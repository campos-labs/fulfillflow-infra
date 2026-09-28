import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "review_persistence",
    Path(__file__).resolve().parents[1] / "scripts/azure/review_persistence.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.before = {
            key: key + "-synthetic"
            for key in (
                "cluster_id",
                "pod_uid",
                "pvc_uid",
                "pv_uid",
                "volume_handle",
                "event_id",
                "order_id",
                "shipment_id",
                "notification_id",
            )
        }
        self.before.update(
            namespace="fulfillflow",
            pod_name="postgres-0",
            ready=True,
            storage_driver="disk.csi.azure.com",
            states={
                "order": "FULFILLED",
                "shipment": "DELIVERED",
                "tracking": "APPLIED",
                "notification": "SIMULATED",
            },
        )
        self.after = {**self.before, "pod_uid": "replacement"}

    def test_same_volume_and_business_after_replacement(self):
        self.assertEqual(m.review(self.before, self.after)["review"], "passed")

    def test_same_pod_cannot_prove_recreation(self):
        with self.assertRaises(ValueError):
            m.review(self.before, self.before)

    def test_changed_identity_rejected(self):
        for key in (
            "cluster_id",
            "pvc_uid",
            "pv_uid",
            "volume_handle",
            "event_id",
            "notification_id",
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.review(self.before, {**self.after, key: "other"})

    def test_non_azure_driver_and_unconfirmed_result_rejected(self):
        for patch in (
            {"storage_driver": "rancher.io/local-path"},
            {"ready": False},
            {"states": {}},
            {"pod_name": "other-0"},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                m.review(self.before, {**self.after, **patch})
