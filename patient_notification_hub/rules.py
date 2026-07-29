from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import cstr


RULE_CACHE_PREFIX = "patient_notification_hub:rules"
RULE_CACHE_TTL_SECONDS = 3600
RULE_QUERY_LIMIT = 100
SUPPORTED_OPERATORS = {"=", "==", "!=", ">", ">=", "<", "<=", "in", "not in", "is", "is not"}


def rule_cache_key(reference_doctype: str, document_event: str) -> str:
	return f"{RULE_CACHE_PREFIX}:{reference_doctype}:{document_event}"


def clear_rule_cache() -> None:
	frappe.cache().delete_keys(f"{RULE_CACHE_PREFIX}:")


def get_enabled_rules(reference_doctype: str, document_event: str):
	key = rule_cache_key(reference_doctype, document_event)
	names = frappe.cache().get_value(key)
	if names is None:
		rows = frappe.get_all(
			"Patient Notification Rule",
			filters={
				"enabled": 1,
				"reference_doctype": reference_doctype,
				"document_event": document_event,
			},
			fields=["name"],
			order_by="creation asc",
			limit_start=0,
			limit_page_length=RULE_QUERY_LIMIT,
		)
		names = [row.name for row in rows]
		frappe.cache().set_value(key, names, expires_in_sec=RULE_CACHE_TTL_SECONDS)
	return [frappe.get_cached_doc("Patient Notification Rule", name) for name in names]


def matches_trigger(rule, doc, previous_doc) -> bool:
	if rule.trigger_mode == "Document Event":
		return True
	if not previous_doc:
		return False

	old_value = cstr(previous_doc.get(rule.watched_field))
	new_value = cstr(doc.get(rule.watched_field))
	if old_value == new_value:
		return False
	if rule.previous_value and old_value != cstr(rule.previous_value):
		return False
	if rule.trigger_mode == "Field Changed To Value":
		return new_value == cstr(rule.target_value)
	return True


def matches_conditions(rule, doc) -> bool:
	if not rule.conditions_json:
		return True
	conditions = json.loads(rule.conditions_json)
	if isinstance(conditions, dict):
		return all(_compare(doc.get(fieldname), "=", expected) for fieldname, expected in conditions.items())
	return all(_matches_condition(doc, condition) for condition in conditions)


def _matches_condition(doc, condition) -> bool:
	if not isinstance(condition, list) or len(condition) != 3:
		return False
	fieldname, operator, expected = condition
	if operator not in SUPPORTED_OPERATORS:
		return False
	return _compare(doc.get(fieldname), operator, expected)


def _compare(actual: Any, operator: str, expected: Any) -> bool:
	if operator in {"=", "=="}:
		return actual == expected
	if operator == "!=":
		return actual != expected
	if operator == "in":
		return actual in (expected or [])
	if operator == "not in":
		return actual not in (expected or [])
	if operator == "is":
		return (expected == "set" and actual not in (None, "")) or (
			expected == "not set" and actual in (None, "")
		)
	if operator == "is not":
		return not _compare(actual, "is", expected)
	try:
		if operator == ">":
			return actual > expected
		if operator == ">=":
			return actual >= expected
		if operator == "<":
			return actual < expected
		if operator == "<=":
			return actual <= expected
	except TypeError:
		return False
	return False
