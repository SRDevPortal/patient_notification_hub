import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, now_datetime

from patient_notification_hub.outbox import enqueue_notification
from patient_notification_hub.workers import reconcile_delivery


class PatientNotification(Document):
	pass


def _get_notification(name: str):
	frappe.only_for("System Manager")
	return frappe.get_doc("Patient Notification", name)


def _audit_recovery_action(notification, action: str, reason: str) -> None:
	reason = cstr(reason).strip()
	if not reason:
		frappe.throw(_("A reason is required for manual recovery actions."))
	notification.last_manual_action = action
	notification.last_manual_action_by = frappe.session.user
	notification.last_manual_action_on = now_datetime()
	notification.last_manual_action_reason = reason


@frappe.whitelist()
def reconcile_notification(name: str):
	_get_notification(name)
	return reconcile_delivery(name)


@frappe.whitelist()
def retry_notification(name: str, reason: str, confirm_ambiguous: int = 0):
	notification = _get_notification(name)
	if notification.status == "Outcome Unknown" and not cint(confirm_ambiguous):
		frappe.throw(_("Confirm that the provider did not deliver this message before retrying."))
	if notification.status not in {"Failed", "Outcome Unknown"}:
		frappe.throw(_("Only Failed or Outcome Unknown notifications can be retried."))
	_audit_recovery_action(notification, "Retry", reason)
	notification.manual_retry_count = cint(notification.manual_retry_count) + 1
	notification.manual_retry_authorized = 1
	notification.status = "Queued"
	notification.queued_on = now_datetime()
	notification.sending_started_on = None
	notification.next_retry_on = None
	notification.last_error = None
	notification.save(ignore_permissions=True)
	frappe.db.commit()
	enqueue_notification(notification.name, enqueue_after_commit=False)
	return {"success": True, "status": "Queued"}


@frappe.whitelist()
def mark_notification_sent(name: str, reason: str):
	notification = _get_notification(name)
	if notification.status not in {"Failed", "Outcome Unknown"}:
		frappe.throw(_("Only Failed or Outcome Unknown notifications can be manually marked Sent."))
	_audit_recovery_action(notification, "Mark Sent", reason)
	notification.status = "Sent"
	notification.sent_on = notification.sent_on or now_datetime()
	notification.sending_started_on = None
	notification.next_retry_on = None
	notification.reconciled_on = now_datetime()
	notification.manual_retry_authorized = 0
	notification.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "status": "Sent"}
