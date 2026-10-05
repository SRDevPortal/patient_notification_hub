import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

from patient_notification_hub import privacy


class TestNotificationNumberPrivacy(unittest.TestCase):
    phone = "9876501234"

    def run_projection(self, path, payload, *, form=None, restricted=True):
        request = Request(EnvironBuilder(path=path, method="GET").get_environ())
        response = Response(
            json.dumps(payload),
            status=200,
            mimetype="application/json",
        )
        with patch.object(privacy, "restricted", return_value=restricted),              patch.object(frappe.local, "form_dict", frappe._dict(form or {})):
            privacy.protect_response(request, response)
        return response

    def test_project_masks_preview_values_and_errors_without_mutation(self):
        raw = {
            "doctype": "Patient Notification",
            "body_values": [self.phone, "Appointment"],
            "body_values_json": json.dumps([self.phone]),
            "body_preview": f"Call {self.phone}",
            "context_json": json.dumps({"mobile_no": self.phone}),
            "last_error": f"Provider rejected {self.phone}",
            "provider_response": {"phoneNumber": self.phone},
        }

        result = privacy.project(raw)

        self.assertNotIn(self.phone, frappe.as_json(result))
        self.assertNotIn("provider_response", result)
        self.assertEqual(raw["body_preview"], f"Call {self.phone}")

    def test_event_snapshots_are_removed_from_restricted_response(self):
        payload = {
            "data": {
                "doctype": "Patient Notification Event",
                "name": "EVENT-1",
                "document_json": json.dumps({"mobile_no": self.phone}),
                "previous_document_json": json.dumps({"phone": self.phone}),
                "last_error": f"Recipient {self.phone}",
            }
        }

        response = self.run_projection(
            "/api/resource/Patient%20Notification%20Event/EVENT-1",
            payload,
        )
        data = response.get_json()["data"]

        self.assertNotIn(self.phone, response.get_data(as_text=True))
        self.assertNotIn("document_json", data)
        self.assertNotIn("previous_document_json", data)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_reportview_uses_requested_doctype_for_projection(self):
        payload = {
            "message": {
                "keys": ["name", "body_preview", "last_error"],
                "values": [["NOTIF-1", f"Call {self.phone}", f"Failed {self.phone}"]],
            }
        }

        response = self.run_projection(
            "/api/method/frappe.desk.reportview.get",
            payload,
            form={"doctype": "Patient Notification"},
        )

        self.assertNotIn(self.phone, response.get_data(as_text=True))

    def test_full_visibility_and_unrelated_responses_stay_unchanged(self):
        payload = {
            "data": {
                "doctype": "Patient Notification",
                "body_preview": f"Call {self.phone}",
            }
        }
        full = self.run_projection(
            "/api/resource/Patient%20Notification/NOTIF-1",
            payload,
            restricted=False,
        )
        unrelated = self.run_projection(
            "/api/resource/ToDo/TODO-1",
            {"data": {"doctype": "ToDo", "description": self.phone}},
        )

        self.assertEqual(full.get_json(), payload)
        self.assertEqual(unrelated.get_json()["data"]["description"], self.phone)

    def test_projection_failure_never_returns_raw_response(self):
        payload = {
            "data": {
                "doctype": "Patient Notification",
                "body_preview": self.phone,
            }
        }
        request = Request(
            EnvironBuilder(
                path="/api/resource/Patient%20Notification/NOTIF-1",
                method="GET",
            ).get_environ()
        )
        response = Response(json.dumps(payload), status=200, mimetype="application/json")

        with patch.object(privacy, "restricted", return_value=True),              patch.object(privacy, "project", side_effect=ValueError("failed")),              patch.object(frappe.local, "form_dict", frappe._dict()):
            privacy.protect_response(request, response)

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(self.phone, response.get_data(as_text=True))

    def test_export_and_print_are_denied_only_for_restricted_target(self):
        target_request = SimpleNamespace(path="/api/method/frappe.utils.print_format.download_pdf")
        with patch.object(privacy, "restricted", return_value=True),              patch.object(privacy.frappe, "request", target_request),              patch.object(
                 frappe.local,
                 "form_dict",
                 frappe._dict(doctype="Patient Notification"),
             ):
            with self.assertRaises(frappe.PermissionError):
                privacy.guard_raw_outputs()

        with patch.object(privacy, "restricted", return_value=False),              patch.object(privacy.frappe, "request", target_request),              patch.object(
                 frappe.local,
                 "form_dict",
                 frappe._dict(doctype="Patient Notification"),
             ):
            privacy.guard_raw_outputs()

    def test_before_request_defers_token_identity_to_auth_hook(self):
        request = SimpleNamespace(
            path="/api/method/frappe.utils.print_format.download_pdf",
            headers={"Authorization": "token key:secret"},
        )
        with patch.object(privacy.frappe, "request", request),              patch.object(privacy.frappe, "session", SimpleNamespace(user="Guest")),              patch.object(privacy, "restricted") as restricted,              patch.object(
                 frappe.local,
                 "form_dict",
                 frappe._dict(doctype="Patient Notification"),
             ):
            privacy.guard_raw_outputs()

        restricted.assert_not_called()

    def test_custom_api_wrapper_masks_restricted_result(self):
        raw = {
            "preview": f"Call {self.phone}",
            "body_values": [self.phone],
            "provider_response": {"phoneNumber": self.phone},
        }
        endpoint = privacy.browser_response(lambda: raw)

        with patch.object(privacy, "restricted", return_value=True):
            result = endpoint()
        self.assertNotIn(self.phone, frappe.as_json(result))
        self.assertEqual(raw["preview"], f"Call {self.phone}")

        with patch.object(privacy, "restricted", return_value=False):
            self.assertIs(endpoint(), raw)
