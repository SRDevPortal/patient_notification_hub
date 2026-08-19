### Patient Notification Hub

Configurable patient transactional notifications for Frappe.

The app observes configured document events, creates an idempotent notification
outbox record, and delegates WhatsApp template delivery to `wa_chat_hub`.

Initial supported workflows:

- Sales Invoice generated
- Patient Encounter submitted
- Shipment order picked up
- Shipment out for delivery

The master switch and every generated rule are disabled by default. Configure and
test approved Interakt templates before enabling live delivery.

### Delivery safety

- Rule processing failures are retained as `Patient Notification Event` records and can be replayed.
  Snapshots contain only rule-referenced fields, are cleared after successful replay, and expire after
  the configured retention period.
- Failures that are definitely unsent use exponential backoff only when the provider marks them
  retryable. Network and post-send uncertainty becomes `Outcome Unknown` and is never retried
  automatically.
- Stale `Sending` records are reconciled against the outbound `Chat Message` dedupe key. They are not
  retried automatically when no local delivery evidence exists.
- System Managers can reconcile, confirm a retry, mark an ambiguous notification as sent, replay an
  event, or discard an event from the corresponding form. Manual retry and Mark Sent actions require
  a reason and record the acting user and time.

`Outcome Unknown` should only be retried after confirming that the provider did not deliver the message.

### Shipment Tracking cutover

When `shipment_tracking` is installed, select exactly one WhatsApp Notification Engine in Shipment
Tracking Settings. Existing sites remain on `Legacy Shipment Tracking` until a System Manager explicitly
enables this hub and switches the engine to `Patient Notification Hub`. The selector is enforced by both
apps: Legacy suppresses the hub's three overlapping rules, while Patient Notification Hub suppresses the
legacy creation and retry pipeline. Patient Encounter notifications remain owned by the hub.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app patient_notification_hub
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/patient_notification_hub
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
