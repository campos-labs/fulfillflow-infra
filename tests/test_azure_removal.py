import copy
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "review_azure_removal", Path(__file__).resolve().parents[1] / "scripts/azure/review_removal.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RemovalReviewTests(unittest.TestCase):
    def setUp(self):
        self.identity = {
            "address": "azurerm_kubernetes_cluster.runtime",
            "type": "azurerm_kubernetes_cluster",
            "id": "/subscriptions/example/resourceGroups/runtime/providers/Microsoft.ContainerService/managedClusters/test",
        }
        self.inventory = {"delete": [self.identity]}
        self.plan = {
            "format_version": "1.2",
            "complete": True,
            "resource_changes": [
                {
                    **self.identity,
                    "mode": "managed",
                    "change": {"actions": ["delete"], "before": {"id": self.identity["id"]}},
                }
            ],
        }

    def test_exact_removal_is_reviewed_but_not_authorized(self):
        result = module.review(self.plan, self.inventory)
        self.assertEqual(result["approved_deletions"], 1)
        self.assertFalse(result["execution_authorized"])

    def test_registry_and_group_cannot_be_allowlisted(self):
        for kind in (
            "azurerm_container_registry",
            "azurerm_resource_group",
            "azurerm_storage_account",
        ):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                module.review(self.plan, {"delete": [{**self.identity, "type": kind}]})

    def test_replacement_update_or_create_is_rejected(self):
        for actions in (["delete", "create"], ["update"], ["create"]):
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                plan = copy.deepcopy(self.plan)
                plan["resource_changes"][0]["change"]["actions"] = actions
                module.review(plan, self.inventory)

    def test_other_subscription_id_is_rejected(self):
        self.plan["resource_changes"][0]["change"]["before"]["id"] = "/subscriptions/other/resource"
        with self.assertRaises(ValueError):
            module.review(self.plan, self.inventory)

    def test_missing_deletion_is_rejected(self):
        self.plan["resource_changes"] = []
        with self.assertRaises(ValueError):
            module.review(self.plan, self.inventory)

    def test_extra_deletion_is_rejected(self):
        other = copy.deepcopy(self.plan["resource_changes"][0])
        other["address"] = "azurerm_kubernetes_cluster.other"
        self.plan["resource_changes"].append(other)
        with self.assertRaises(ValueError):
            module.review(self.plan, self.inventory)

    def test_drift_and_incomplete_plans_are_rejected(self):
        for key, value in (
            ("complete", False),
            ("errored", True),
            ("deferred_changes", [1]),
            ("resource_drift", [1]),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.review({**self.plan, key: value}, self.inventory)

    def test_retained_registry_noop_is_allowed(self):
        self.plan["resource_changes"].append({"change": {"actions": ["no-op"]}})
        self.assertEqual(module.review(self.plan, self.inventory)["offline_review"], "passed")

    def test_explicit_exact_targeted_plan_is_not_full_convergence(self):
        plan = {**self.plan, "complete": False, "applyable": True}
        result = module.review(plan, self.inventory, targets=[self.identity["address"]])
        self.assertTrue(result["targeted"])
        self.assertFalse(result["full_configuration_convergence"])
        self.assertFalse(result["execution_authorized"])

    def test_target_list_must_match_exact_inventory(self):
        plan = {**self.plan, "complete": False, "applyable": True}
        for targets in ([], ["other"], [self.identity["address"]] * 2):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                module.review(plan, self.inventory, targets=targets)

    def test_targeting_does_not_bypass_other_guards(self):
        plan = {**self.plan, "complete": False, "applyable": True}
        for key, value in (
            ("errored", True),
            ("deferred_changes", [1]),
            ("resource_drift", [1]),
            ("applyable", False),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.review(
                    {**plan, key: value}, self.inventory, targets=[self.identity["address"]]
                )
        other = copy.deepcopy(plan)
        other["resource_changes"][0]["change"]["actions"] = ["update"]
        with self.assertRaises(ValueError):
            module.review(other, self.inventory, targets=[self.identity["address"]])
