from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint, now_datetime


NOTIFICATION_DOCTYPE = "Patient Notification"


def create_notification(
	*,
	rule,
	event_key: str,
	patient: str,
	reference_doctype: str,
	reference_name: str,
	body_values: list[str],
	body_preview: str,
	context: dict[str, Any] | None = None,
	settings=None,
) -> str | None:
	if not event_key:
		raise ValueError("Event key is required.")
	existing = frappe.db.get_value(NOTIFICATION_DOCTYPE, {"event_key": event_key}, "name")
	if existing:
		return existing

	settings = settings or frappe.get_cached_doc("Patient Notification Settings")
	dry_run = bool(cint(settings.dry_run))
	notification = frappe.get_doc(
		{
			"doctype": NOTIFICATION_DOCTYPE,
			"event_key": event_key,
			"rule": rule.name,
			"rule_key": rule.rule_key,
			"event_type": rule.event_type,
			"status": "Skipped" if dry_run else "Queued",
			"patient": patient,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"template_name": rule.template_name,
			"language_code": rule.language_code,
			"body_values_json": frappe.as_json(body_values),
			"body_preview": body_preview,
			"context_json": frappe.as_json(context or {}),
			"queued_on": now_datetime(),
			"skip_reason": "Dry run is enabled." if dry_run else None,
		}
	)

	savepoint = "patient_notification_insert"
	frappe.db.savepoint(savepoint)
	try:
		notification.insert(ignore_permissions=True)
		frappe.db.release_savepoint(savepoint)
	except frappe.DuplicateEntryError:
		frappe.db.rollback(save_point=savepoint)
		return frappe.db.get_value(NOTIFICATION_DOCTYPE, {"event_key": event_key}, "name")

	if not dry_run:
		enqueue_notification(notification.name, enqueue_after_commit=True)
	return notification.name


def enqueue_notification(notification_name: str, *, enqueue_after_commit: bool) -> None:
	frappe.enqueue(
		"patient_notification_hub.workers.send_notification",
		queue="short",
		timeout=90,
		enqueue_after_commit=enqueue_after_commit,
		job_id=f"patient_notification_{notification_name}",
		deduplicate=True,
		notification_name=notification_name,
	)
