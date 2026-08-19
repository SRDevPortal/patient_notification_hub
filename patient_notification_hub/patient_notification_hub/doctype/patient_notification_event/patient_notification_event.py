import frappe
from frappe import _
from frappe.model.document import Document

from patient_notification_hub.event_inbox import enqueue_event


class PatientNotificationEvent(Document):
	pass


def _get_event(name: str):
	frappe.only_for("System Manager")
	return frappe.get_doc("Patient Notification Event", name)


@frappe.whitelist()
def retry_event(name: str):
	event = _get_event(name)
	if event.status not in {"Captured", "Failed"}:
		frappe.throw(_("Only Captured or Failed events can be retried."))
	event.status = "Captured"
	event.attempt_count = 0
	event.next_retry_on = None
	event.last_error = None
	event.save(ignore_permissions=True)
	frappe.db.commit()
	enqueue_event(event.name, enqueue_after_commit=False)
	return {"success": True, "status": "Captured"}


@frappe.whitelist()
def discard_event(name: str):
	event = _get_event(name)
	if event.status == "Processed":
		frappe.throw(_("Processed events cannot be discarded."))
	event.status = "Discarded"
	event.next_retry_on = None
	event.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "status": "Discarded"}
