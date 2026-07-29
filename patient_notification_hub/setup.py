from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

from patient_notification_hub.indexes import ensure_indexes


INITIAL_RULES = [
	{
		"rule_key": "sales_invoice_generated",
		"title": "Sales Invoice Generated",
		"event_type": "sales_invoice_generated",
		"source_application": "ERPNext",
		"reference_doctype": "Sales Invoice",
		"document_event": "On Submit",
		"trigger_mode": "Document Event",
		"recipient_mode": "Document Field",
		"patient_field": "patient",
		"template_name": "sales_invoice_generated",
		"language_code": "en",
		"preview_template": (
			"Hello {{ values[0] }},\n\n"
			"Your sales invoice {{ values[1] }} dated {{ values[2] }} has been generated successfully.\n\n"
			"Invoice Amount: {{ values[3] }}\n\n"
			"Thank you for choosing us."
		),
		"deduplication_scope": "Once Per Document",
		"event_key_template": "sales_invoice:{{ doc.name }}:sales_invoice_generated",
		"variables": [
			{"position": 1, "source_type": "Registered Resolver", "source": "patient_name"},
			{"position": 2, "source_type": "Document Field", "source": "name"},
			{"position": 3, "source_type": "Document Field", "source": "posting_date", "format_type": "Date"},
			{"position": 4, "source_type": "Registered Resolver", "source": "invoice_amount"},
		],
	},
	{
		"rule_key": "patient_encounter_submitted",
		"title": "Patient Encounter Submitted",
		"event_type": "patient_encounter_submitted",
		"source_application": "Healthcare",
		"reference_doctype": "Patient Encounter",
		"document_event": "On Submit",
		"trigger_mode": "Document Event",
		"recipient_mode": "Document Field",
		"patient_field": "patient",
		"template_name": "patient_encounter_submitted",
		"language_code": "en",
		"preview_template": (
			"Hello {{ values[0] }},\n\n"
			"Your patient encounter {{ values[1] }} dated {{ values[2] }} has been completed.\n\n"
			"Practitioner: {{ values[3] }}\n"
			"Department: {{ values[4] }}"
		),
		"deduplication_scope": "Once Per Document",
		"variables": [
			{"position": 1, "source_type": "Registered Resolver", "source": "patient_name"},
			{"position": 2, "source_type": "Document Field", "source": "name"},
			{"position": 3, "source_type": "Document Field", "source": "encounter_date", "format_type": "Date"},
			{"position": 4, "source_type": "Document Field", "source": "practitioner_name"},
			{"position": 5, "source_type": "Document Field", "source": "medical_department"},
		],
	},
	{
		"rule_key": "order_picked_up",
		"title": "Order Picked Up",
		"event_type": "order_picked_up",
		"source_application": "Shipment Tracking",
		"reference_doctype": "Shipment Tracking Shipment",
		"document_event": "On Update",
		"trigger_mode": "Field Changed To Value",
		"watched_field": "normalized_status",
		"target_value": "Picked Up",
		"recipient_mode": "Document Field",
		"patient_field": "patient",
		"template_name": "order_picked_up",
		"language_code": "en",
		"preview_template": (
			"Hello {{ values[0] }},\n\n"
			"Your order {{ values[1] }} has been picked up and is on its way.\n\n"
			"AWB Number: {{ values[2] }}\n"
			"Delivery Partner: {{ values[3] }}\n"
			"Estimated Delivery: {{ values[4] }}\n\n"
			"We will notify you when it is out for delivery."
		),
		"deduplication_scope": "Once Per Target Value",
		"event_key_template": "shipment:{{ doc.name }}:order_picked_up",
		"variables": [
			{"position": 1, "source_type": "Registered Resolver", "source": "patient_name"},
			{"position": 2, "source_type": "Document Field", "source": "shipkia_order_id"},
			{"position": 3, "source_type": "Document Field", "source": "shipkia_awb_number"},
			{"position": 4, "source_type": "Document Field", "source": "delivery_partner"},
			{
				"position": 5,
				"source_type": "Document Field",
				"source": "shipkia_estimated_delivery",
				"format_type": "Datetime",
			},
		],
	},
	{
		"rule_key": "out_for_delivery",
		"title": "Out for Delivery",
		"event_type": "out_for_delivery",
		"source_application": "Shipment Tracking",
		"reference_doctype": "Shipment Tracking Shipment",
		"document_event": "On Update",
		"trigger_mode": "Field Changed To Value",
		"watched_field": "normalized_status",
		"target_value": "Out for Delivery",
		"recipient_mode": "Document Field",
		"patient_field": "patient",
		"template_name": "out_for_delivery",
		"language_code": "en",
		"preview_template": (
			"Hello {{ values[0] }},\n\n"
			"Your order {{ values[1] }} is out for delivery.\n\n"
			"AWB Number: {{ values[2] }}\n"
			"Delivery Partner: {{ values[3] }}\n\n"
			"Please keep your phone available for the delivery agent."
		),
		"deduplication_scope": "Once Per Target Value",
		"event_key_template": "shipment:{{ doc.name }}:out_for_delivery",
		"variables": [
			{"position": 1, "source_type": "Registered Resolver", "source": "patient_name"},
			{"position": 2, "source_type": "Document Field", "source": "shipkia_order_id"},
			{"position": 3, "source_type": "Document Field", "source": "shipkia_awb_number"},
			{"position": 4, "source_type": "Document Field", "source": "delivery_partner"},
		],
	},
]

APP_NAME = "patient_notification_hub"
APP_MODULE = "patient_notification_hub"


def validate_dependencies():
	# install_app clears the shared module-map cache after frappe.init(), but the
	# process-local map can still represent the apps that existed before this app
	# was added to the bench. Rebuild it before sync_for() reads the map.
	frappe.setup_module_map(include_all_apps=True)
	if APP_MODULE not in (frappe.local.app_modules.get(APP_NAME) or []):
		frappe.throw(
			"Patient Notification Hub module metadata could not be discovered. "
			"Verify the deployed app contains modules.txt and its DocType package, then retry installation."
		)
	if "wa_chat_hub" not in frappe.get_installed_apps():
		frappe.throw("Patient Notification Hub requires the wa_chat_hub app.")


def after_install():
	ensure_settings()
	ensure_initial_rules()
	migrate_legacy_configuration()
	migrate_legacy_notifications()
	ensure_indexes()


def after_migrate():
	ensure_settings()
	ensure_initial_rules()
	migrate_legacy_configuration()
	migrate_legacy_notifications()


def ensure_settings():
	settings = frappe.get_single("Patient Notification Settings")
	changed = False
	defaults = {
		"enabled": 0,
		"dry_run": 1,
		"maximum_attempts": 3,
		"base_retry_delay_minutes": 5,
		"stale_sending_timeout_minutes": 15,
		"worker_batch_size": 50,
		"enable_background_recovery": 0,
		"enable_failed_retry": 1,
		"enable_queued_recovery": 1,
		"enable_stale_sending_recovery": 1,
		"queued_recovery_timeout_minutes": 10,
	}
	for fieldname, value in defaults.items():
		if settings.get(fieldname) in (None, ""):
			settings.set(fieldname, value)
			changed = True
	if not cint(settings.recovery_settings_initialized):
		settings.enable_background_recovery = 0
		settings.enable_failed_retry = 1
		settings.enable_queued_recovery = 1
		settings.enable_stale_sending_recovery = 1
		settings.queued_recovery_timeout_minutes = 10
		settings.recovery_settings_initialized = 1
		changed = True
	if changed or settings.is_new():
		settings.save(ignore_permissions=True)


def ensure_initial_rules():
	rule_keys = [definition["rule_key"] for definition in INITIAL_RULES]
	existing_rule_keys = {
		row.rule_key
		for row in frappe.get_all(
			"Patient Notification Rule",
			filters={"rule_key": ["in", rule_keys]},
			fields=["rule_key"],
			limit_start=0,
			limit_page_length=len(rule_keys),
		)
	}
	missing_rules = [
		definition for definition in INITIAL_RULES if definition["rule_key"] not in existing_rule_keys
	]
	if not missing_rules:
		return

	timestamp = now_datetime()
	rule_fields = [
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"docstatus",
		"idx",
		"rule_key",
		"title",
		"enabled",
		"event_type",
		"source_application",
		"reference_doctype",
		"document_event",
		"trigger_mode",
		"watched_field",
		"previous_value",
		"target_value",
		"conditions_json",
		"recipient_mode",
		"patient_field",
		"recipient_resolver",
		"channel",
		"template_name",
		"language_code",
		"template_category",
		"preview_template",
		"deduplication_scope",
		"event_key_template",
		"priority",
	]
	rule_values = []
	variable_fields = [
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"docstatus",
		"idx",
		"parent",
		"parentfield",
		"parenttype",
		"position",
		"source_type",
		"source",
		"default_value",
		"format_type",
		"required",
	]
	variable_values = []
	for definition in missing_rules:
		rule_name = definition["rule_key"]
		rule_values.append(
			(
				rule_name,
				"Administrator",
				timestamp,
				timestamp,
				"Administrator",
				0,
				0,
				rule_name,
				definition["title"],
				0,
				definition["event_type"],
				definition["source_application"],
				definition["reference_doctype"],
				definition["document_event"],
				definition["trigger_mode"],
				definition.get("watched_field"),
				definition.get("previous_value"),
				definition.get("target_value"),
				definition.get("conditions_json"),
				definition["recipient_mode"],
				definition.get("patient_field"),
				definition.get("recipient_resolver"),
				"WhatsApp",
				definition["template_name"],
				definition["language_code"],
				"UTILITY",
				definition["preview_template"],
				definition["deduplication_scope"],
				definition.get("event_key_template"),
				"Short",
			)
		)
		for index, variable in enumerate(definition.get("variables", []), start=1):
			variable_values.append(
				(
					frappe.generate_hash(length=10),
					"Administrator",
					timestamp,
					timestamp,
					"Administrator",
					0,
					index,
					rule_name,
					"variables",
					"Patient Notification Rule",
					variable["position"],
					variable["source_type"],
					variable["source"],
					variable.get("default_value"),
					variable.get("format_type"),
					variable.get("required", 0),
				)
			)

	frappe.db.bulk_insert(
		"Patient Notification Rule",
		rule_fields,
		rule_values,
		ignore_duplicates=True,
		chunk_size=500,
	)
	if variable_values:
		frappe.db.bulk_insert(
			"Patient Notification Variable",
			variable_fields,
			variable_values,
			ignore_duplicates=True,
			chunk_size=500,
		)


def migrate_legacy_configuration():
	if not frappe.db.exists("DocType", "Shipment Tracking Settings"):
		return

	settings = frappe.get_single("Patient Notification Settings")
	if cint(settings.legacy_migration_completed):
		return

	legacy = frappe.get_single("Shipment Tracking Settings")
	settings.dry_run = 1
	settings.enabled = 0
	settings.pilot_patient = legacy.get("whatsapp_test_patient")
	settings.enable_default_interakt_fallback = cint(legacy.get("enable_default_interakt_fallback"))
	settings.default_interakt_account = legacy.get("default_interakt_account")
	settings.maximum_attempts = cint(legacy.get("whatsapp_max_retries")) or 3
	settings.base_retry_delay_minutes = cint(legacy.get("whatsapp_retry_delay_minutes")) or 5
	settings.legacy_migration_completed = 1
	settings.save(ignore_permissions=True)

	rule_values = [
		(
			"sales_invoice_generated",
			legacy.get("sales_invoice_generated_template") or "sales_invoice_generated",
			legacy.get("sales_invoice_generated_language") or "en",
		),
		(
			"order_picked_up",
			legacy.get("order_picked_up_template") or "order_picked_up",
			legacy.get("order_picked_up_language") or "en",
		),
		(
			"out_for_delivery",
			legacy.get("out_for_delivery_template") or "out_for_delivery",
			legacy.get("out_for_delivery_language") or "en",
		),
	]
	template_cases = " ".join("when %s then %s" for _ in rule_values)
	language_cases = " ".join("when %s then %s" for _ in rule_values)
	rule_placeholders = ", ".join(["%s"] * len(rule_values))
	frappe.db.sql(
		f"""
		update `tabPatient Notification Rule`
		set template_name = case rule_key {template_cases} else template_name end,
			language_code = case rule_key {language_cases} else language_code end,
			enabled = 0
		where rule_key in ({rule_placeholders})
		""",
		[
			*(value for rule_name, template_name, _ in rule_values for value in (rule_name, template_name)),
			*(value for rule_name, _, language_code in rule_values for value in (rule_name, language_code)),
			*(rule_name for rule_name, _, _ in rule_values),
		],
	)


def migrate_legacy_notifications():
	settings = frappe.get_single("Patient Notification Settings")
	if cint(settings.legacy_notifications_migration_completed):
		return
	if not frappe.db.exists("DocType", "Shipment WhatsApp Notification"):
		settings.legacy_notifications_migration_completed = 1
		settings.save(ignore_permissions=True)
		return

	page_length = 500
	rule_names = {
		row.name
		for row in frappe.get_all(
			"Patient Notification Rule",
			fields=["name"],
			limit_start=0,
			limit_page_length=100,
		)
	}
	start = 0
	while True:
		rows = frappe.get_all(
			"Shipment WhatsApp Notification",
			fields=[
				"name",
				"owner",
				"creation",
				"modified",
				"modified_by",
				"event_key",
				"event_type",
				"status",
				"sales_invoice",
				"shipment",
				"patient",
				"shipkia_order_id",
				"template_name",
				"language_code",
				"body_values_json",
				"body_preview",
				"channel_account",
				"routing_source",
				"conversation",
				"chat_message",
				"provider_message_id",
				"attempt_count",
				"next_retry_on",
				"queued_on",
				"sent_on",
				"skip_reason",
				"last_error",
			],
			limit_start=start,
			limit_page_length=page_length,
			order_by="creation asc, name asc",
		)
		if not rows:
			break

		event_keys = [row.event_key for row in rows if row.event_key]
		existing_event_keys = (
			{
				row.event_key
				for row in frappe.get_all(
					"Patient Notification",
					filters={"event_key": ["in", event_keys]},
					fields=["event_key"],
					limit_start=0,
					limit_page_length=page_length,
				)
			}
			if event_keys
			else set()
		)
		fields = [
			"name",
			"owner",
			"creation",
			"modified",
			"modified_by",
			"docstatus",
			"idx",
			"event_key",
			"rule",
			"rule_key",
			"event_type",
			"status",
			"patient",
			"reference_doctype",
			"reference_name",
			"template_name",
			"language_code",
			"body_values_json",
			"body_preview",
			"context_json",
			"channel_account",
			"routing_source",
			"conversation",
			"chat_message",
			"provider_message_id",
			"attempt_count",
			"next_retry_on",
			"queued_on",
			"sent_on",
			"skip_reason",
			"last_error",
		]
		values = []
		for row in rows:
			if not row.event_key or row.event_key in existing_event_keys:
				continue
			reference_doctype = "Sales Invoice" if row.sales_invoice else "Shipment Tracking Shipment"
			reference_name = row.sales_invoice or row.shipment
			timestamp = row.creation or now_datetime()
			values.append(
				(
					frappe.generate_hash(length=10),
					row.owner or "Administrator",
					timestamp,
					row.modified or timestamp,
					row.modified_by or row.owner or "Administrator",
					0,
					0,
					row.event_key,
					row.event_type if row.event_type in rule_names else None,
					row.event_type,
					row.event_type,
					row.status,
					row.patient,
					reference_doctype if reference_name else None,
					reference_name,
					row.template_name,
					row.language_code,
					row.body_values_json,
					row.body_preview,
					frappe.as_json({"shipkia_order_id": row.shipkia_order_id}),
					row.channel_account,
					row.routing_source,
					row.conversation,
					row.chat_message,
					row.provider_message_id,
					row.attempt_count,
					row.next_retry_on,
					row.queued_on,
					row.sent_on,
					row.skip_reason,
					row.last_error,
				)
			)
		if values:
			frappe.db.bulk_insert(
				"Patient Notification",
				fields,
				values,
				ignore_duplicates=True,
				chunk_size=page_length,
			)
		start += page_length
		frappe.db.commit()

	settings.legacy_notifications_migration_completed = 1
	settings.save(ignore_permissions=True)
