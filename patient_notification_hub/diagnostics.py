"""Read-only operational snapshot for bench execute; no provider or send calls."""
from __future__ import annotations

import frappe


def notification_load_snapshot() -> dict:
	"""Report site backlog and query plans, plus explicitly server-wide counters."""
	indexes = frappe.db.sql(
		"""SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX, SUB_PART
		FROM information_schema.STATISTICS
		WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tabChat Message'
		ORDER BY INDEX_NAME, SEQ_IN_INDEX""", as_dict=True,
	)
	plans = {}
	for field in ("dedupe_key", "provider_event_id"):
		plans[field] = frappe.db.sql(
			f"""EXPLAIN SELECT name, conversation, provider_message_id, creation
			FROM `tabChat Message` WHERE `{field}`=%s AND direction='Outbound'
			ORDER BY modified DESC LIMIT 1""",
			("__notification_health_plan_only__",), as_dict=True,
		)
	backlog = frappe.db.sql(
		"""SELECT status, COUNT(*) AS count, MIN(queued_on) AS oldest_queued_on
		FROM `tabPatient Notification`
		WHERE status IN ('Queued', 'Sending', 'Failed', 'Outcome Unknown')
		GROUP BY status""", as_dict=True,
	)
	status = frappe.db.sql(
		"""SHOW GLOBAL STATUS WHERE Variable_name IN
		('Threads_connected','Threads_running','Max_used_connections',
		'Connection_errors_max_connections','Slow_queries','Uptime')""", as_dict=True,
	)
	limits = frappe.db.sql("SELECT @@max_connections AS max_connections", as_dict=True)[0]
	counters = {row["Variable_name"]: int(row["Value"]) for row in status}
	warnings = []
	if any(row.get("type") in ("ALL", "index") for row in plans["provider_event_id"]):
		warnings.append("Delivery event lookup uses a scan; check the notification event index.")
	if counters.get("Threads_connected", 0) >= 0.8 * limits["max_connections"]:
		warnings.append("Server connections are at or above 80% of the configured limit.")
	return {
		"site": frappe.local.site,
		"captured_at": frappe.utils.now(),
		"message_indexes": indexes,
		"lookup_plans": plans,
		"site_notification_backlog": backlog,
		"server_counters_since_startup": counters,
		"server_max_connections": limits["max_connections"],
		"warnings": warnings,
	}
