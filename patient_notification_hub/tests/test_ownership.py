from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from patient_notification_hub.ownership import hub_owns_rule


class TestPatientNotificationOwnership(FrappeTestCase):
	@patch("patient_notification_hub.ownership.frappe.db.get_single_value", return_value="Legacy Shipment Tracking")
	@patch("patient_notification_hub.ownership.frappe.db.exists", return_value=True)
	def test_legacy_engine_suppresses_overlapping_hub_rules(self, exists, get_single_value):
		self.assertFalse(hub_owns_rule("sales_invoice_generated"))
		self.assertFalse(hub_owns_rule("order_picked_up"))
		self.assertFalse(hub_owns_rule("out_for_delivery"))
		self.assertTrue(hub_owns_rule("patient_encounter_submitted"))

	@patch("patient_notification_hub.ownership.frappe.db.get_single_value", return_value="Patient Notification Hub")
	@patch("patient_notification_hub.ownership.frappe.db.exists", return_value=True)
	def test_hub_engine_owns_overlapping_rules(self, exists, get_single_value):
		self.assertTrue(hub_owns_rule("sales_invoice_generated"))
