from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint, cstr


def send_whatsapp_template(notification, settings) -> dict[str, Any]:
	from wa_chat_hub.automation import send_patient_template

	return send_patient_template(
		patient=notification.patient,
		template_name=notification.template_name,
		language_code=notification.language_code,
		body_values=frappe.parse_json(notification.body_values_json or "[]"),
		body_preview=notification.body_preview,
		event_key=notification.event_key,
		fallback_channel_account=(
			cstr(settings.default_interakt_account).strip()
			if cint(settings.enable_default_interakt_fallback)
			else None
		),
	)
