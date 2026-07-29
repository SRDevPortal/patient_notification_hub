from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from patient_notification_hub.indexes import INDEXES, add_online_index
from patient_notification_hub.rules import RULE_CACHE_TTL_SECONDS, get_enabled_rules


class TestPatientNotificationPerformanceCompliance(FrappeTestCase):
	def test_required_composite_indexes_are_declared(self):
		declared = {(doctype, fields) for doctype, index_name, fields in INDEXES}
		self.assertIn(
			(
				"Patient Notification Rule",
				("enabled", "reference_doctype", "document_event", "creation"),
			),
			declared,
		)
		self.assertIn(("Patient Notification", ("status", "queued_on")), declared)
		self.assertIn(("Patient Notification", ("status", "sending_started_on")), declared)
		self.assertIn(
			("Patient Notification Variable", ("parent", "parenttype")),
			declared,
		)

	@patch("patient_notification_hub.indexes.frappe.db.sql_ddl")
	def test_online_index_commits_before_nonblocking_ddl(self, sql_ddl):
		add_online_index(
			"Patient Notification",
			"idx_test_status_queued",
			("status", "queued_on"),
		)

		statement = sql_ddl.call_args.args[0].lower()
		self.assertIn("algorithm=inplace", statement)
		self.assertIn("lock=none", statement)

	@patch("patient_notification_hub.rules.frappe.get_cached_doc")
	@patch("patient_notification_hub.rules.frappe.get_all")
	@patch("patient_notification_hub.rules.frappe.cache")
	def test_rule_cache_has_ttl_and_bounded_query(self, cache, get_all, get_cached_doc):
		redis = Mock()
		redis.get_value.return_value = None
		cache.return_value = redis
		get_all.return_value = [frappe._dict(name="RULE-1")]
		get_cached_doc.return_value = frappe._dict(name="RULE-1")

		get_enabled_rules("Sales Invoice", "On Submit")

		self.assertEqual(get_all.call_args.kwargs["fields"], ["name"])
		self.assertEqual(get_all.call_args.kwargs["limit_start"], 0)
		self.assertGreater(get_all.call_args.kwargs["limit_page_length"], 0)
		self.assertEqual(
			redis.set_value.call_args.kwargs["expires_in_sec"],
			RULE_CACHE_TTL_SECONDS,
		)
