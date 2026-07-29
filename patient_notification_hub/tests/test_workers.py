from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from patient_notification_hub.workers import (
	process_queued_notifications,
	reconcile_notifications,
	recover_stale_notifications,
	send_notification,
)


def notification_doc():
	return SimpleNamespace(
		name="NOTIF-0001",
		status="Queued",
		rule="sales_invoice_generated",
		patient="PAT-0001",
		template_name="sales_invoice_generated",
		language_code="en",
		body_values_json="[]",
		body_preview="Invoice generated",
		event_key="invoice:SINV-0001:sales_invoice_generated",
		attempt_count=0,
		channel_account=None,
		routing_source=None,
		conversation=None,
		chat_message=None,
		provider_message_id=None,
		sent_on=None,
		sending_started_on=None,
		next_retry_on=None,
		last_error=None,
		skip_reason=None,
		save=Mock(),
	)


class TestPatientNotificationWorkers(FrappeTestCase):
	@patch("patient_notification_hub.workers.process_queued_notifications")
	@patch("patient_notification_hub.workers.process_retryable_notifications")
	@patch("patient_notification_hub.workers.recover_stale_notifications")
	@patch("patient_notification_hub.workers.frappe.get_cached_doc")
	def test_reconciler_respects_background_master_switch(
		self,
		get_cached_doc,
		recover_stale,
		process_retryable,
		process_queued,
	):
		get_cached_doc.return_value = SimpleNamespace(
			enabled=1,
			dry_run=0,
			enable_background_recovery=0,
		)

		result = reconcile_notifications()

		self.assertEqual(result, {"queued": 0, "failed": 0, "stale": 0})
		recover_stale.assert_not_called()
		process_retryable.assert_not_called()
		process_queued.assert_not_called()

	@patch("patient_notification_hub.workers.process_queued_notifications", return_value=2)
	@patch("patient_notification_hub.workers.process_retryable_notifications")
	@patch("patient_notification_hub.workers.recover_stale_notifications", return_value=1)
	@patch("patient_notification_hub.workers.frappe.get_cached_doc")
	def test_reconciler_respects_individual_feature_switches(
		self,
		get_cached_doc,
		recover_stale,
		process_retryable,
		process_queued,
	):
		settings = SimpleNamespace(
			enabled=1,
			dry_run=0,
			enable_background_recovery=1,
			enable_failed_retry=0,
			enable_queued_recovery=1,
			enable_stale_sending_recovery=1,
		)
		get_cached_doc.return_value = settings

		result = reconcile_notifications()

		self.assertEqual(result, {"queued": 2, "failed": 0, "stale": 1})
		recover_stale.assert_called_once_with(settings)
		process_retryable.assert_not_called()
		process_queued.assert_called_once_with(settings)

	@patch("patient_notification_hub.workers.enqueue_notification")
	@patch("patient_notification_hub.workers.frappe.get_all")
	def test_queued_recovery_selects_only_expired_records(self, get_all, enqueue):
		get_all.return_value = [frappe._dict(name="NOTIF-OLD")]
		settings = SimpleNamespace(
			enabled=1,
			dry_run=0,
			enable_background_recovery=1,
			enable_queued_recovery=1,
			queued_recovery_timeout_minutes=10,
			worker_batch_size=25,
		)

		count = process_queued_notifications(settings)

		self.assertEqual(count, 1)
		filters = get_all.call_args.kwargs["filters"]
		self.assertEqual(filters["status"], "Queued")
		self.assertEqual(filters["queued_on"][0], "<=")
		self.assertEqual(get_all.call_args.kwargs["limit_start"], 0)
		self.assertEqual(get_all.call_args.kwargs["limit_page_length"], 25)
		enqueue.assert_called_once_with("NOTIF-OLD", enqueue_after_commit=False)

	@patch("patient_notification_hub.workers.frappe.db.commit")
	@patch("patient_notification_hub.workers.frappe.db.set_value")
	@patch("patient_notification_hub.workers.frappe.get_all")
	def test_stale_recovery_marks_records_retryable(self, get_all, set_value, commit):
		get_all.return_value = [frappe._dict(name="NOTIF-STALE")]
		settings = SimpleNamespace(
			enabled=1,
			dry_run=0,
			enable_background_recovery=1,
			enable_stale_sending_recovery=1,
			stale_sending_timeout_minutes=15,
			worker_batch_size=50,
		)

		count = recover_stale_notifications(settings)

		self.assertEqual(count, 1)
		filters = set_value.call_args.args[1]
		updates = set_value.call_args.args[2]
		self.assertEqual(filters["name"], ["in", ["NOTIF-STALE"]])
		self.assertEqual(filters["status"], "Sending")
		self.assertEqual(updates["status"], "Failed")
		self.assertIsNone(updates["sending_started_on"])
		self.assertIsNotNone(updates["next_retry_on"])
		self.assertIn("stale", updates["last_error"])
		commit.assert_called_once()

	@patch("patient_notification_hub.workers.frappe.db.commit")
	@patch("patient_notification_hub.workers.send_whatsapp_template")
	@patch("patient_notification_hub.workers.claim_notification")
	@patch("patient_notification_hub.workers.frappe.get_cached_doc")
	@patch("patient_notification_hub.workers.frappe.get_doc")
	def test_successful_send_persists_transport_references(
		self,
		get_doc,
		get_cached_doc,
		claim_notification,
		send_whatsapp_template,
		commit,
	):
		notification = notification_doc()
		get_doc.return_value = notification
		claim_notification.side_effect = lambda current, maximum_attempts: (
			setattr(current, "status", "Sending")
			or setattr(current, "attempt_count", 1)
			or current
		)
		get_cached_doc.side_effect = [
			SimpleNamespace(
				enabled=1,
				dry_run=0,
				pilot_patient=None,
				maximum_attempts=3,
			),
			SimpleNamespace(enabled=1),
		]
		send_whatsapp_template.return_value = {
			"channel_account": "Interakt Account",
			"routing_source": "Department Map",
			"conversation": "CONV-0001",
			"message": "MSG-0001",
			"provider_message_id": "PROVIDER-0001",
		}

		result = send_notification(notification.name)

		self.assertTrue(result["success"])
		self.assertEqual(notification.status, "Sent")
		self.assertEqual(notification.chat_message, "MSG-0001")
		self.assertEqual(notification.provider_message_id, "PROVIDER-0001")
		self.assertEqual(notification.attempt_count, 1)
		notification.save.assert_called_once()
		commit.assert_called_once()

	@patch("patient_notification_hub.workers.frappe.db.commit")
	@patch("patient_notification_hub.workers.frappe.get_cached_doc")
	@patch("patient_notification_hub.workers.frappe.get_doc")
	def test_disabled_master_switch_skips_queued_record(self, get_doc, get_cached_doc, commit):
		notification = notification_doc()
		get_doc.return_value = notification
		get_cached_doc.side_effect = [
			SimpleNamespace(enabled=0, dry_run=0, pilot_patient=None),
			SimpleNamespace(enabled=1),
		]

		result = send_notification(notification.name)

		self.assertEqual(result["status"], "Skipped")
		self.assertEqual(notification.status, "Skipped")
		self.assertIn("disabled", notification.skip_reason)
		notification.save.assert_called_once()
		commit.assert_called_once()
