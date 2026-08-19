import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from patient_notification_hub.registry import get_resolver
from patient_notification_hub.rendering import (
	STANDARD_DOCUMENT_FIELDS,
	compile_preview,
	validate_field_path,
)
from patient_notification_hub.rules import SUPPORTED_OPERATORS, clear_rule_cache


class PatientNotificationRule(Document):
	def validate(self):
		self.rule_key = (self.rule_key or "").strip()
		self.event_type = (self.event_type or "").strip()
		self.template_name = (self.template_name or "").strip()
		self.language_code = (self.language_code or "").strip() or "en"

		if not self.rule_key or not self.event_type:
			frappe.throw(_("Rule Key and Event Type are required."))
		if not cint(self.enabled):
			return
		if not frappe.db.exists("DocType", self.reference_doctype):
			frappe.throw(_("Reference DocType {0} does not exist.").format(self.reference_doctype))
		if not self.template_name:
			frappe.throw(_("Interakt Template Name is required."))
		if self.trigger_mode != "Document Event":
			self._validate_watched_field()
		self._validate_recipient()
		self._validate_conditions()
		self._validate_variables()
		compile_preview(self.preview_template or "")
		compile_preview(self.event_key_template or "")

	def on_update(self):
		clear_rule_cache()
		frappe.db.after_commit.add(clear_rule_cache)

	def on_trash(self):
		clear_rule_cache()
		frappe.db.after_commit.add(clear_rule_cache)

	def _validate_watched_field(self):
		if not self.watched_field:
			frappe.throw(_("Watched Field is required for field-based triggers."))
		if not frappe.get_meta(self.reference_doctype).has_field(self.watched_field):
			frappe.throw(
				_("Field {0} does not exist on {1}.").format(self.watched_field, self.reference_doctype)
			)
		if self.trigger_mode == "Field Changed To Value" and not self.target_value:
			frappe.throw(_("Target Value is required for Field Changed To Value rules."))

	def _validate_recipient(self):
		if self.recipient_mode == "Registered Resolver":
			get_resolver(self.recipient_resolver)
			return
		if not self.patient_field:
			frappe.throw(_("Patient Field is required."))
		field = frappe.get_meta(self.reference_doctype).get_field(self.patient_field)
		if not field or field.fieldtype != "Link" or field.options != "Patient":
			frappe.throw(_("{0} must be a Link to Patient.").format(self.patient_field))

	def _validate_conditions(self):
		if not self.conditions_json:
			return
		try:
			conditions = json.loads(self.conditions_json)
		except ValueError:
			frappe.throw(_("Conditions must contain valid JSON."))
		if not isinstance(conditions, (dict, list)):
			frappe.throw(_("Conditions must be a JSON object or list."))
		if isinstance(conditions, dict):
			for fieldname in conditions:
				self._validate_condition_field(fieldname)
			return
		for condition in conditions:
			if not isinstance(condition, list) or len(condition) != 3:
				frappe.throw(_("Each condition must be [field, operator, value]."))
			fieldname, operator, expected = condition
			self._validate_condition_field(fieldname)
			if operator not in SUPPORTED_OPERATORS:
				frappe.throw(_("Unsupported condition operator: {0}").format(operator))
			if operator in {"in", "not in"} and not isinstance(expected, (list, tuple)):
				frappe.throw(_("Operator {0} requires a list value.").format(operator))
			if operator in {"is", "is not"} and expected not in {"set", "not set"}:
				frappe.throw(_("Operator {0} requires 'set' or 'not set'.").format(operator))

	def _validate_condition_field(self, fieldname):
		if not isinstance(fieldname, str) or not fieldname.strip():
			frappe.throw(_("Condition field must be a non-empty field name."))
		if fieldname not in STANDARD_DOCUMENT_FIELDS and not frappe.get_meta(self.reference_doctype).has_field(
			fieldname
		):
			frappe.throw(_("Condition field {0} does not exist on {1}.").format(fieldname, self.reference_doctype))

	def _validate_variables(self):
		positions = [cint(row.position) for row in self.variables]
		if len(positions) != len(set(positions)) or sorted(positions) != list(range(1, len(positions) + 1)):
			frappe.throw(_("Variable positions must be unique and sequential from 1."))
		for row in self.variables:
			if row.source_type == "Registered Resolver":
				get_resolver(row.source)
			elif row.source_type == "Jinja":
				compile_preview(row.source)
			elif row.source_type in {"Document Field", "Linked Field"}:
				validate_field_path(self.reference_doctype, row.source)


@frappe.whitelist()
def test_rule(name: str, reference_name: str):
	frappe.only_for("System Manager")
	rule = frappe.get_doc("Patient Notification Rule", name)
	was_enabled = rule.enabled
	try:
		rule.enabled = 1
		rule.validate()
	finally:
		rule.enabled = was_enabled
	doc = frappe.get_doc(rule.reference_doctype, reference_name)
	from patient_notification_hub.events import resolve_patient
	from patient_notification_hub.rendering import render_event_key, render_preview, resolve_variables

	patient_name = resolve_patient(rule, doc)
	if not patient_name or not frappe.db.exists("Patient", patient_name):
		frappe.throw(_("Patient could not be resolved for this document."))
	patient_record = frappe.get_cached_doc("Patient", patient_name)
	patient = frappe._dict(name=patient_record.name, patient_name=patient_record.get("patient_name"))
	values = resolve_variables(rule, doc, None, patient)
	return {
		"patient": patient_name,
		"event_key": render_event_key(rule, doc, None),
		"body_values": values,
		"preview": render_preview(rule, doc, None, patient, values),
	}
