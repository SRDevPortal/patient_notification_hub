from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from patient_notification_hub.outbox import create_notification


class TestPatientNotificationOutbox(FrappeTestCase):
	def test_dry_run_creates_one_skipped_record(self):
		rule = frappe.get_doc("Patient Notification Rule", "sales_invoice_generated")
		settings = frappe._dict(dry_run=1)
		event_key = "test:patient_notification_hub:dry_run"

		with patch("patient_notification_hub.outbox.enqueue_notification") as enqueue:
			first = create_notification(
				rule=rule,
				event_key=event_key,
				patient="",
				reference_doctype="",
				reference_name="",
				body_values=["Patient", "TEST-INVOICE"],
				body_preview="Test preview",
				settings=settings,
			)
			second = create_notification(
				rule=rule,
				event_key=event_key,
				patient="",
				reference_doctype="",
				reference_name="",
				body_values=["Patient", "TEST-INVOICE"],
				body_preview="Test preview",
				settings=settings,
			)

		self.assertEqual(first, second)
		self.assertEqual(frappe.db.get_value("Patient Notification", first, "status"), "Skipped")
		enqueue.assert_not_called()
		frappe.delete_doc("Patient Notification", first, force=True, ignore_permissions=True)
