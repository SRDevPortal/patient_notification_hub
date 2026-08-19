from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint, cstr


class DeliveryNotSentError(Exception):
	def __init__(self, message: str, *, retryable: bool = False):
		super().__init__(message)
		self.retryable = retryable


class DeliveryOutcomeUnknownError(Exception):
	pass


def send_whatsapp_template(notification, settings) -> dict[str, Any]:
	from wa_chat_hub.automation import send_patient_template
	from wa_chat_hub.delivery_outcomes import (
		PatientTemplateNotSentError,
		PatientTemplateOutcomeUnknownError,
	)

	try:
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
	except PatientTemplateNotSentError as exc:
		raise DeliveryNotSentError(cstr(exc), retryable=bool(exc.retryable)) from exc
	except PatientTemplateOutcomeUnknownError as exc:
		raise DeliveryOutcomeUnknownError(cstr(exc)) from exc
