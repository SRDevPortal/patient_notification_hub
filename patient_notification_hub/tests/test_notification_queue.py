from unittest import TestCase
from unittest.mock import patch

import frappe

from patient_notification_hub import outbox


class TestNotificationQueue(TestCase):
	def setUp(self):
		self.config = frappe._dict()
		self.config_patch = patch.object(outbox.frappe, "conf", self.config)
		self.config_patch.start()
		self.addCleanup(self.config_patch.stop)
		self.queues_patch = patch.object(
			outbox, "get_queues_timeout",
			return_value={"short": 300, "patient_notifications": 90},
		)
		self.queues_patch.start()
		self.addCleanup(self.queues_patch.stop)

	@patch.object(outbox.frappe, "enqueue")
	def test_existing_sites_keep_queue_and_deduplication(self, enqueue):
		outbox.enqueue_notification("NOTIF-1", enqueue_after_commit=True)
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["queue"], "short")
		self.assertEqual(kwargs["job_id"], "patient_notification_NOTIF-1")
		self.assertTrue(kwargs["deduplicate"])
		self.assertTrue(kwargs["enqueue_after_commit"])
		self.assertEqual(kwargs["timeout"], 90)

	@patch.object(outbox.frappe, "enqueue")
	def test_dedicated_queue_preserves_identity_for_recovery(self, enqueue):
		self.config.patient_notification_queue = "patient_notifications"
		outbox.enqueue_notification("NOTIF-1", enqueue_after_commit=False)
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["queue"], "patient_notifications")
		self.assertEqual(kwargs["job_id"], "patient_notification_NOTIF-1")
		self.assertTrue(kwargs["deduplicate"])
		self.assertFalse(kwargs["enqueue_after_commit"])

	@patch.object(outbox.frappe, "enqueue")
	def test_unregistered_queue_fails_instead_of_stranding_jobs(self, enqueue):
		self.config.patient_notification_queue = "typo_queue"
		with self.assertRaisesRegex(ValueError, "configured in Frappe workers"):
			outbox.enqueue_notification("NOTIF-1", enqueue_after_commit=False)
		enqueue.assert_not_called()

	def test_invalid_config_type_is_rejected(self):
		self.config.patient_notification_queue = ["short"]
		with self.assertRaises(ValueError):
			outbox.get_notification_queue()
