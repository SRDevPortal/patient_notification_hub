from patient_notification_hub.indexes import ensure_indexes


def execute() -> None:
	ensure_indexes()
