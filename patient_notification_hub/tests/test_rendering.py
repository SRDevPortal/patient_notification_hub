import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from patient_notification_hub.rendering import render_preview, resolve_variables
from patient_notification_hub.setup import INITIAL_RULES


class TestPatientNotificationRendering(FrappeTestCase):
	def test_initial_invoice_values_and_preview(self):
		rule = frappe.get_doc("Patient Notification Rule", "sales_invoice_generated")
		patient = frappe._dict(name="PAT-0001", patient_name="Test Patient")
		doc = frappe._dict(
			doctype="Sales Invoice",
			name="SINV-0001",
			patient="PAT-0001",
			posting_date="2026-07-29",
			currency="INR",
			rounded_total=1250,
			grand_total=1250,
		)
		values = resolve_variables(rule, doc, None, patient)
		self.assertEqual(values[0], "Test Patient")
		self.assertEqual(values[1], "SINV-0001")
		self.assertEqual(values[3], "INR 1250.00")
		preview = render_preview(rule, doc, None, patient, values)
		self.assertIn("sales invoice SINV-0001", preview)
		self.assertIn("Invoice Amount: INR 1250.00", preview)

	def test_initial_rules_are_disabled_by_default(self):
		self.assertEqual(
			{definition["rule_key"] for definition in INITIAL_RULES},
			{
				"sales_invoice_generated",
				"patient_encounter_submitted",
				"order_picked_up",
				"out_for_delivery",
			},
		)
		enabled_field = frappe.get_meta("Patient Notification Rule").get_field("enabled")
		self.assertEqual(cint(enabled_field.default), 0)

	def test_initial_invoice_rule_is_valid_when_enabled(self):
		rule = frappe.get_doc("Patient Notification Rule", "sales_invoice_generated")
		rule.enabled = 1

		rule.validate()
