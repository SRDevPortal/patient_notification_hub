from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from patient_notification_hub.event_inbox import (
	_remove_password_fields,
	capture_failed_event,
	process_retryable_events,
)


class TestPatientNotificationEventInbox(FrappeTestCase):
	@patch("patient_notification_hub.event_inbox.frappe.get_meta")
	def test_event_snapshots_remove_password_and_secret_fields(self, get_meta):
		get_meta.return_value = SimpleNamespace(
			fields=[SimpleNamespace(fieldname="credential", fieldtype="Password")]
		)

		snapshot = _remove_password_fields(
			{
				"doctype": "Test Source",
				"name": "SOURCE-1",
				"credential": "encrypted",
				"api_secret": "secret",
			}
		)

		self.assertEqual(snapshot, {"doctype": "Test Source", "name": "SOURCE-1"})

	@patch("patient_notification_hub.event_inbox.enqueue_event")
	@patch("patient_notification_hub.event_inbox.frappe.get_doc")
	@patch("patient_notification_hub.event_inbox.frappe.db.release_savepoint")
	@patch("patient_notification_hub.event_inbox.frappe.db.savepoint")
	@patch("patient_notification_hub.event_inbox.frappe.db.get_value", return_value=None)
	@patch("patient_notification_hub.event_inbox.frappe.db.exists", return_value=True)
	def test_failure_capture_creates_replayable_event(
		self,
		exists,
		get_value,
		savepoint,
		release_savepoint,
		get_doc,
		enqueue_event,
	):
		event = SimpleNamespace(name="EVENT-1", insert=Mock())
		get_doc.return_value = event
		rule = frappe._dict(name="RULE-1", rule_key="rule_1", watched_field="status")
		doc = frappe._dict(doctype="Sales Invoice", name="SINV-1", modified="2026-08-18", status="Open")
		previous = frappe._dict(status="Draft")

		with patch("patient_notification_hub.event_inbox.now_datetime", return_value=datetime(2026, 8, 18)):
			name = capture_failed_event(rule, doc, previous, "On Update", ValueError("bad template"))

		self.assertEqual(name, "EVENT-1")
		payload = get_doc.call_args.args[0]
		self.assertEqual(payload["status"], "Captured")
		self.assertIn("bad template", payload["last_error"])
		self.assertLessEqual(len(payload["event_key"]), 140)
		event.insert.assert_called_once_with(ignore_permissions=True)
		enqueue_event.assert_called_once_with("EVENT-1", enqueue_after_commit=True)

	@patch("patient_notification_hub.event_inbox.enqueue_event")
	@patch("patient_notification_hub.event_inbox.frappe.get_all")
	def test_recovery_includes_stale_captured_and_due_failed_events(self, get_all, enqueue_event):
		get_all.side_effect = [
			[],
			[frappe._dict(name="EVENT-CAPTURED")],
			[frappe._dict(name="EVENT-FAILED")],
		]
		settings = SimpleNamespace(
			enabled=1,
			enable_background_recovery=1,
			maximum_attempts=3,
			worker_batch_size=10,
			queued_recovery_timeout_minutes=10,
		)

		with patch("patient_notification_hub.event_inbox.now_datetime", return_value=datetime(2026, 8, 18)):
			count = process_retryable_events(settings)

		self.assertEqual(count, 2)
		enqueue_event.assert_any_call("EVENT-CAPTURED", enqueue_after_commit=False)
		enqueue_event.assert_any_call("EVENT-FAILED", enqueue_after_commit=False)
