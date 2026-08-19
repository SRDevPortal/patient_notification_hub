from __future__ import annotations

import hashlib
import json
import re

import frappe
from frappe.utils import add_to_date, cint, cstr, now_datetime


EVENT_DOCTYPE = "Patient Notification Event"
ERROR_MESSAGE_LIMIT = 4000
BASE_SNAPSHOT_FIELDS = {
	"doctype",
	"name",
	"modified",
	"docstatus",
}
BUILTIN_RESOLVER_FIELDS = {
	"invoice_amount": {"rounded_total", "grand_total", "currency"},
	"patient_name": set(),
}
TEMPLATE_FIELD_PATTERN = re.compile(r"\b(?:doc|previous_doc)\.([A-Za-z_][A-Za-z0-9_]*)")
SENSITIVE_FIELD_NAMES = {
	"api_key",
	"api_secret",
	"access_token",
	"password",
	"secret",
	"token",
	"webhook_secret",
}


def capture_failed_event(rule, doc, previous_doc, document_event: str, error: Exception) -> str | None:
	if not frappe.db.exists("DocType", EVENT_DOCTYPE):
		return None
	raw_key = "|".join(
		[
			cstr(rule.name),
			cstr(doc.doctype),
			cstr(doc.name),
			cstr(document_event),
			cstr(doc.get("modified")),
			cstr(doc.get(rule.watched_field)) if rule.watched_field else "",
			cstr(previous_doc.get(rule.watched_field)) if previous_doc and rule.watched_field else "",
		]
	)
	event_key = f"event:{hashlib.sha256(raw_key.encode()).hexdigest()}"
	existing = frappe.db.get_value(EVENT_DOCTYPE, {"event_key": event_key}, "name")
	if existing:
		return existing

	event = frappe.get_doc(
		{
			"doctype": EVENT_DOCTYPE,
			"event_key": event_key,
			"rule": rule.name,
			"rule_key": rule.rule_key,
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"document_event": document_event,
			"status": "Captured",
			"document_json": frappe.as_json(_snapshot(rule, doc)),
			"previous_document_json": frappe.as_json(_snapshot(rule, previous_doc)) if previous_doc else None,
			"captured_on": now_datetime(),
			"last_error": cstr(error)[:ERROR_MESSAGE_LIMIT],
		}
	)
	savepoint = "patient_notification_event_insert"
	frappe.db.savepoint(savepoint)
	try:
		event.insert(ignore_permissions=True)
		frappe.db.release_savepoint(savepoint)
	except frappe.DuplicateEntryError:
		frappe.db.rollback(save_point=savepoint)
		return frappe.db.get_value(EVENT_DOCTYPE, {"event_key": event_key}, "name")
	enqueue_event(event.name, enqueue_after_commit=True)
	return event.name


def _as_dict(doc):
	if callable(getattr(doc, "as_dict", None)):
		return doc.as_dict()
	return dict(doc or {})


def _snapshot(rule, doc):
	payload = _remove_password_fields(_as_dict(doc))
	allowed_fields = _snapshot_fields(rule)
	return {key: value for key, value in payload.items() if key in allowed_fields}


def _snapshot_fields(rule) -> set[str]:
	fields = set(BASE_SNAPSHOT_FIELDS)
	for fieldname in (rule.get("watched_field"), rule.get("patient_field")):
		if fieldname:
			fields.add(cstr(fieldname).split(".", 1)[0])

	try:
		conditions = json.loads(rule.get("conditions_json") or "[]")
	except (TypeError, ValueError):
		conditions = []
	if isinstance(conditions, dict):
		fields.update(cstr(fieldname) for fieldname in conditions)
	elif isinstance(conditions, list):
		fields.update(
			cstr(condition[0])
			for condition in conditions
			if isinstance(condition, list) and len(condition) == 3
		)

	for variable in rule.get("variables") or []:
		source_type = cstr(variable.get("source_type"))
		source = cstr(variable.get("source"))
		if source_type in {"Document Field", "Linked Field"} and source:
			fields.add(source.split(".", 1)[0])
		elif source_type == "Jinja":
			fields.update(TEMPLATE_FIELD_PATTERN.findall(source))
		elif source_type == "Registered Resolver":
			fields.update(BUILTIN_RESOLVER_FIELDS.get(source, set()))
		if variable.get("format_type") == "Currency":
			fields.add("currency")

	for template in (rule.get("event_key_template"), rule.get("preview_template")):
		fields.update(TEMPLATE_FIELD_PATTERN.findall(cstr(template)))
	return {fieldname for fieldname in fields if fieldname}


def _remove_password_fields(value):
	if isinstance(value, list):
		return [_remove_password_fields(item) for item in value]
	if not isinstance(value, dict):
		return value
	password_fields = set()
	doctype = cstr(value.get("doctype")).strip()
	if doctype:
		try:
			password_fields = {
				field.fieldname for field in frappe.get_meta(doctype).fields if field.fieldtype == "Password"
			}
		except Exception:
			pass
	return {
		key: _remove_password_fields(item)
		for key, item in value.items()
		if key not in password_fields and cstr(key).lower() not in SENSITIVE_FIELD_NAMES
	}


def enqueue_event(event_name: str, *, enqueue_after_commit: bool) -> None:
	frappe.enqueue(
		"patient_notification_hub.event_inbox.process_event",
		queue="short",
		timeout=90,
		enqueue_after_commit=enqueue_after_commit,
		job_id=f"patient_notification_event_{event_name}",
		deduplicate=True,
		event_name=event_name,
	)


def process_event(event_name: str):
	settings = frappe.get_cached_doc("Patient Notification Settings")
	event = frappe.get_doc(EVENT_DOCTYPE, event_name)
	if event.status in {"Processed", "Discarded", "Processing"}:
		return {"success": event.status == "Processed", "status": event.status}
	rule = frappe.get_cached_doc("Patient Notification Rule", event.rule) if event.rule else None
	if not cint(settings.enabled) or not rule or not cint(rule.enabled):
		return {"success": False, "status": "Paused"}

	event = claim_event(event, max(cint(settings.maximum_attempts), 1))
	if not event:
		status = frappe.db.get_value(EVENT_DOCTYPE, event_name, "status")
		return {"success": status == "Processed", "status": status or "Missing"}

	try:
		from patient_notification_hub.events import process_rule

		doc = frappe._dict(frappe.parse_json(event.document_json or "{}"))
		previous_doc = frappe._dict(frappe.parse_json(event.previous_document_json or "{}"))
		notification = process_rule(rule, doc, previous_doc, event.document_event, settings)
	except Exception as exc:
		frappe.db.rollback()
		event = frappe.get_doc(EVENT_DOCTYPE, event_name)
		return mark_event_failed(event, settings, exc)

	event.status = "Processed"
	event.notification = notification
	event.processed_on = now_datetime()
	event.next_retry_on = None
	event.last_error = None
	event.document_json = None
	event.previous_document_json = None
	event.snapshot_purged_on = now_datetime()
	event.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "status": "Processed", "notification": notification}


def claim_event(event, maximum_attempts: int):
	rows = frappe.db.sql(
		f"""
		select status, attempt_count
		from `tab{EVENT_DOCTYPE}`
		where name = %s
		for update
		""",
		(event.name,),
		as_dict=True,
	)
	if not rows:
		frappe.db.rollback()
		return None
	current = rows[0]
	if current.status not in {"Captured", "Failed"} or cint(current.attempt_count) >= maximum_attempts:
		frappe.db.rollback()
		return None
	attempt_count = cint(current.attempt_count) + 1
	frappe.db.set_value(
		EVENT_DOCTYPE,
		event.name,
		{
			"status": "Processing",
			"attempt_count": attempt_count,
			"last_attempt_on": now_datetime(),
			"next_retry_on": None,
		},
		update_modified=False,
	)
	frappe.db.commit()
	event.status = "Processing"
	event.attempt_count = attempt_count
	return event


def mark_event_failed(event, settings, error: Exception):
	maximum_attempts = max(cint(settings.maximum_attempts), 1)
	base_delay = max(cint(settings.base_retry_delay_minutes), 1)
	event.status = "Failed"
	event.last_error = cstr(error)[:ERROR_MESSAGE_LIMIT]
	event.next_retry_on = (
		add_to_date(
			now_datetime(),
			minutes=base_delay * (2 ** max(cint(event.attempt_count) - 1, 0)),
			as_datetime=True,
		)
		if cint(event.attempt_count) < maximum_attempts
		else None
	)
	event.save(ignore_permissions=True)
	frappe.db.commit()
	frappe.log_error(frappe.get_traceback(), f"Patient Notification Event failed for {event.name}")
	return {"success": False, "status": "Failed", "error": cstr(error)}


def process_retryable_events(settings=None) -> int:
	settings = settings or frappe.get_cached_doc("Patient Notification Settings")
	if not cint(settings.enabled) or not cint(settings.enable_background_recovery):
		return 0
	maximum_attempts = max(cint(settings.maximum_attempts), 1)
	batch_size = max(cint(settings.worker_batch_size), 1)
	now = now_datetime()
	processing_cutoff = add_to_date(
		now,
		minutes=-max(cint(getattr(settings, "stale_sending_timeout_minutes", 15)), 1),
		as_datetime=True,
	)
	stale_processing = frappe.get_all(
		EVENT_DOCTYPE,
		filters={"status": "Processing", "last_attempt_on": ["<=", processing_cutoff]},
		fields=["name"],
		order_by="last_attempt_on asc",
		limit_start=0,
		limit_page_length=batch_size,
	)
	if stale_processing:
		frappe.db.set_value(
			EVENT_DOCTYPE,
			{"name": ["in", [row.name for row in stale_processing]], "status": "Processing"},
			{
				"status": "Failed",
				"next_retry_on": now,
				"last_error": "Recovered after stale event Processing timeout.",
			},
		)
		frappe.db.commit()
	cutoff = add_to_date(
		now,
		minutes=-max(cint(getattr(settings, "queued_recovery_timeout_minutes", 10)), 1),
		as_datetime=True,
	)
	captured = frappe.get_all(
		EVENT_DOCTYPE,
		filters={"status": "Captured", "captured_on": ["<=", cutoff]},
		fields=["name"],
		order_by="captured_on asc",
		limit_start=0,
		limit_page_length=batch_size,
	)
	remaining = batch_size - len(captured)
	failed = (
		frappe.get_all(
			EVENT_DOCTYPE,
			filters={
				"status": "Failed",
				"next_retry_on": ["<=", now],
				"attempt_count": ["<", maximum_attempts],
			},
			fields=["name"],
			order_by="next_retry_on asc",
			limit_start=0,
			limit_page_length=remaining,
		)
		if remaining
		else []
	)
	rows = [*captured, *failed]
	for row in rows:
		enqueue_event(row.name, enqueue_after_commit=False)
	return len(rows)


def purge_expired_event_snapshots(settings=None) -> int:
	if not frappe.db.exists("DocType", EVENT_DOCTYPE):
		return 0
	settings = settings or frappe.get_cached_doc("Patient Notification Settings")
	retention_days = max(cint(getattr(settings, "event_snapshot_retention_days", 7)), 1)
	batch_size = max(cint(getattr(settings, "worker_batch_size", 50)), 1)
	now = now_datetime()
	cutoff = add_to_date(now, days=-retention_days, as_datetime=True)

	completed = frappe.get_all(
		EVENT_DOCTYPE,
		filters={
			"status": ["in", ["Processed", "Discarded"]],
			"snapshot_purged_on": ["is", "not set"],
		},
		fields=["name"],
		limit_start=0,
		limit_page_length=batch_size,
	)
	remaining = max(batch_size - len(completed), 0)
	expired = (
		frappe.get_all(
			EVENT_DOCTYPE,
			filters={
				"status": ["in", ["Captured", "Failed"]],
				"captured_on": ["<=", cutoff],
			},
			fields=["name"],
			limit_start=0,
			limit_page_length=remaining,
		)
		if remaining
		else []
	)

	for row in completed:
		frappe.db.set_value(
			EVENT_DOCTYPE,
			row.name,
			{
				"document_json": None,
				"previous_document_json": None,
				"snapshot_purged_on": now,
			},
			update_modified=False,
		)
	for row in expired:
		frappe.db.set_value(
			EVENT_DOCTYPE,
			row.name,
			{
				"status": "Discarded",
				"document_json": None,
				"previous_document_json": None,
				"snapshot_purged_on": now,
				"next_retry_on": None,
				"last_error": "Event snapshot expired before successful replay.",
			},
			update_modified=False,
		)
	if completed or expired:
		frappe.db.commit()
	return len(completed) + len(expired)

