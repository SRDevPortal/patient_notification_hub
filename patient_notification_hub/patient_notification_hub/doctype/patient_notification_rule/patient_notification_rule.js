frappe.ui.form.on("Patient Notification Rule", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.reference_doctype) {
			return;
		}
		frm.add_custom_button(__("Test Rule"), () => {
			frappe.prompt(
				[
					{
						fieldname: "reference_name",
						fieldtype: "Link",
						label: __("Test Document"),
						options: frm.doc.reference_doctype,
						reqd: 1,
					},
				],
				({ reference_name }) => {
					frappe.call({
						method: "patient_notification_hub.patient_notification_hub.doctype.patient_notification_rule.patient_notification_rule.test_rule",
						args: { name: frm.doc.name, reference_name },
						freeze: true,
						callback({ message }) {
							if (!message) return;
							const values = frappe.utils.escape_html(JSON.stringify(message.body_values));
							const preview = frappe.utils.escape_html(message.preview || "").replaceAll("\n", "<br>");
							frappe.msgprint({
								title: __("Rule Preview"),
								message: `<p><b>${__("Patient")}:</b> ${frappe.utils.escape_html(message.patient)}</p>
									<p><b>${__("Event Key")}:</b> ${frappe.utils.escape_html(message.event_key)}</p>
									<p><b>${__("Values")}:</b> ${values}</p><hr><div>${preview}</div>`,
							});
						},
					});
				},
				__("Test Notification Rule"),
			);
		});
	},
});
