from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import add_to_date, cint, cstr, now_datetime

from patient_notification_hub.outbox import NOTIFICATION_DOCTYPE, enqueue_notification
from patient_notification_hub.transport import send_whatsapp_template


ERROR_MESSAGE_LIMIT = 4000


def reconcile_notifications() -> dict[str, int]:
	settings = frappe.get_cached_doc("Patient Notification Settings")
	if (
		not cint(settings.enabled)
		or cint(settings.dry_run)
		or not cint(settings.enable_background_recovery)
	):
		return {"queued": 0, "failed": 0, "stale": 0}

	stale = recover_stale_notifications(settings) if cint(settings.enable_stale_sending_recovery) else 0
	failed = process_retryable_notifications(settings) if cint(settings.enable_failed_retry) else 0
	queued = process_queued_notifications(settings) if cint(settings.enable_queued_recovery) else 0
	return {"queued": queued, "failed": failed, "stale": stale}


def send_notification(notification_name: str) -> dict[str, Any]:
	notification = frappe.get_doc(NOTIFICATION_DOCTYPE, notification_name)
	if notification.status in {"Sent", "Skipped", "Sending"}:
		return {"success": notification.status == "Sent", "status": notification.status}

	settings = frappe.get_cached_doc("Patient Notification Settings")
	rule = frappe.get_cached_doc("Patient Notification Rule", notification.rule) if notification.rule else None
	if not cint(settings.enabled) or not rule or not cint(rule.enabled):
		return mark_skipped(notification, "Notification settings or rule is disabled.")
	if settings.pilot_patient and settings.pilot_patient != notification.patient:
		return mark_skipped(notification, "Patient is outside the configured pilot.")
	if cint(settings.dry_run):
		return mark_skipped(notification, "Dry run is enabled.")

	maximum_attempts = max(cint(settings.maximum_attempts), 1)
	if cint(notification.attempt_count) >= maximum_attempts:
		return mark_failed_without_retry(notification, "Maximum attempts reached.")

	notification = claim_notification(notification, maximum_attempts)
	if not notification:
		status = frappe.db.get_value(NOTIFICATION_DOCTYPE, notification_name, "status")
		return {"success": status == "Sent", "status": status or "Missing"}

	try:
		result = send_whatsapp_template(notification, settings)
	except Exception as exc:
		mark_failed(notification, settings, exc)
		return {"success": False, "status": "Failed", "error": cstr(exc)}

	notification.status = "Sent"
	notification.channel_account = result.get("channel_account")
	notification.routing_source = result.get("routing_source")
	notification.conversation = result.get("conversation")
	notification.chat_message = result.get("message")
	notification.provider_message_id = result.get("provider_message_id")
	notification.sent_on = now_datetime()
	notification.sending_started_on = None
	notification.next_retry_on = None
	notification.last_error = None
	notification.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "status": "Sent", **result}


def claim_notification(notification, maximum_attempts: int):
	rows = frappe.db.sql(
		f"""
		select status, attempt_count
		from `tab{NOTIFICATION_DOCTYPE}`
		where name = %s
		for update
		""",
		(notification.name,),
		as_dict=True,
	)
	if not rows:
		frappe.db.rollback()
		return None
	current = rows[0]
	if current.status not in {"Queued", "Failed"} or cint(current.attempt_count) >= maximum_attempts:
		frappe.db.rollback()
		return None

	started_on = now_datetime()
	attempt_count = cint(current.attempt_count) + 1
	frappe.db.set_value(
		NOTIFICATION_DOCTYPE,
		notification.name,
		{
			"status": "Sending",
			"sending_started_on": started_on,
			"attempt_count": attempt_count,
			"next_retry_on": None,
			"last_error": None,
		},
		update_modified=False,
	)
	frappe.db.commit()
	notification.status = "Sending"
	notification.sending_started_on = started_on
	notification.attempt_count = attempt_count
	notification.next_retry_on = None
	notification.last_error = None
	return notification


def mark_skipped(notification, reason: str) -> dict[str, Any]:
	notification.status = "Skipped"
	notification.skip_reason = reason
	notification.sending_started_on = None
	notification.next_retry_on = None
	notification.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": False, "status": "Skipped", "reason": reason}


def mark_failed(notification, settings, error: Exception) -> None:
	maximum_attempts = max(cint(settings.maximum_attempts), 1)
	attempt_count = cint(notification.attempt_count)
	base_delay = max(cint(settings.base_retry_delay_minutes), 1)
	notification.status = "Failed"
	notification.sending_started_on = None
	notification.last_error = cstr(error)[:ERROR_MESSAGE_LIMIT]
	notification.next_retry_on = (
		add_to_date(
			now_datetime(),
			minutes=base_delay * (2 ** max(attempt_count - 1, 0)),
			as_datetime=True,
		)
		if attempt_count < maximum_attempts
		else None
	)
	notification.save(ignore_permissions=True)
	frappe.db.commit()
	frappe.log_error(frappe.get_traceback(), f"Patient Notification send failed for {notification.name}")


def mark_failed_without_retry(notification, error: str) -> dict[str, Any]:
	notification.status = "Failed"
	notification.sending_started_on = None
	notification.next_retry_on = None
	notification.last_error = error
	notification.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": False, "status": "Failed", "error": error}


def process_retryable_notifications(settings=None) -> int:
	settings = settings or frappe.get_cached_doc("Patient Notification Settings")
	if (
		not cint(settings.enabled)
		or cint(settings.dry_run)
		or not cint(settings.enable_background_recovery)
		or not cint(settings.enable_failed_retry)
	):
		return 0
	rows = frappe.get_all(
		NOTIFICATION_DOCTYPE,
		filters={
			"status": "Failed",
			"next_retry_on": ["<=", now_datetime()],
			"attempt_count": ["<", max(cint(settings.maximum_attempts), 1)],
		},
		fields=["name"],
		order_by="next_retry_on asc",
		limit_start=0,
		limit_page_length=max(cint(settings.worker_batch_size), 1),
	)
	names = [row.name for row in rows]
	for name in names:
		enqueue_notification(name, enqueue_after_commit=False)
	return len(names)


def process_queued_notifications(settings=None) -> int:
	settings = settings or frappe.get_cached_doc("Patient Notification Settings")
	if (
		not cint(settings.enabled)
		or cint(settings.dry_run)
		or not cint(settings.enable_background_recovery)
		or not cint(settings.enable_queued_recovery)
	):
		return 0
	cutoff = add_to_date(
		now_datetime(),
		minutes=-max(cint(settings.queued_recovery_timeout_minutes), 1),
		as_datetime=True,
	)
	rows = frappe.get_all(
		NOTIFICATION_DOCTYPE,
		filters={"status": "Queued", "queued_on": ["<=", cutoff]},
		fields=["name"],
		order_by="queued_on asc",
		limit_start=0,
		limit_page_length=max(cint(settings.worker_batch_size), 1),
	)
	names = [row.name for row in rows]
	for name in names:
		enqueue_notification(name, enqueue_after_commit=False)
	return len(names)


def recover_stale_notifications(settings=None) -> int:
	settings = settings or frappe.get_cached_doc("Patient Notification Settings")
	if (
		not cint(settings.enabled)
		or cint(settings.dry_run)
		or not cint(settings.enable_background_recovery)
		or not cint(settings.enable_stale_sending_recovery)
	):
		return 0
	cutoff = add_to_date(
		now_datetime(),
		minutes=-max(cint(settings.stale_sending_timeout_minutes), 1),
		as_datetime=True,
	)
	rows = frappe.get_all(
		NOTIFICATION_DOCTYPE,
		filters={"status": "Sending", "sending_started_on": ["<=", cutoff]},
		fields=["name"],
		order_by="sending_started_on asc",
		limit_start=0,
		limit_page_length=max(cint(settings.worker_batch_size), 1),
	)
	names = [row.name for row in rows]
	if not names:
		return 0
	frappe.db.set_value(
		NOTIFICATION_DOCTYPE,
		{
			"name": ["in", names],
			"status": "Sending",
		},
		{
			"status": "Failed",
			"sending_started_on": None,
			"last_error": "Recovered after stale Sending timeout.",
			"next_retry_on": now_datetime(),
		},
	)
	frappe.db.commit()
	return len(names)
