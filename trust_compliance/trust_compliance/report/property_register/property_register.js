frappe.query_reports["Property Register"] = {
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
			fieldname: "fund",
			label: __("Fund"),
			fieldtype: "Link",
			options: "Fund",
			get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Active", "Under Dispute", "Disposed"],
			default: "Active",
		},
		{
			fieldname: "only_tax_due",
			label: __("Only properties with tax outstanding"),
			fieldtype: "Check",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "next_due" && data && data.tax_outstanding > 0) {
			const overdue = data.next_due && data.next_due < frappe.datetime.get_today();
			value = `<span style="color: var(--${overdue ? "red" : "orange"}-600)">${value}</span>`;
		}
		return value;
	},
};
