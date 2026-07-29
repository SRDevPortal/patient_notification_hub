from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from patient_notification_hub.patient_notification_hub.doctype.patient_notification_settings.patient_notification_settings import (
	PatientNotificationSettings,
	get_scheduler_status,
)
from patient_notification_hub.rendering import render_event_key
from patient_notification_hub.rules import matches_conditions, matches_trigger


class TestPatientNotificationRules(FrappeTestCase):
	@patch(
		"patient_notification_hub.patient_notification_hub.doctype.patient_notification_settings.patient_notification_settings.is_scheduler_inactive",
		return_value=True,
	)
	@patch(
		"patient_notification_hub.patient_notification_hub.doctype.patient_notification_settings.patient_notification_settings.is_scheduler_disabled",
		return_value=True,
	)
	def test_scheduler_status_reports_disabled_state(self, scheduler_disabled, scheduler_inactive):
		status = get_scheduler_status()

		self.assertFalse(status["enabled"])
		self.assertFalse(status["active"])
		self.assertIn("disabled", status["message"])

	def test_background_recovery_requires_a_subfeature(self):
		settings = PatientNotificationSettings(
			{
				"doctype": "Patient Notification Settings",
				"maximum_attempts": 3,
				"base_retry_delay_minutes": 5,
				"stale_sending_timeout_minutes": 15,
				"worker_batch_size": 50,
				"queued_recovery_timeout_minutes": 10,
				"enable_background_recovery": 1,
				"enable_failed_retry": 0,
				"enable_queued_recovery": 0,
				"enable_stale_sending_recovery": 0,
			}
		)

		with self.assertRaises(frappe.ValidationError):
			settings.validate()

	def test_document_event_always_matches(self):
		rule = frappe._dict(trigger_mode="Document Event")
		self.assertTrue(matches_trigger(rule, frappe._dict(), None))

	def test_changed_to_value_requires_transition(self):
		rule = frappe._dict(
			trigger_mode="Field Changed To Value",
			watched_field="status",
			previous_value="",
			target_value="Picked Up",
		)
		self.assertTrue(
			matches_trigger(
				rule,
				frappe._dict(status="Picked Up"),
				frappe._dict(status="In Transit"),
			)
		)
		self.assertFalse(
			matches_trigger(
				rule,
				frappe._dict(status="Picked Up"),
				frappe._dict(status="Picked Up"),
			)
		)

	def test_previous_value_restricts_transition(self):
		rule = frappe._dict(
			trigger_mode="Field Changed To Value",
			watched_field="status",
			previous_value="In Transit",
			target_value="Out for Delivery",
		)
		self.assertFalse(
			matches_trigger(
				rule,
				frappe._dict(status="Out for Delivery"),
				frappe._dict(status="Pending Pickup"),
			)
		)

	def test_conditions_support_object_and_filter_list(self):
		doc = frappe._dict(docstatus=1, status="Open")
		self.assertTrue(matches_conditions(frappe._dict(conditions_json='{"docstatus": 1}'), doc))
		self.assertTrue(
			matches_conditions(
				frappe._dict(conditions_json='[["status", "in", ["Open", "Closed"]]]'),
				doc,
			)
		)
		self.assertFalse(
			matches_conditions(frappe._dict(conditions_json='[["status", "=", "Closed"]]'), doc)
		)

	def test_legacy_event_key_template_is_preserved(self):
		rule = frappe._dict(
			event_key_template="shipment:{{ doc.name }}:order_picked_up",
			rule_key="order_picked_up",
			deduplication_scope="Once Per Target Value",
			target_value="Picked Up",
		)
		doc = frappe._dict(
			doctype="Shipment Tracking Shipment",
			name="SHIP-0001",
			modified="2026-07-29 10:00:00",
		)
		self.assertEqual(
			render_event_key(rule, doc, None),
			"shipment:SHIP-0001:order_picked_up",
		)
