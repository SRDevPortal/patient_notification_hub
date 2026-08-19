from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from patient_notification_hub.patient_notification_hub.doctype.patient_notification.patient_notification import (
	retry_notification,
)
from patient_notification_hub.transport import DeliveryNotSentError, send_whatsapp_template
from patient_notification_hub.workers import claim_notification, mark_delivery_failed
from wa_chat_hub.delivery_outcomes import (
	PatientTemplateNotSentError,
	PatientTemplateOutcomeUnknownError,
)


def notification_doc(attempt_count=1):
	return SimpleNamespace(
		name="NOTIF-0001",
		status="Failed",
		patient="PAT-0001",
		template_name="template",
		language_code="en",
		body_values_json="[]",
		body_preview="Preview",
		event_key="event-key",
		attempt_count=attempt_count,
		manual_retry_authorized=0,
		manual_retry_count=0,
		sending_started_on=None,
		next_retry_on=None,
		last_error=None,
		save=Mock(),
	)


class TestDeliveryRecovery(FrappeTestCase):
	@patch("patient_notification_hub.workers.frappe.db.commit")
	def test_definitely_unsent_transient_failure_schedules_retry(self, commit):
		notification = notification_doc(attempt_count=1)
		settings = SimpleNamespace(maximum_attempts=3, base_retry_delay_minutes=5)

		with patch("patient_notification_hub.workers.now_datetime", return_value=datetime(2026, 8, 19)):
			result = mark_delivery_failed(
				notification,
				settings,
				DeliveryNotSentError("provider unavailable", retryable=True),
			)

		self.assertEqual(result["status"], "Failed")
		self.assertTrue(result["retryable"])
		self.assertIsNotNone(notification.next_retry_on)
		notification.save.assert_called_once_with(ignore_permissions=True)
		commit.assert_called_once()

	@patch("patient_notification_hub.workers.frappe.db.commit")
	def test_permanent_rejection_does_not_schedule_retry(self, commit):
		notification = notification_doc(attempt_count=1)
		settings = SimpleNamespace(maximum_attempts=3, base_retry_delay_minutes=5)

		result = mark_delivery_failed(
			notification,
			settings,
			DeliveryNotSentError("invalid template", retryable=False),
		)

		self.assertFalse(result["retryable"])
		self.assertIsNone(notification.next_retry_on)

	@patch("patient_notification_hub.workers.frappe.db.commit")
	@patch("patient_notification_hub.workers.frappe.db.set_value")
	@patch("patient_notification_hub.workers.frappe.db.sql")
	def test_authorized_manual_retry_can_exceed_attempt_limit(self, sql, set_value, commit):
		notification = notification_doc(attempt_count=3)
		notification.status = "Queued"
		notification.manual_retry_authorized = 1
		sql.return_value = [
			frappe._dict(status="Queued", attempt_count=3, manual_retry_authorized=1)
		]

		with patch("patient_notification_hub.workers.now_datetime", return_value=datetime(2026, 8, 19)):
			claimed = claim_notification(notification, maximum_attempts=3)

		self.assertEqual(claimed.attempt_count, 4)
		self.assertEqual(claimed.manual_retry_authorized, 0)
		self.assertEqual(set_value.call_args.args[2]["manual_retry_authorized"], 0)
		commit.assert_called_once()

	@patch("patient_notification_hub.patient_notification_hub.doctype.patient_notification.patient_notification.enqueue_notification")
	@patch("patient_notification_hub.patient_notification_hub.doctype.patient_notification.patient_notification.frappe.db.commit")
	@patch("patient_notification_hub.patient_notification_hub.doctype.patient_notification.patient_notification._get_notification")
	def test_manual_retry_preserves_attempt_history_and_records_audit(self, get_notification, commit, enqueue):
		notification = notification_doc(attempt_count=3)
		get_notification.return_value = notification

		with (
			patch(
				"patient_notification_hub.patient_notification_hub.doctype.patient_notification.patient_notification.frappe.session",
				SimpleNamespace(user="Administrator"),
			),
			patch("patient_notification_hub.patient_notification_hub.doctype.patient_notification.patient_notification.now_datetime", return_value=datetime(2026, 8, 19)),
		):
			result = retry_notification(notification.name, reason="Provider confirmed no delivery")

		self.assertEqual(result["status"], "Queued")
		self.assertEqual(notification.attempt_count, 3)
		self.assertEqual(notification.manual_retry_authorized, 1)
		self.assertEqual(notification.manual_retry_count, 1)
		self.assertEqual(notification.last_manual_action_by, "Administrator")
		self.assertEqual(notification.last_manual_action_reason, "Provider confirmed no delivery")
		enqueue.assert_called_once_with(notification.name, enqueue_after_commit=False)

	def test_transport_preserves_typed_outcomes(self):
		notification = notification_doc()
		settings = SimpleNamespace(enable_default_interakt_fallback=0)

		with patch(
			"wa_chat_hub.automation.send_patient_template",
			side_effect=PatientTemplateNotSentError("busy", retryable=True),
		):
			with self.assertRaises(DeliveryNotSentError) as context:
				send_whatsapp_template(notification, settings)
		self.assertTrue(context.exception.retryable)

		with patch(
			"wa_chat_hub.automation.send_patient_template",
			side_effect=PatientTemplateOutcomeUnknownError("timeout"),
		):
			with self.assertRaisesRegex(Exception, "timeout"):
				send_whatsapp_template(notification, settings)


