from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, format_date, format_datetime
from frappe.utils.jinja import validate_template

from patient_notification_hub.registry import get_resolver


def compile_preview(template: str) -> None:
	validate_template(template)


def resolve_variables(rule, doc, previous_doc, patient_doc) -> list[str]:
	rows = sorted(rule.variables or [], key=lambda row: cint(row.position))
	values = []
	for row in rows:
		value = resolve_variable(row, rule, doc, previous_doc, patient_doc)
		if (value is None or value == "") and row.default_value:
			value = row.default_value
		if row.required and (value is None or value == ""):
			frappe.throw(
				_("Required notification variable {0} is empty for rule {1}.").format(
					row.position, rule.rule_key
				)
			)
		values.append(format_value(value, row.format_type, doc))
	return values


def resolve_variable(row, rule, doc, previous_doc, patient_doc):
	context = {
		"doc": doc,
		"previous_doc": previous_doc or {},
		"patient": patient_doc,
		"rule": rule,
	}
	if row.source_type in {"Document Field", "Linked Field"}:
		return resolve_field_path(doc, row.source)
	if row.source_type == "Static Value":
		return row.source
	if row.source_type == "Jinja":
		return frappe.render_template(row.source, context)
	if row.source_type == "Registered Resolver":
		resolver = get_resolver(row.source)
		return resolver(
			doc=doc,
			previous_doc=previous_doc,
			patient=patient_doc,
			rule=rule,
			variable=row,
		)
	frappe.throw(_("Unsupported notification variable source type: {0}").format(row.source_type))


def resolve_field_path(doc, path: str):
	parts = [part.strip() for part in cstr(path).split(".") if part.strip()]
	if not parts:
		return ""

	current: Any = doc
	current_doctype = doc.doctype
	for index, part in enumerate(parts):
		value = current.get(part) if hasattr(current, "get") else None
		if index == len(parts) - 1:
			return value
		field = frappe.get_meta(current_doctype).get_field(part)
		if not field or field.fieldtype != "Link" or not field.options or not value:
			return ""
		current_doctype = field.options
		current = frappe.get_cached_doc(current_doctype, value)
	return ""


def format_value(value, format_type: str, doc) -> str:
	if value is None:
		return ""
	if format_type == "Date":
		return format_date(value) if value else ""
	if format_type == "Datetime":
		return format_datetime(value) if value else ""
	if format_type == "Number":
		return f"{flt(value):.2f}"
	if format_type == "Currency":
		currency = cstr(doc.get("currency")).strip()
		return f"{currency} {flt(value):.2f}".strip()
	return cstr(value)


def render_preview(rule, doc, previous_doc, patient_doc, values: list[str]) -> str:
	if not rule.preview_template:
		return f"Template: {rule.template_name}"
	return cstr(
		frappe.render_template(
			rule.preview_template,
			{
				"doc": doc,
				"previous_doc": previous_doc or {},
				"patient": patient_doc,
				"rule": rule,
				"values": values,
			},
		)
	).strip()


def render_event_key(rule, doc, previous_doc) -> str:
	if rule.event_key_template:
		return cstr(
			frappe.render_template(
				rule.event_key_template,
				{"doc": doc, "previous_doc": previous_doc or {}, "rule": rule},
			)
		).strip()

	parts = ["rule", rule.rule_key, doc.doctype, doc.name]
	if rule.deduplication_scope == "Once Per Target Value":
		parts.append(cstr(rule.target_value or doc.get(rule.watched_field)))
	elif rule.deduplication_scope == "Every Transition":
		parts.append(cstr(doc.modified))
	return ":".join(parts)
