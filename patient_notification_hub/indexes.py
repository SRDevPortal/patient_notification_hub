from __future__ import annotations

import frappe


INDEXES = (
	(
		"Patient Notification Rule",
		"idx_pnh_rule_event_lookup",
		("enabled", "reference_doctype", "document_event", "creation"),
	),
	(
		"Patient Notification",
		"idx_patient_notification_status_retry",
		("status", "next_retry_on"),
	),
	(
		"Patient Notification",
		"idx_patient_notification_status_queued",
		("status", "queued_on"),
	),
	(
		"Patient Notification",
		"idx_patient_notification_status_sending",
		("status", "sending_started_on"),
	),
	(
		"Patient Notification",
		"idx_patient_notification_reference",
		("reference_doctype", "reference_name"),
	),
	(
		"Patient Notification",
		"idx_patient_notification_rule_status",
		("rule", "status"),
	),
	(
		"Patient Notification Variable",
		"idx_pnh_variable_parent_parenttype",
		("parent", "parenttype"),
	),
	(
		"Patient Notification Event",
		"idx_pnh_event_status_retry",
		("status", "next_retry_on"),
	),
	(
		"Patient Notification Event",
		"idx_pnh_event_status_captured",
		("status", "captured_on"),
	),
	(
		"Patient Notification Event",
		"idx_pnh_event_status_processing",
		("status", "last_attempt_on"),
	),
	(
		"Patient Notification Event",
		"idx_pnh_event_reference",
		("reference_doctype", "reference_name"),
	),
)


def ensure_indexes() -> None:
	for doctype, index_name, fields in INDEXES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if not all(frappe.db.has_column(doctype, fieldname) for fieldname in fields):
			continue
		if has_equivalent_index(doctype, fields):
			continue
		add_online_index(doctype, index_name, fields)


def has_equivalent_index(doctype: str, fields: tuple[str, ...]) -> bool:
	rows = frappe.db.sql(
		"""
		select index_name, group_concat(column_name order by seq_in_index) as indexed_fields
		from information_schema.statistics
		where table_schema = database()
		  and table_name = %(table_name)s
		group by index_name
		""",
		{"table_name": f"tab{doctype}"},
		as_dict=True,
	)
	return any(row.indexed_fields == ",".join(fields) for row in rows)


def add_online_index(doctype: str, index_name: str, fields: tuple[str, ...]) -> None:
	table = f"tab{doctype}"
	columns = ", ".join(f"`{fieldname}`" for fieldname in fields)
	frappe.db.sql_ddl(
		f"""
		alter table `{table}`
		add index `{index_name}` ({columns}),
		algorithm=inplace,
		lock=none
		"""
	)
