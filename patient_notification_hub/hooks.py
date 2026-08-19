app_name = "patient_notification_hub"
app_title = "Patient Notification Hub"
app_publisher = "SRIAAS"
app_description = "Patient-focused configurable transactional notification engine"
app_email = "webdevelopersriaas@gmail.com"
app_license = "mit"

before_install = "patient_notification_hub.setup.validate_dependencies"
after_install = "patient_notification_hub.setup.after_install"
after_migrate = "patient_notification_hub.setup.after_migrate"

doc_events = {
	"*": {
		"after_insert": "patient_notification_hub.events.after_insert",
		"on_update": "patient_notification_hub.events.on_update",
		"on_submit": "patient_notification_hub.events.on_submit",
		"on_cancel": "patient_notification_hub.events.on_cancel",
	}
}

scheduler_events = {
	"daily": [
		"patient_notification_hub.event_inbox.purge_expired_event_snapshots",
	],
	"cron": {
		"*/5 * * * *": [
			"patient_notification_hub.workers.reconcile_notifications",
		]
	}
}

patient_notification_resolvers = {
	"patient_name": "patient_notification_hub.resolvers.patient_name",
	"invoice_amount": "patient_notification_hub.resolvers.invoice_amount",
}
