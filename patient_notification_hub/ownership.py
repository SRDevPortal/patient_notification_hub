from __future__ import annotations

import frappe
from frappe.utils import cstr


SHIPMENT_RULE_KEYS = {"sales_invoice_generated", "order_picked_up", "out_for_delivery"}
HUB_ENGINE = "Patient Notification Hub"
LEGACY_ENGINE = "Legacy Shipment Tracking"


def hub_owns_rule(rule_key: str) -> bool:
	"""Return whether the hub owns a rule that overlaps Shipment Tracking."""
	if cstr(rule_key).strip() not in SHIPMENT_RULE_KEYS:
		return True
	if not frappe.db.exists("DocType", "Shipment Tracking Settings"):
		return True
	engine = cstr(
		frappe.db.get_single_value("Shipment Tracking Settings", "whatsapp_notification_engine")
	).strip()
	# Missing values belong to pre-cutover installations and must remain legacy-safe.
	return engine == HUB_ENGINE
