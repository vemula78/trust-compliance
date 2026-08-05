// Current Indian financial year (April-March), so the filter opens on the year
// the user is almost certainly reporting on.
function trust_compliance_current_fy() {
	const today = frappe.datetime.now_date(true);
	const start = today.getMonth() + 1 >= 4 ? today.getFullYear() : today.getFullYear() - 1;
	return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

frappe.query_reports["Income Application"] = {
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
			fieldname: "financial_year",
			label: __("Financial Year"),
			fieldtype: "Data",
			reqd: 1,
			default: trust_compliance_current_fy(),
			description: __("Indian financial year, April to March, e.g. 2026-27"),
		},
	],
};
