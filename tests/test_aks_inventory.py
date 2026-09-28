import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location(
    "inventory", Path(__file__).resolve().parents[1] / "scripts/azure/capture_inventory.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SUB = "00000000-0000-0000-0000-000000000000"


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.resource = {
            "id": f"/subscriptions/{SUB}/resourceGroups/test/providers/Microsoft.Compute/disks/test",
            "type": "Microsoft.Compute/disks",
            "location": "brazilsouth",
            "tags": {"private": "omitted"},
        }

    def test_pagination_and_minimal_projection(self):
        get = Mock(
            side_effect=[
                {
                    "value": [],
                    "nextLink": f"https://management.azure.com/subscriptions/{SUB}/resources?api-version=2021-04-01&$skiptoken=x",
                },
                {"value": [self.resource]},
            ]
        )
        result = m.collect(SUB, get)
        self.assertEqual(result["pages"], 2)
        self.assertNotIn("tags", result["resources"][0])

    def test_cross_scope_pagination_is_not_followed(self):
        for url in (
            "https://other.example/resources",
            "http://management.azure.com/resources",
            "https://management.azure.com/subscriptions/other/resources",
        ):
            get = Mock(return_value={"value": [], "nextLink": url})
            with self.subTest(url=url), self.assertRaises(ValueError):
                m.collect(SUB, get)
            self.assertEqual(get.call_count, 1)

    def test_duplicate_or_cross_subscription_identity_rejected(self):
        for records in (
            [self.resource, self.resource],
            [{**self.resource, "id": "/subscriptions/other/resource"}],
        ):
            with self.subTest(records=records), self.assertRaises(ValueError):
                m.collect(SUB, Mock(return_value={"value": records}))

    def test_empty_inventory_does_not_claim_zero_billing(self):
        result = m.collect(SUB, Mock(return_value={"value": []}))
        self.assertEqual(result["resources"], [])
        self.assertIn("not billing", result["limit"])
