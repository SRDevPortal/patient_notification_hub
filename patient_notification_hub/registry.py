from collections.abc import Callable

import frappe
from frappe import _


BUILTIN_RESOLVERS = {
	"patient_name": "patient_notification_hub.resolvers.patient_name",
	"invoice_amount": "patient_notification_hub.resolvers.invoice_amount",
}


def get_resolver(key: str) -> Callable:
	key = (key or "").strip()
	resolvers = dict(BUILTIN_RESOLVERS)
	configured = frappe.get_hooks("patient_notification_resolvers")
	if isinstance(configured, dict):
		for resolver_key, method in configured.items():
			resolvers[resolver_key] = method[-1] if isinstance(method, list) else method
	else:
		for item in configured or []:
			if isinstance(item, dict):
				for resolver_key, method in item.items():
					resolvers[resolver_key] = method[-1] if isinstance(method, list) else method

	method = resolvers.get(key)
	if not method:
		frappe.throw(_("Patient notification resolver {0} is not registered.").format(key))
	return frappe.get_attr(method) if isinstance(method, str) else method
