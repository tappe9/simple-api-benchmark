"""Flask investigation must keep all arms non-publishing and clean every cell."""

import importlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_benchmark_runner import Environment

from benchmark.environment import registered_pinned_versions
from benchmark.healthcheck import EXTERNAL_READINESS
from benchmark.report import validate_report
from benchmark.results import BenchmarkFailure


class DiagnosticEnvironment(Environment):
    def __init__(self, root, cell, fail=None):
        super().__init__(fail)
        self.artifacts = root / cell["id"]
        self.artifacts.mkdir()
        self.health_policy = EXTERNAL_READINESS
        self.connections = 50
        self.request_timeout = 15
        self.readiness = {"attempts": 1}

    def observe(self, label):
        self.event("observe")
        return {"label": label, "cpu_stat": "usage_usec 1"}


class FlaskDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("benchmark.flask_diagnostic"),
            "Flask needs the bounded non-publishing investigation runner",
        )
        self.module = importlib.import_module("benchmark.flask_diagnostic")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cache = self.root / ".cache" / "flask-diagnostic"
        self.cache.mkdir(parents=True)
        patcher = patch.object(self.module, "CACHE_ROOT", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.output = self.cache / "diagnostic.json"
        self.output.write_bytes(b"previous diagnostic")
        self.published = self.root / "results" / "latest.json"
        self.published.parent.mkdir()
        self.published.write_bytes(b"previous official result")
        self.metadata = {
            "source_commit": "a" * 40,
            "source_tree": "b" * 40,
            "versions": {"python-flask": registered_pinned_versions()["python-flask"]},
        }
        self.environments = []

    def run_diagnostic(self, fail=None, alter=None, phase="initial"):
        def factory(cell):
            environment = DiagnosticEnvironment(self.cache, cell, fail)
            if alter is not None:
                alter(environment)
            self.environments.append(environment)
            return environment

        def contract(url, *, implementation):
            return self.environments[-1].contract(url, implementation=implementation)

        return self.module.run_diagnostic(
            factory, self.output, metadata=self.metadata, contract=contract, phase=phase
        )

    def test_fixed_counterbalanced_plan_and_every_sample_are_preserved(self):
        result = self.run_diagnostic()
        self.assertEqual(
            [cell["arm"] for cell in result["cells"]],
            ["baseline", "switch-1ms", "queue-quiet", "queue-quiet", "switch-1ms", "baseline"],
        )
        self.assertEqual(len(self.environments), 6)
        for position, (cell, environment) in enumerate(zip(result["cells"], self.environments)):
            endpoints = ["/json", "/db/42"] if position < 3 else ["/db/42", "/json"]
            self.assertEqual([item["endpoint"] for item in cell["endpoints"]], endpoints)
            measured = [event for event in environment.events if isinstance(event, tuple)]
            self.assertEqual(
                measured,
                [
                    ("python-flask", endpoint, 5 if index == 0 else 10, index)
                    for endpoint in endpoints
                    for index in (0, 1, 2, 3)
                ],
            )
            self.assertEqual(environment.events.count("cleanup"), 1)
            self.assertIsNone(environment.active)
            self.assertEqual(cell["readiness"], {"attempts": 1})
        self.assertFalse(result["official"])
        self.assertFalse(result["publishable"])
        self.assertEqual(result["mode"], "flask-diagnostic")
        self.assertEqual(json.loads(self.output.read_bytes()), result)
        self.assertEqual(self.published.read_bytes(), b"previous official result")
        with self.assertRaises(BenchmarkFailure):
            validate_report(result)

    def test_all_failure_stages_clean_and_never_write_partial_success(self):
        for stage in (
            "build",
            "startup",
            "contract",
            "state",
            "warmup",
            "measurement",
            "metric",
            "observe",
            "cleanup",
        ):
            for folder in self.cache.iterdir():
                if folder.is_dir():
                    shutil.rmtree(folder)
            with self.subTest(stage=stage), self.assertRaises(BenchmarkFailure):
                self.run_diagnostic(stage)
            environment = self.environments[-1]
            self.assertEqual(environment.events.count("cleanup"), 1)
            self.assertEqual(self.output.read_bytes(), b"previous diagnostic")
            self.assertEqual(self.published.read_bytes(), b"previous official result")

    def test_cleanup_precedes_successful_output_and_retains_readiness(self):
        def alter(environment):
            original = environment.cleanup

            def cleanup():
                self.assertEqual(self.output.read_bytes(), b"previous diagnostic")
                original()
                environment.readiness = None

            environment.cleanup = cleanup

        self.run_diagnostic(alter=alter)

    def test_interruption_cleans_and_does_not_retry(self):
        def alter(environment):
            def interrupted(*args):
                raise KeyboardInterrupt

            environment.measure = interrupted

        with self.assertRaises(KeyboardInterrupt):
            self.run_diagnostic(alter=alter)
        self.assertEqual(len(self.environments), 1)
        self.assertEqual(self.environments[0].events.count("cleanup"), 1)
        self.assertEqual(self.output.read_bytes(), b"previous diagnostic")

    def test_incomplete_contract_cannot_start_load(self):
        def alter(environment):
            environment.contract = lambda *args, **kwargs: True

        with self.assertRaisesRegex(BenchmarkFailure, "contract"):
            self.run_diagnostic(alter=alter)
        self.assertEqual(self.environments[0].measures, 0)

    def test_invalid_profile_or_metadata_prevents_load(self):
        for field, value in (
            ("connections", 2),
            ("request_timeout", 1),
            ("health_policy", "container-healthcheck"),
        ):
            with self.subTest(field=field), self.assertRaises(BenchmarkFailure):
                self.run_diagnostic(alter=lambda environment: setattr(environment, field, value))
            self.assertNotIn("build", self.environments[-1].events)
            self.environments[-1].artifacts.rmdir()
        self.metadata["source_commit"] = "unknown"
        with self.assertRaises(BenchmarkFailure):
            self.run_diagnostic()

    def test_later_cell_failure_preserves_completed_evidence_without_final_result(self):
        count = 0

        def alter(environment):
            nonlocal count
            count += 1
            if count == 2:
                environment.fail = "measurement"

        with self.assertRaises(BenchmarkFailure):
            self.run_diagnostic(alter=alter)
        self.assertEqual(len(self.environments), 2)
        self.assertTrue(all(e.events.count("cleanup") == 1 for e in self.environments))
        progress = json.loads((self.cache / "progress.json").read_bytes())
        self.assertEqual(progress["status"], "failed")
        self.assertEqual(progress["failed_cell"], "block-1-switch-1ms")
        self.assertEqual(len(progress["cells"]), 1)
        self.assertEqual(self.output.read_bytes(), b"previous diagnostic")

    def test_image_drift_stops_before_loading_the_next_cell(self):
        count = 0

        def alter(environment):
            nonlocal count
            count += 1
            if count == 2:
                original = environment.start

                def changed_image(identifier):
                    result = original(identifier)
                    result["image_id"] = "sha256:changed-test-image"
                    return result

                environment.start = changed_image

        with self.assertRaisesRegex(BenchmarkFailure, "image changed"):
            self.run_diagnostic(alter=alter, phase="scheduling")
        self.assertEqual(len(self.environments), 2)
        self.assertEqual(self.environments[0].measures, 6)
        self.assertEqual(self.environments[1].measures, 0)
        self.assertTrue(all(e.events.count("cleanup") == 1 for e in self.environments))
        self.assertEqual(self.output.read_bytes(), b"previous diagnostic")
        self.assertEqual(self.published.read_bytes(), b"previous official result")
        progress = json.loads((self.cache / "progress.json").read_bytes())
        self.assertEqual(progress["status"], "failed")
        self.assertEqual(len(progress["cells"]), 1)

    def test_invalid_measurement_is_not_retried_or_selected(self):
        def alter(environment):
            original = environment.measure

            def measure(*args):
                value = original(*args)
                value["requests_per_second"] = float("nan")
                return value

            environment.measure = measure

        with self.assertRaises(BenchmarkFailure):
            self.run_diagnostic(alter=alter)
        self.assertEqual(len(self.environments), 1)
        self.assertEqual(self.environments[0].events.count("cleanup"), 1)
        self.assertEqual(self.output.read_bytes(), b"previous diagnostic")

    def test_output_and_symlinks_cannot_escape_cache(self):
        for path in (self.published, self.cache / ".." / "diagnostic.json"):
            with self.assertRaises(BenchmarkFailure):
                self.module.validate_output_path(path)
        linked = self.cache / "linked"
        linked.symlink_to(self.published.parent, target_is_directory=True)
        with self.assertRaises(BenchmarkFailure):
            self.module.validate_output_path(linked / "diagnostic.json")
        self.output.unlink()
        self.output.symlink_to(self.published)
        with self.assertRaises(BenchmarkFailure):
            self.run_diagnostic()
        self.assertEqual(self.published.read_bytes(), b"previous official result")

    def test_startup_hooks_change_only_the_declared_factor(self):
        for arm in ("baseline", "switch-1ms", "queue-quiet"):
            code = self.module.hook_source(arm)
            probe = (
                "import sys, logging, json\n"
                + code
                + '\nprint(json.dumps({"interval":sys.getswitchinterval(),"queue":logging.getLogger("waitress.queue").disabled,"root":logging.getLogger().disabled}))'
            )
            output = subprocess.check_output([sys.executable, "-c", probe], text=True, timeout=5)
            observed = json.loads(output.splitlines()[-1])
            self.assertEqual(
                observed["interval"], 0.001 if arm == "switch-1ms" else sys.getswitchinterval()
            )
            self.assertEqual(observed["queue"], arm == "queue-quiet")
            self.assertFalse(observed["root"])
        with self.assertRaises(BenchmarkFailure):
            self.module.hook_source("arbitrary-code")

    def test_scheduling_phase_has_bracketing_baselines_and_unchanged_load(self):
        self.assertIn("phase", inspect.signature(self.module.diagnostic_plan).parameters)
        plan = self.module.diagnostic_plan("scheduling")
        self.assertEqual([cell["arm"] for cell in plan], ["baseline", "affinity-one", "baseline"])
        self.assertTrue(all(cell["endpoints"] == ["/json", "/db/42"] for cell in plan))
        with self.assertRaises(BenchmarkFailure):
            self.module.diagnostic_plan("arbitrary")
        result = self.run_diagnostic(phase="scheduling")
        self.assertEqual(len(result["cells"]), 3)
        self.assertEqual(sum(e.measures for e in self.environments), 18)
        self.assertEqual(result["phase"], "scheduling")

    def test_affinity_hook_changes_only_the_child_allowed_cpu_set(self):
        self.assertIn("affinity-one", self.module.ARMS)
        before = sorted(os.sched_getaffinity(0))
        probe = self.module.hook_source("affinity-one") + (
            '\nprint(json.dumps({"affinity":sorted(os.sched_getaffinity(0)), '
            '"interval":sys.getswitchinterval(),"queue":logging.getLogger("waitress.queue").disabled}))'
        )
        output = subprocess.check_output([sys.executable, "-c", probe], text=True, timeout=5)
        observed = json.loads(output.splitlines()[-1])
        self.assertEqual(observed["affinity"], [before[0]])
        self.assertEqual(observed["interval"], 0.005)
        self.assertFalse(observed["queue"])
        self.assertEqual(sorted(os.sched_getaffinity(0)), before)

    def test_help_and_invalid_arguments_never_start_measurement(self):
        for args, code in ((["--help"], 0), (["--unknown"], 2)):
            with self.subTest(args=args), patch.object(sys, "argv", ["flask-diagnostic", *args]):
                with patch(
                    "benchmark.install_oha.ensure_oha",
                    side_effect=AssertionError("load must not start"),
                ):
                    with self.assertRaises(SystemExit) as stopped:
                        self.module.main()
                    self.assertEqual(stopped.exception.code, code)

    def test_baseline_override_does_not_change_command_or_environment(self):
        self.assertEqual(self.module.compose_override("baseline", self.cache), {})
        for arm in ("switch-1ms", "queue-quiet"):
            config = self.module.compose_override(arm, self.cache)
            service = config["services"]["python-flask"]
            self.assertEqual(set(service), {"environment", "volumes"})
            self.assertTrue(service["volumes"][0]["read_only"])
            self.assertEqual(service["environment"], {"PYTHONPATH": "/flask-diagnostic"})


if __name__ == "__main__":
    unittest.main()
