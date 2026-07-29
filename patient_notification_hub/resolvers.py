from frappe.utils import cstr, flt


def patient_name(*, patient=None, **kwargs):
	if not patient:
		return ""
	return cstr(patient.get("patient_name") or patient.name)


def invoice_amount(*, doc=None, **kwargs):
	amount = flt(doc.get("rounded_total") or doc.get("grand_total"))
	currency = cstr(doc.get("currency")).strip()
	return f"{currency} {amount:.2f}".strip()
