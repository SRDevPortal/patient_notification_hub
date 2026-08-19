frappe.ui.form.on("Patient Notification Event", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (["Captured", "Failed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Retry Event"), () => call_event_action(frm, "retry_event"));
		}
		if (!["Processed", "Discarded"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Discard"), () => {
				frappe.confirm(__("Discard this captured notification event?"), () => {
					call_event_action(frm, "discard_event");
				});
			});
		}
	},
});

function call_event_action(frm, action) {
	return frappe.call({
		method: `patient_notification_hub.patient_notification_hub.doctype.patient_notification_event.patient_notification_event.${action}`,
		args: { name: frm.doc.name },
		freeze: true,
		callback: () => frm.reload_doc(),
	});
}
