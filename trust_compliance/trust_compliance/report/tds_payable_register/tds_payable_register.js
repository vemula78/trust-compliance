frappe.query_reports["TDS Payable Register"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "as_on",
			label: __("As On"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			description: __("TDS deducted but not yet remitted, as at this date."),
		},
	],
};
