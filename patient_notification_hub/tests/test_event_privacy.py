from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from patient_notification_hub.event_inbox import _snapshot, purge_expired_event_snapshots


class TestEventSnapshotPrivacy(FrappeTestCase):
	def test_snapshot_keeps_only_rule_referenced_fields(self):
		rule = frappe._dict(
			watched_field="status",
			patient_field="patient",
			conditions_json='[["company", "=", "SRIAAS"]]',
			event_key_template="invoice:{{ doc.name }}",
			preview_template="{{ doc.posting_date }}",
			variables=[
				frappe._dict(source_type="Document Field", source="grand_total", format_type="Currency"),
			],
		)
		doc = frappe._dict(
			doctype="Sales Invoice",
			name="SINV-1",
			modified="2026-08-19",
			status="Submitted",
			patient="PAT-1",
			company="SRIAAS",
			posting_date="2026-08-19",
			grand_total=100,
			currency="INR",
			diagnosis="must not be retained",
		)

		snapshot = _snapshot(rule, doc)

		self.assertEqual(snapshot["grand_total"], 100)
		self.assertEqual(snapshot["currency"], "INR")
		self.assertNotIn("diagnosis", snapshot)

	@patch("patient_notification_hub.event_inbox.frappe.db.commit")
	@patch("patient_notification_hub.event_inbox.frappe.db.set_value")
	@patch("patient_notification_hub.event_inbox.frappe.get_all")
	@patch("patient_notification_hub.event_inbox.frappe.db.exists", return_value=True)
	def test_retention_discards_expired_unreplayed_snapshot(self, exists, get_all, set_value, commit):
		get_all.side_effect = [[], [frappe._dict(name="EVENT-OLD")]]
		settings = SimpleNamespace(event_snapshot_retention_days=7, worker_batch_size=50)

		with patch("patient_notification_hub.event_inbox.now_datetime", return_value=datetime(2026, 8, 19)):
			count = purge_expired_event_snapshots(settings)

		self.assertEqual(count, 1)
		updates = set_value.call_args.args[2]
		self.assertEqual(updates["status"], "Discarded")
		self.assertIsNone(updates["document_json"])
		self.assertIsNone(updates["previous_document_json"])
		commit.assert_called_once()

