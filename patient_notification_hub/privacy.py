"""Customer-number privacy at Patient Notification browser boundaries."""
from __future__ import annotations

from copy import deepcopy
from functools import wraps
import json
import re
from urllib.parse import unquote

import frappe


TARGET_DOCTYPES = frozenset({
    "Patient Notification",
    "Patient Notification Event",
})
RAW_KEYS = frozenset({
    "document_json",
    "previous_document_json",
    "provider_response",
    "raw_payload",
    "raw_transport_payload",
    "payload",
})
PHONE_KEYS = frozenset({
    "phone",
    "phone_number",
    "phoneNumber",
    "mobile",
    "mobile_no",
    "contact_phone_number",
    "channel_phone_number",
    "normalized_phone",
    "recipient_phone",
    "user_phone",
})
TEXT_KEYS = frozenset({
    "body_values",
    "body_values_json",
    "body_preview",
    "context_json",
    "last_error",
    "skip_reason",
    "last_manual_action_reason",
    "preview",
    "error",
    "reason",
    "message",
})


def enabled() -> bool:
    return bool(frappe.conf.get("privacy_shield_desk_enabled", False)) and (
        "privacy_shield" in frappe.get_installed_apps()
    )


def restricted() -> bool:
    if not enabled():
        return False
    from privacy_shield.policy import current_capabilities

    return not current_capabilities().view_full


def project(payload):
    """Copy and redact browser data without changing delivery records."""
    from privacy_shield.display_text import mask_display
    from privacy_shield.masking import mask_number

    def clean(value, context=None):
        if isinstance(value, list):
            return [clean(item, context) for item in value]
        if isinstance(value, tuple):
            return tuple(clean(item, context) for item in value)
        if not isinstance(value, dict):
            if context in TEXT_KEYS and isinstance(value, str):
                return mask_display(value)
            return deepcopy(value)

        if isinstance(value.get("keys"), list) and isinstance(value.get("values"), list):
            keys = value["keys"]
            indexes = [index for index, key in enumerate(keys) if key not in RAW_KEYS]
            result = {
                key: clean(item, key)
                for key, item in value.items()
                if key not in {"keys", "values"} and key not in RAW_KEYS
            }
            result["keys"] = [keys[index] for index in indexes]
            result["values"] = [
                [
                    clean(row[index], keys[index])
                    for index in indexes
                    if index < len(row)
                ]
                for row in value["values"]
            ]
            return result

        result = {}
        for key, item in value.items():
            if key in RAW_KEYS:
                continue
            if key in PHONE_KEYS:
                result[key] = (
                    item
                    if isinstance(item, str)
                    and re.fullmatch(r"\*{1,14}[0-9]{0,4}|\[masked\]", item)
                    else mask_number(item)
                )
            elif key in TEXT_KEYS:
                result[key] = clean(item, key)
            else:
                result[key] = clean(item, key)
        return result

    return clean(payload)


def browser_response(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        result = fn(*args, **kwargs)
        return project(result) if restricted() else result

    return wrapped


def _payload_doctype(payload):
    if isinstance(payload, dict):
        doctype = payload.get("doctype")
        if doctype in TARGET_DOCTYPES:
            return doctype
        for key in ("docs", "data", "message", "result"):
            found = _payload_doctype(payload.get(key))
            if found:
                return found
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            found = _payload_doctype(item)
            if found:
                return found
    return None


def _request_doctype(request=None, payload=None):
    form = getattr(frappe.local, "form_dict", {}) or {}
    for key in ("doctype", "dt", "parent_doctype"):
        if form.get(key) in TARGET_DOCTYPES:
            return form.get(key)

    selected = form.get("select_columns")
    if selected:
        try:
            selected = json.loads(selected) if isinstance(selected, str) else selected
        except (TypeError, ValueError):
            selected = None
        if isinstance(selected, dict):
            for doctype in TARGET_DOCTYPES:
                if doctype in selected:
                    return doctype

    path = unquote(getattr(request, "path", "") or "")
    for doctype in TARGET_DOCTYPES:
        if doctype in path:
            return doctype
    return _payload_doctype(payload)


def guard_raw_outputs():
    """Restricted users cannot export or print raw notification snapshots."""
    request = getattr(frappe, "request", None)
    authorization = (
        getattr(request, "headers", {}).get("Authorization", "")
        if request is not None
        else ""
    )
    # before_request precedes token authentication. The same guard runs again
    # as an auth hook after Frappe has established the token user's identity.
    if authorization and getattr(frappe.session, "user", "Guest") == "Guest":
        return
    if not restricted():
        return
    doctype = _request_doctype(request)
    if not doctype:
        return
    form = getattr(frappe.local, "form_dict", {}) or {}
    operation = " ".join(
        str(value or "")
        for value in (
            form.get("cmd"),
            form.get("method"),
            getattr(request, "path", ""),
        )
    ).lower()
    if any(token in operation for token in ("export", "download", "print")):
        raise frappe.PermissionError(
            f"Export and print are unavailable for protected {doctype} records."
        )


def protect_response(request, response):
    """Project successful JSON responses after normal Frappe authorization."""
    if not 200 <= response.status_code < 300:
        return
    try:
        if not restricted():
            return
        payload = response.get_json(silent=True)
        if payload is None or not _request_doctype(request, payload):
            return
        response.set_data(json.dumps(project(payload), ensure_ascii=False, default=str))
        response.headers["Cache-Control"] = "no-store"
        response.mimetype = "application/json"
    except Exception:
        response.status_code = 500
        response.set_data(json.dumps({
            "exc_type": "PrivacyProjectionError",
            "message": "Unable to prepare a protected notification response.",
        }))
        response.headers["Cache-Control"] = "no-store"
        response.mimetype = "application/json"
