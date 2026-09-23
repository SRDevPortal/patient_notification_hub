from unittest import TestCase
from unittest.mock import MagicMock, patch

from patient_notification_hub import diagnostics


class TestNotificationDiagnostics(TestCase):
	def snapshot(self, access="ref", connections=10):
		db = MagicMock()
		db.sql.side_effect = [
			[], [{"type": "const"}], [{"type": access}],
			[{"status": "Queued", "count": 3}],
			[{"Variable_name": "Threads_connected", "Value": str(connections)},
			 {"Variable_name": "Slow_queries", "Value": "100"}],
			[{"max_connections": 80}],
		]
		with patch.object(diagnostics.frappe, "db", db):
			result = diagnostics.notification_load_snapshot()
		# Operational inspection must not send, enqueue, update, or execute the lookup.
		for call in db.sql.call_args_list:
			self.assertIn(call.args[0].lstrip().split()[0].upper(), {"SELECT", "SHOW", "EXPLAIN"})
		return result

	def test_healthy_plan_and_capacity_do_not_warn_about_historical_counters(self):
		result = self.snapshot()
		self.assertEqual(result["warnings"], [])
		self.assertEqual(result["server_counters_since_startup"]["Slow_queries"], 100)
		self.assertEqual(result["site_notification_backlog"][0]["count"], 3)

	def test_scan_and_connection_pressure_are_reported(self):
		result = self.snapshot(access="index", connections=64)
		self.assertEqual(len(result["warnings"]), 2)
		self.assertIn("scan", result["warnings"][0])
		self.assertIn("80%", result["warnings"][1])
