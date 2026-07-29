frappe.ui.form.on("Patient Notification Settings", {
	setup(frm) {
		frm.set_query("default_interakt_account", () => ({
			filters: {
				channel_type: "Interakt",
				is_active: 1,
			},
		}));
	},
	refresh(frm) {
		load_scheduler_status(frm);
		frm.add_custom_button(__("Refresh Scheduler Status"), () => load_scheduler_status(frm));
	},
	enable_background_recovery(frm) {
		load_scheduler_status(frm);
	},
});

function load_scheduler_status(frm) {
	frappe.call({
		method: "patient_notification_hub.patient_notification_hub.doctype.patient_notification_settings.patient_notification_settings.get_scheduler_status",
		callback({ message }) {
			if (!message) {
				return;
			}
			const recovery_enabled = Boolean(frm.doc.enable_background_recovery);
			const ready = message.enabled && message.active;
			const indicator = ready ? "green" : "orange";
			const recovery_note =
				recovery_enabled && !ready
					? __("Background recovery cannot run until the site scheduler is enabled and active.")
					: "";
			const html = `
				<div class="form-message ${indicator}">
					<div><strong>${frappe.utils.escape_html(message.message)}</strong></div>
					${recovery_note ? `<div class="text-muted">${frappe.utils.escape_html(recovery_note)}</div>` : ""}
				</div>
			`;
			frm.fields_dict.scheduler_status_html.$wrapper.html(html);
		},
	});
}
