frappe.ui.form.on("Patient Notification", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		if (["Sending", "Outcome Unknown", "Failed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Reconcile Delivery"), () => {
				call_action(frm, "reconcile_notification");
			});
		}
		if (frm.doc.status === "Failed") {
			frm.add_custom_button(__("Retry"), () => {
				prompt_reason(__("Retry Notification"), (reason) => {
					call_action(frm, "retry_notification", { reason });
				});
			});
		}
		if (frm.doc.status === "Outcome Unknown") {
			frm.add_custom_button(__("Retry After Confirmation"), () => {
				frappe.confirm(
					__("Confirm that the provider did not deliver this message. Retrying may otherwise send a duplicate."),
					() => {
						prompt_reason(__("Retry Notification"), (reason) => {
							call_action(frm, "retry_notification", {
								confirm_ambiguous: 1,
								reason,
							});
						});
					},
				);
			});
			frm.add_custom_button(__("Mark Sent"), () => {
				prompt_reason(__("Mark Notification Sent"), (reason) => {
					call_action(frm, "mark_notification_sent", { reason });
				});
			});
		}
	},
});

function prompt_reason(title, callback) {
	frappe.prompt(
		[
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason"),
				reqd: 1,
			},
		],
		(values) => callback(values.reason),
		title,
		__("Continue"),
	);
}

function call_action(frm, action, args = {}) {
	return frappe.call({
		method: `patient_notification_hub.patient_notification_hub.doctype.patient_notification.patient_notification.${action}`,
		args: { name: frm.doc.name, ...args },
		freeze: true,
		callback: () => frm.reload_doc(),
	});
}

