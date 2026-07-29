import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from patient_notification_hub.registry import get_resolver
from patient_notification_hub.rendering import compile_preview
from patient_notification_hub.rules import clear_rule_cache


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

	def on_update(self):
		clear_rule_cache()

	def on_trash(self):
		clear_rule_cache()

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

	def _validate_variables(self):
		positions = [cint(row.position) for row in self.variables]
		if len(positions) != len(set(positions)) or sorted(positions) != list(range(1, len(positions) + 1)):
			frappe.throw(_("Variable positions must be unique and sequential from 1."))
		for row in self.variables:
			if row.source_type == "Registered Resolver":
				get_resolver(row.source)
