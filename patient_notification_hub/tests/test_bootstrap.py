from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from patient_notification_hub.events import process_document_event
from patient_notification_hub.setup import validate_dependencies


class TestPatientNotificationBootstrap(FrappeTestCase):
	@patch("patient_notification_hub.setup.frappe.get_installed_apps", return_value=["wa_chat_hub"])
	@patch("patient_notification_hub.setup.frappe.setup_module_map")
	def test_dependency_validation_refreshes_module_map(self, setup_module_map, get_installed_apps):
		validate_dependencies()

		setup_module_map.assert_called_once_with(include_all_apps=True)
		get_installed_apps.assert_called_once()

	@patch("patient_notification_hub.setup.frappe.setup_module_map")
	def test_dependency_validation_rejects_missing_app_module(self, setup_module_map):
		app_modules = frappe.local.app_modules
		try:
			frappe.local.app_modules = {}
			with self.assertRaises(frappe.ValidationError):
				validate_dependencies()
		finally:
			frappe.local.app_modules = app_modules

		setup_module_map.assert_called_once_with(include_all_apps=True)

	@patch(
		"patient_notification_hub.events.frappe.get_cached_doc",
		side_effect=frappe.DoesNotExistError,
	)
	def test_document_event_is_ignored_before_settings_doctype_exists(self, get_cached_doc):
		result = process_document_event(
			frappe._dict(doctype="DocType", name="Test Bootstrap DocType"),
			"After Insert",
		)

		self.assertEqual(result, [])
		get_cached_doc.assert_called_once_with("Patient Notification Settings")

	@patch("patient_notification_hub.events.frappe.get_cached_doc", side_effect=ImportError)
	def test_document_event_is_ignored_when_settings_controller_is_unavailable(self, get_cached_doc):
		result = process_document_event(
			frappe._dict(doctype="DocType", name="Test Bootstrap DocType"),
			"After Insert",
		)

		self.assertEqual(result, [])
		get_cached_doc.assert_called_once_with("Patient Notification Settings")

	@patch("patient_notification_hub.events.frappe.get_cached_doc")
	def test_document_event_is_ignored_during_migration(self, get_cached_doc):
		in_migrate = frappe.flags.in_migrate
		try:
			frappe.flags.in_migrate = True
			result = process_document_event(
				frappe._dict(doctype="DocType", name="Test Bootstrap DocType"),
				"After Insert",
			)
		finally:
			frappe.flags.in_migrate = in_migrate

		self.assertEqual(result, [])
		get_cached_doc.assert_not_called()
