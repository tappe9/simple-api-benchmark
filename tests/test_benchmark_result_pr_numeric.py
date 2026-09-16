"""Reject numeric coercion in raw PR/CI/policy snapshots."""

import unittest

from test_benchmark_result_pr import mutate, snapshots

from benchmark import result_pr


class NumericIdentityTests(unittest.TestCase):
    def test_ci_identity_floats_cannot_equal_integer_ids(self):
        candidate, arguments = snapshots()
        paths = (
            ("ci_run", "workflow_id"),
            ("ci_run", "pull_requests", 0, "number"),
            ("ci_run", "pull_requests", 0, "head", "repo", "id"),
            ("ci_run", "pull_requests", 0, "base", "repo", "id"),
            ("checks", 0, "check_suite", "id"),
            ("checks", 0, "app", "id"),
        )
        for path in paths:
            value = arguments
            for key in path:
                value = value[key]
            with self.subTest(path=path):
                with self.assertRaises(result_pr.ResultPRFailure) as caught:
                    result_pr.plan_merge(candidate, **mutate(arguments, path, float(value)))
                self.assertEqual(caught.exception.code, "invalid_ci")

    def test_policy_integration_id_must_be_integer_even_when_snapshots_agree(self):
        candidate, arguments = snapshots()
        for policy in ("ruleset", "effective_rules"):
            rules = arguments[policy]["rules"] if policy == "ruleset" else arguments[policy]
            rules[3]["parameters"]["required_status_checks"][0]["integration_id"] = 15368.0
        with self.assertRaises(result_pr.ResultPRFailure) as caught:
            result_pr.plan_merge(candidate, **arguments)
        self.assertEqual(caught.exception.code, "policy_unverified")


if __name__ == "__main__":
    unittest.main()
