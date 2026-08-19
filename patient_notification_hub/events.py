from __future__ import annotations

import frappe
from frappe.utils import cint, cstr

from patient_notification_hub.event_inbox import capture_failed_event
from patient_notification_hub.outbox import create_notification
from patient_notification_hub.ownership import hub_owns_rule
from patient_notification_hub.registry import get_resolver
from patient_notification_hub.rendering import (
	render_event_key,
	render_preview,
	resolve_variables,
)
from patient_notification_hub.rules import get_enabled_rules, matches_conditions, matches_trigger


OWN_DOCTYPES = {
	"Patient Notification",
	"Patient Notification Event",
	"Patient Notification Rule",
	"Patient Notification Settings",
	"Patient Notification Variable",
}


def after_insert(doc, method=None):
	process_document_event(doc, "After Insert")


def on_update(doc, method=None):
	process_document_event(doc, "On Update")


def on_submit(doc, method=None):
	process_document_event(doc, "On Submit")


def on_cancel(doc, method=None):
	process_document_event(doc, "On Cancel")


def process_document_event(doc, document_event: str):
	if frappe.flags.in_install or frappe.flags.in_migrate:
		return []
	if doc.doctype in OWN_DOCTYPES:
		return []
	try:
		settings = frappe.get_cached_doc("Patient Notification Settings")
	except (frappe.DoesNotExistError, ImportError):
		return []
	if not cint(settings.enabled):
		return []

	previous_doc = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	created = []
	for rule in get_enabled_rules(doc.doctype, document_event):
		try:
			if not hub_owns_rule(rule.rule_key):
				continue
			if not matches_trigger(rule, doc, previous_doc) or not matches_conditions(rule, doc):
				continue
			notification = process_rule(rule, doc, previous_doc, document_event, settings)
			if notification:
				created.append(notification)
		except Exception as exc:
			try:
				capture_failed_event(rule, doc, previous_doc, document_event, exc)
			except Exception:
				frappe.log_error(
					frappe.get_traceback(),
					f"Patient Notification event capture failed for {doc.doctype} {doc.name}",
				)
			frappe.log_error(
				frappe.get_traceback(),
				f"Patient Notification rule {rule.name} failed for {doc.doctype} {doc.name}",
			)
	return created


def process_rule(rule, doc, previous_doc, document_event: str, settings=None):
	settings = settings or frappe.get_cached_doc("Patient Notification Settings")
	if not hub_owns_rule(rule.rule_key):
		return None
	patient_name = resolve_patient(rule, doc, previous_doc)
	if not patient_name or not frappe.db.exists("Patient", patient_name):
		raise frappe.ValidationError(f"Patient could not be resolved for {doc.doctype} {doc.name}.")
	if settings.pilot_patient and settings.pilot_patient != patient_name:
		return None

	patient_record = frappe.get_cached_doc("Patient", patient_name)
	patient_doc = frappe._dict(
		name=patient_record.name,
		patient_name=patient_record.get("patient_name"),
	)
	body_values = resolve_variables(rule, doc, previous_doc, patient_doc)
	preview = render_preview(rule, doc, previous_doc, patient_doc, body_values)
	event_key = render_event_key(rule, doc, previous_doc)
	return create_notification(
		rule=rule,
		event_key=event_key,
		patient=patient_name,
		reference_doctype=doc.doctype,
		reference_name=doc.name,
		body_values=body_values,
		body_preview=preview,
		context={
			"document_event": document_event,
			"watched_field": rule.watched_field,
			"previous_value": (
				cstr(previous_doc.get(rule.watched_field))
				if previous_doc and rule.watched_field
				else None
			),
			"current_value": cstr(doc.get(rule.watched_field)) if rule.watched_field else None,
		},
		settings=settings,
	)


def resolve_patient(rule, doc, previous_doc=None) -> str:
	if rule.recipient_mode == "Registered Resolver":
		resolver = get_resolver(rule.recipient_resolver)
		return cstr(resolver(doc=doc, previous_doc=previous_doc, rule=rule)).strip()
	return cstr(doc.get(rule.patient_field)).strip()
