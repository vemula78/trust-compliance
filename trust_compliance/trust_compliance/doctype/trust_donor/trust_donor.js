// Form 10BE is issued per donor per financial year, so it lives on the donor
// rather than on any single receipt.
frappe.ui.form.on("Trust Donor", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.is_anonymous) {
			return;
		}

		frm.add_custom_button(__("Form 10BE Certificate"), () => {
			const today = frappe.datetime.now_date(true);
			const start = today.getMonth() + 1 >= 4 ? today.getFullYear() : today.getFullYear() - 1;

			frappe.prompt(
				[
					{
						fieldname: "financial_year",
						label: __("Financial Year"),
						fieldtype: "Data",
						reqd: 1,
						default: `${start}-${String((start + 1) % 100).padStart(2, "0")}`,
						description: __("Indian financial year, April to March, e.g. 2026-27"),
					},
				],
				({ financial_year }) => {
					frappe.call({
						method: "trust_compliance.form_10be.get_certificate_html",
						args: { donor: frm.doc.name, financial_year },
						freeze: true,
						freeze_message: __("Preparing certificate..."),
						callback({ message }) {
							if (!message) {
								return;
							}
							const win = window.open("", "_blank");
							win.document.write(message);
							win.document.close();
							win.focus();
							win.print();
						},
					});
				},
				__("Form 10BE Certificate"),
				__("Generate")
			);
		});
	},
});
