import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint
from frappe.utils.scheduler import is_scheduler_disabled, is_scheduler_inactive


class PatientNotificationSettings(Document):
	def validate(self):
		if cint(self.maximum_attempts) < 1:
			frappe.throw(_("Maximum Attempts must be at least 1."))
		if cint(self.base_retry_delay_minutes) < 1:
			frappe.throw(_("Base Retry Delay must be at least 1 minute."))
		if cint(self.stale_sending_timeout_minutes) < 1:
			frappe.throw(_("Stale Sending Timeout must be at least 1 minute."))
		if cint(self.worker_batch_size) < 1:
			frappe.throw(_("Worker Batch Size must be at least 1."))
		if cint(getattr(self, "event_snapshot_retention_days", 7)) < 1:
			frappe.throw(_("Event Snapshot Retention must be at least 1 day."))
		if cint(self.queued_recovery_timeout_minutes) < 1:
			frappe.throw(_("Queued Recovery Timeout must be at least 1 minute."))
		if cint(self.enable_background_recovery) and not any(
			(
				cint(self.enable_failed_retry),
				cint(self.enable_queued_recovery),
				cint(self.enable_stale_sending_recovery),
			)
		):
			frappe.throw(_("Enable at least one background recovery feature."))
		if cint(self.enable_default_interakt_fallback):
			self._validate_fallback_account()

	def on_update(self):
		frappe.clear_cache(doctype=self.doctype)

	def _validate_fallback_account(self):
		if not self.default_interakt_account:
			frappe.throw(_("Default Interakt Account is required when fallback routing is enabled."))
		account = frappe.get_doc("Chat Channel Account", self.default_interakt_account)
		if not cint(account.is_active) or account.channel_type != "Interakt":
			frappe.throw(_("Default Interakt Account must be an active Interakt account."))


@frappe.whitelist()
def get_scheduler_status():
	frappe.only_for("System Manager")
	disabled = is_scheduler_disabled(verbose=False)
	inactive = is_scheduler_inactive(verbose=False)
	if disabled:
		message = _("The Frappe scheduler is disabled in System Settings.")
	elif inactive:
		message = _("The Frappe scheduler is currently inactive.")
	else:
		message = _("The Frappe scheduler is enabled and active.")
	return {
		"enabled": not disabled,
		"active": not inactive,
		"message": message,
	}
