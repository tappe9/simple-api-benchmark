"""Parse actual workflow YAML to verify the read/write and trusted-source boundaries."""

import json
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from registry_fixtures import extended_registry

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    path = ROOT / ".github/workflows" / name
    if not path.exists():
        return {}
    # BaseLoader deliberately preserves YAML 1.2 Actions keys such as `on` and bool strings.
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


class WorkflowTests(unittest.TestCase):
    def test_only_four_permanent_workflows_use_pinned_actions_and_safe_checkouts(self):
        paths = list((ROOT / ".github/workflows").glob("*.yml"))
        self.assertEqual(
            {p.name for p in paths}, {"ci.yml", "benchmark.yml", "pages.yml", "pages-deploy.yml"}
        )
        for path in paths:
            workflow = load(path.name)
            for job in workflow["jobs"].values():
                if "uses" in job:
                    self.assertEqual(job["uses"], "./.github/workflows/pages-deploy.yml")
                    self.assertNotIn("steps", job)
                    self.assertNotIn("secrets", job)
                    continue
                self.assertEqual(job["runs-on"], "ubuntu-24.04")
                self.assertGreater(int(job["timeout-minutes"]), 0)
                for step in job["steps"]:
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"^actions/[a-z-]+@[0-9a-f]{40}$")
                        if step["uses"].startswith("actions/checkout@"):
                            self.assertEqual(step["with"]["persist-credentials"], "false")
                    self.assertNotIn("${{", step.get("run", ""), "pass expression data through env")

    def test_pr_ci_is_split_read_only_and_never_publishes(self):
        ci = load("ci.yml")
        self.assertEqual(ci["permissions"], {"contents": "read"})
        self.assertIn("pull_request", ci.get("on", {}))
        self.assertEqual(set(ci["on"]), {"pull_request", "push"})
        self.assertEqual(ci["on"]["push"]["branches"], ["main"])
        self.assertEqual(
            set(ci["on"]["push"]["paths-ignore"]),
            {"results/**", "README.md", "README.ja.md"},
        )
        self.assertEqual(
            set(ci["jobs"]),
            {"plan", "shared", "implementation", "smoke", "required"},
        )
        content = (ROOT / ".github/workflows/ci.yml").read_text()
        for forbidden in (
            "secrets.",
            "contents: write",
            "pull_request_target",
            "workflow_run",
            "benchmark.official",
            "benchmark.publish",
            "deploy-pages",
        ):
            self.assertNotIn(forbidden, content)
        self.assertIn("actionlint", content)
        self.assertIn("test_workflows.py", content)
        self.assertIn("git diff --exit-code HEAD", content)
        self.assertNotIn("healthcheck-investigation", content)

    def test_split_ci_matrix_is_registry_driven_and_compose_owned(self):
        ci = load("ci.yml")
        plan = ci["jobs"]["plan"]
        implementation = ci["jobs"]["implementation"]
        self.assertEqual(implementation["needs"], "plan")
        self.assertEqual(implementation["strategy"]["fail-fast"], "false")
        self.assertEqual(
            implementation["strategy"]["matrix"], "${{ fromJSON(needs.plan.outputs.matrix) }}"
        )
        self.assertEqual(plan["outputs"]["matrix"], "${{ steps.matrix.outputs.matrix }}")
        matrix_step = next(step for step in plan["steps"] if step.get("id") == "matrix")
        self.assertEqual(matrix_step["run"], 'python -m benchmark.ci matrix >> "$GITHUB_OUTPUT"')
        registry = json.loads((ROOT / "benchmark/implementations.json").read_text())
        workflow_text = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertNotIn(
            "implementation: ["
            + ", ".join(spec["id"] for spec in registry["implementations"])
            + "]",
            workflow_text,
        )
        self.assertEqual(implementation["env"]["IMPLEMENTATION_ID"], "${{ matrix.implementation }}")
        project = implementation["env"]["COMPOSE_PROJECT_NAME"]
        for expected in ("github.run_id", "github.run_attempt", "matrix.implementation"):
            self.assertIn(expected, project)
        command_text = "\n".join(step.get("run", "") for step in implementation["steps"])
        self.assertIn('make "test-$IMPLEMENTATION_ID"', command_text)
        self.assertIn('CONTRACT_IMPL="$IMPLEMENTATION_ID"', command_text)
        cleanup = next(
            step for step in implementation["steps"] if "docker compose -p" in step.get("run", "")
        )
        self.assertEqual(cleanup["if"], "always()")
        self.assertIn('docker compose -p "$COMPOSE_PROJECT_NAME" down', cleanup["run"])

    def test_implementation_setup_is_selected_and_all_host_gates_are_isolated(self):
        job = load("ci.yml")["jobs"]["implementation"]
        self.assertEqual(job.get("name"), "implementation (${{ matrix.implementation }})")
        steps = job["steps"]
        for action, condition in (
            ("actions/setup-python@", None),
            ("actions/setup-go@", "matrix.toolchain == 'go'"),
            ("actions/setup-node@", "matrix.toolchain == 'node'"),
        ):
            matching = [step for step in steps if step.get("uses", "").startswith(action)]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0].get("if"), condition)
        java = next(step for step in steps if step.get("name") == "Install pinned Java toolchain")
        self.assertEqual(java["if"], "matrix.toolchain == 'java'")
        self.assertIn("sha256sum -c -", java["run"])
        self.assertIn("jdk-25.0.4.1%2B1", java["run"])
        self.assertNotIn("continue-on-error", java)
        rust = next(step for step in steps if step.get("name") == "Install pinned Rust toolchain")
        self.assertEqual(rust["if"], "matrix.toolchain == 'rust'")
        self.assertEqual(
            rust["run"],
            "rustup toolchain install 1.98.1 --profile minimal --component rustfmt,clippy",
        )
        for command in (
            'make "test-$IMPLEMENTATION_ID"',
            'make test-contract CONTRACT_IMPL="$IMPLEMENTATION_ID"',
            "make axum-diagnostic",
        ):
            matching = [step for step in steps if command in step.get("run", "")]
            self.assertEqual(len(matching), 1)
            self.assertIn(
                'python -m benchmark.ci run-isolated --implementation "$IMPLEMENTATION_ID" -- '
                + command,
                matching[0]["run"],
            )
            self.assertNotIn("continue-on-error", matching[0])
        self.assertEqual(
            next(step for step in steps if step.get("uses", "").startswith("actions/setup-go@"))[
                "with"
            ],
            {"go-version": "1.27.1", "cache": "false"},
        )
        self.assertEqual(
            next(step for step in steps if step.get("uses", "").startswith("actions/setup-node@"))[
                "with"
            ],
            {"node-version-file": "apps/node-fastify/.node-version"},
        )

    def test_axum_diagnostic_is_required_in_its_read_only_implementation_job(self):
        job = load("ci.yml")["jobs"]["implementation"]
        diagnostic = [
            step for step in job["steps"] if "make axum-diagnostic" in step.get("run", "")
        ]
        self.assertEqual(len(diagnostic), 1)
        step = diagnostic[0]
        self.assertEqual(step["if"], "matrix.implementation == 'rust-axum'")
        self.assertNotIn("continue-on-error", step)
        self.assertIn("git diff --exit-code HEAD", step["run"])
        self.assertIn("git ls-files --others --exclude-standard", step["run"])
        artifacts = [
            step
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact@")
        ]
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["with"]["path"], ".cache/axum-diagnostic/")
        self.assertEqual(artifacts[0]["if"], "always() && matrix.implementation == 'rust-axum'")

    def test_split_ci_preserves_shared_smoke_and_fail_closed_aggregate(self):
        ci = load("ci.yml")
        shared = str(ci["jobs"]["shared"])
        for expected in (
            "Python 3.10 shared compatibility",
            "make test-registry",
            "make test-site",
            "make test-db",
            "make test-benchmark",
            "python -O",
            "actionlint",
        ):
            self.assertIn(expected, shared)
        smoke = str(ci["jobs"]["smoke"])
        for expected in (
            "make benchmark-smoke",
            "git diff --exit-code HEAD",
            "git ls-files --others --exclude-standard",
        ):
            self.assertIn(expected, smoke)
        required = ci["jobs"]["required"]
        self.assertEqual(set(required["needs"]), {"plan", "shared", "implementation", "smoke"})
        self.assertEqual(required["if"], "always()")
        run = next(step for step in required["steps"] if "run" in step)
        self.assertEqual(run["run"], "python -m benchmark.ci require-success")
        self.assertEqual(
            run["env"],
            {
                "PLAN_RESULT": "${{ needs.plan.result }}",
                "SHARED_RESULT": "${{ needs.shared.result }}",
                "IMPLEMENTATION_RESULT": "${{ needs.implementation.result }}",
                "SMOKE_RESULT": "${{ needs.smoke.result }}",
            },
        )

    def test_ci_support_matrix_and_aggregate_are_fail_closed(self):
        from benchmark import ci as ci_support
        from benchmark import registry

        current = json.loads((ROOT / "benchmark/implementations.json").read_text())
        self.assertEqual(
            ci_support.matrix_payload(),
            {
                "include": [
                    {
                        "implementation": spec["id"],
                        "toolchain": {
                            "Go": "go",
                            "Rust": "rust",
                            "Node.js": "node",
                            "Python": "python",
                            "Java": "java",
                        }[spec["language"]],
                    }
                    for spec in current["implementations"]
                ]
            },
        )
        extended = extended_registry()
        with patch.object(registry, "REGISTRY", extended):
            # Synthetic display languages are not declared CI toolchains.
            with self.assertRaisesRegex(RuntimeError, "unsupported CI language"):
                ci_support.matrix_payload()
        valid = {
            "plan": "success",
            "shared": "success",
            "implementation": "success",
            "smoke": "success",
        }
        ci_support.require_success(valid)
        for key in valid:
            for bad in ("failure", "cancelled", "skipped", "", "success "):
                results = dict(valid)
                results[key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaises(RuntimeError):
                    ci_support.require_success(results)
        with self.assertRaises(RuntimeError):
            ci_support.require_success({**valid, "extra": "success"})

    def test_registry_targets_preserve_every_acceptance_and_failure_gate(self):
        path = ROOT / "benchmark/implementations.json"
        self.assertTrue(path.is_file(), "registry is required for CI gate coverage")
        registry = json.loads(path.read_text())
        commands = subprocess.run(
            ["make", "-n", "test-implementations"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(
            {spec["acceptance_test"] for spec in registry["implementations"]},
            {
                path.relative_to(ROOT).as_posix()
                for path in (ROOT / "tests").glob("test_*_service.py")
            },
        )
        self.assertEqual(
            {
                spec["failure_test"]
                for spec in registry["implementations"]
                if spec["failure_test"] is not None
            },
            {
                path.relative_to(ROOT).as_posix()
                for path in (ROOT / "tests").glob("test_*_acceptance.py")
            },
        )
        previous = -1
        for spec in registry["implementations"]:
            position = commands.index(spec["acceptance_test"])
            self.assertGreater(position, previous, "local acceptance checks must remain sequential")
            previous = position
            if spec["failure_test"] is not None:
                self.assertIn(Path(spec["failure_test"]).name, commands)
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        self.assertEqual(
            set(compose["services"]) - {"postgres"},
            {spec["id"] for spec in registry["implementations"]},
        )
        for spec in registry["implementations"]:
            build = compose["services"][spec["id"]]["build"]
            context = build["context"] if isinstance(build, dict) else build
            self.assertEqual(context.removeprefix("./"), spec["source_path"])

    def test_official_workflow_is_manual_only_on_the_trusted_default_ref(self):
        workflow = load("benchmark.yml")
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow.get("on", {})), {"workflow_dispatch"})
        self.assertIn(workflow["on"]["workflow_dispatch"], ("", {}))
        self.assertEqual(workflow["concurrency"]["cancel-in-progress"], "false")
        self.assertEqual(set(workflow["jobs"]), {"measure", "publish", "pages"})
        for job in workflow["jobs"].values():
            self.assertIn("github.event.repository.default_branch", job["if"])
            self.assertIn("github.ref", job["if"])
            self.assertIn("tappe9/simple-api-benchmark", job["if"])
            if "uses" in job:
                self.assertEqual(job["uses"], "./.github/workflows/pages-deploy.yml")
                continue
            checkout = next(
                s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")
            )
            self.assertEqual(checkout["with"]["ref"], "${{ github.sha }}")

    def test_official_jobs_require_dispatch_and_preserve_success_guards(self):
        workflow = load("benchmark.yml")
        trust = (
            "github.repository == 'tappe9/simple-api-benchmark' && "
            "github.ref == format('refs/heads/{0}', github.event.repository.default_branch) && "
            "github.event_name == 'workflow_dispatch'"
        )
        # Compare the actual YAML conditions, not a substitute expression evaluator.
        # Extra OR/always clauses or a schedule path must not widen authorization.
        for name, upstream in (("measure", None), ("publish", "measure"), ("pages", "publish")):
            job = workflow["jobs"][name]
            expected = (
                trust if upstream is None else f"needs.{upstream}.result == 'success' && {trust}"
            )
            with self.subTest(job=name):
                self.assertEqual(" ".join(job["if"].split()), expected)

    def test_manual_benchmark_policy_is_linked_and_distinguishes_publication(self):
        guide = (ROOT / "docs/AUTOMATION.md").read_text()
        self.assertIn("## When to request an official benchmark", guide)
        self.assertIn(
            "gh workflow run benchmark.yml --repo tappe9/simple-api-benchmark --ref main", guide
        )
        self.assertIn("not a measurement-only operation", guide)
        self.assertIn("not automatic triggers", guide)
        self.assertIn("historical", guide.lower())
        for document in ("README.md", "README.ja.md", "CONTRIBUTING.md", "ARCHITECTURE.md"):
            with self.subTest(document=document):
                self.assertIn(
                    "docs/AUTOMATION.md#when-to-request-an-official-benchmark",
                    (ROOT / document).read_text(),
                )

    def test_measurement_is_one_read_only_job_using_existing_runner(self):
        workflow = load("benchmark.yml")
        self.assertIn("measure", workflow.get("jobs", {}))
        job = workflow["jobs"]["measure"]
        self.assertNotIn("strategy", job)
        self.assertEqual(job.get("permissions", {"contents": "read"}), {"contents": "read"})
        steps = job["steps"]
        self.assertEqual(sum("python -m benchmark.official" in s.get("run", "") for s in steps), 1)
        content = str(job)
        self.assertNotIn("secrets.", content)
        self.assertNotIn("-z 30s", content)
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["path"], ".cache/official/")
        self.assertEqual(upload["with"]["include-hidden-files"], "true")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")

    def test_only_successful_same_run_artifact_reaches_write_job(self):
        workflow = load("benchmark.yml")
        self.assertIn("publish", workflow.get("jobs", {}))
        job = workflow["jobs"]["publish"]
        self.assertEqual(job["needs"], "measure")
        self.assertIn("needs.measure.result == 'success'", job["if"])
        self.assertEqual(job["permissions"], {"contents": "write"})
        download = next(
            s for s in job["steps"] if s.get("uses", "").startswith("actions/download-artifact@")
        )
        self.assertEqual(set(download["with"]), {"name", "path"})
        upload = next(
            s
            for s in workflow["jobs"]["measure"]["steps"]
            if s.get("uses", "").startswith("actions/upload-artifact@")
        )
        self.assertEqual(upload["with"]["name"], download["with"]["name"])
        self.assertIn("github.run_id", download["with"]["name"])
        self.assertIn("github.run_attempt", download["with"]["name"])
        final = job["steps"][-1]
        self.assertEqual(final["run"], "python -m benchmark.publish")
        self.assertEqual(final["env"], {"GH_TOKEN": "${{ github.token }}"})
        for step in job["steps"][:-1]:
            self.assertNotIn("GH_TOKEN", str(step))
        self.assertNotRegex(str(job), re.compile(r"make (test|benchmark)|docker (build|run)|npm "))

    def test_pages_deploys_only_after_trusted_main_validation(self):
        workflow = load("pages.yml")
        self.assertEqual(set(workflow.get("on", {})), {"workflow_run", "workflow_dispatch"})
        self.assertEqual(set(workflow["on"]["workflow_run"]["workflows"]), {"CI"})
        self.assertEqual(workflow["on"]["workflow_run"]["types"], ["completed"])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow["jobs"]), {"deploy"})
        self.assertEqual(workflow["jobs"]["deploy"]["uses"], "./.github/workflows/pages-deploy.yml")
        common = load("pages-deploy.yml")
        build = common["jobs"]["build"]
        self.assertEqual(build.get("permissions", {"contents": "read"}), {"contents": "read"})
        self.assertIn("python -m benchmark.pages_handoff build", str(build))
        upload = next(
            step
            for step in build["steps"]
            if step.get("uses", "").startswith("actions/upload-pages-artifact@")
        )
        self.assertEqual(upload["with"]["path"], ".cache/pages-source/.cache/site")
        deploy = common["jobs"]["deploy"]
        self.assertEqual(deploy["needs"], "build")
        self.assertEqual(
            deploy["permissions"], {"contents": "read", "pages": "write", "id-token": "write"}
        )
        self.assertEqual(deploy["environment"]["name"], "github-pages")
        self.assertTrue(
            any(
                step.get("uses", "").startswith("actions/deploy-pages@") for step in deploy["steps"]
            )
        )
        content = (ROOT / ".github/workflows/pages.yml").read_text()
        for forbidden in ("pull_request:", "pull_request_target", "secrets."):
            self.assertNotIn(forbidden, content)

    def test_pages_paths_cannot_create_releases_or_write_repository_contents(self):
        for filename in ("pages.yml", "pages-deploy.yml"):
            with self.subTest(workflow=filename):
                workflow = load(filename)
                self.assertEqual(workflow["permissions"], {"contents": "read"})
                for job in workflow["jobs"].values():
                    permissions = job.get("permissions", workflow["permissions"])
                    self.assertEqual(permissions.get("contents"), "read")
                    self.assertLessEqual(set(permissions), {"contents", "pages", "id-token"})
                    self.assertNotIn("secrets", job)
                text = (ROOT / ".github/workflows" / filename).read_text()
                for forbidden in ("gh release", "v0.1.0", "GH_TOKEN", "contents: write"):
                    self.assertNotIn(forbidden, text)

    def test_release_guidance_is_linked_separately_from_pages(self):
        guide = ROOT / "docs/RELEASING.md"
        self.assertTrue(guide.is_file(), "explicit maintainer release guide is required")
        for name in ("README.md", "README.ja.md", "CONTRIBUTING.md", "ARCHITECTURE.md"):
            with self.subTest(document=name):
                self.assertIn("docs/RELEASING.md", (ROOT / name).read_text())
        automation = (ROOT / "docs/AUTOMATION.md").read_text()
        self.assertIn("[release procedure](RELEASING.md)", automation)
        self.assertIn("## GitHub Pages\n", automation)
        # Preserve incoming links from published discussions and historical docs.
        self.assertIn('<a id="github-pages-and-v010-release"></a>', automation)

    def test_architecture_inventory_includes_current_implementations_and_pages_paths(self):
        architecture = (ROOT / "ARCHITECTURE.md").read_text()
        layout = architecture.split("## Repository layout", 1)[1].split("```", 2)[1]
        registry = json.loads((ROOT / "benchmark/implementations.json").read_text())
        for spec in registry["implementations"]:
            self.assertIn(Path(spec["source_path"]).name + "/", layout)
        for name in ("pages-deploy.yml", "pages_handoff.py", "RELEASING.md"):
            self.assertIn(name, layout)
        self.assertNotIn(
            "Axum is registered for acceptance and shared contracts but is not", architecture
        )

    def test_release_runbook_uses_explicit_tag_and_draft_with_valid_shell_syntax(self):
        guide = ROOT / "docs/RELEASING.md"
        self.assertTrue(guide.is_file(), "explicit maintainer release guide is required")
        text = guide.read_text()
        for required in ("RELEASE_SHA", "RELEASE_TAG", "--verify-tag", "--draft", "make test"):
            self.assertIn(required, text)
        for forbidden in ("gh release create v0.1.0", "git push --force", "git tag -f"):
            self.assertNotIn(forbidden, text)
        snippets = re.findall(r"```bash\n(.*?)\n```", text, flags=re.DOTALL)
        self.assertTrue(snippets, "release commands must be documented")
        for snippet in snippets:
            subprocess.run(["bash", "-n"], input=snippet, text=True, check=True)


class ReusablePagesWorkflowTests(unittest.TestCase):
    def test_official_publication_calls_same_revision_reusable_workflow_after_success(self):
        workflow = load("benchmark.yml")
        self.assertIn("pages", workflow["jobs"], "publish must have a direct dependent Pages call")
        call = workflow["jobs"]["pages"]
        self.assertEqual(call["needs"], "publish")
        self.assertIn("needs.publish.result == 'success'", call["if"])
        self.assertEqual(call["uses"], "./.github/workflows/pages-deploy.yml")
        self.assertEqual(
            call["with"],
            {
                "caller": "official",
                "target_sha": "${{ needs.publish.outputs.publication_sha }}",
                "source_sha": "${{ needs.publish.outputs.source_sha }}",
                "producer_run_id": "${{ needs.publish.outputs.producer_run_id }}",
                "producer_run_attempt": "${{ needs.publish.outputs.producer_run_attempt }}",
                "producer_result": "${{ needs.publish.result }}",
            },
        )
        producer = workflow["jobs"]["publish"]
        self.assertEqual(producer["steps"][-1]["id"], "publication")
        self.assertEqual(
            producer["outputs"],
            {
                name: "${{ steps.publication.outputs." + name + " }}"
                for name in (
                    "publication_sha",
                    "source_sha",
                    "producer_run_id",
                    "producer_run_attempt",
                )
            },
        )

    def test_ci_and_recovery_use_same_reusable_workflow_without_double_official_route(self):
        pages = load("pages.yml")
        self.assertEqual(pages["on"]["workflow_run"]["workflows"], ["CI"])
        self.assertEqual(set(pages["jobs"]), {"deploy"})
        call = pages["jobs"]["deploy"]
        self.assertEqual(call["uses"], "./.github/workflows/pages-deploy.yml")
        self.assertEqual(call["with"], {"caller": "pages", "target_sha": "${{ github.sha }}"})
        self.assertNotIn("Official benchmark", call["if"])
        self.assertNotIn("concurrency", pages)
        self.assertNotIn("concurrency", call)

    def test_reusable_build_and_deploy_reduce_permissions_and_recheck_freshness(self):
        workflow = load("pages-deploy.yml")
        self.assertEqual(set(workflow.get("on", {})), {"workflow_call"})
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow["jobs"]), {"build", "deploy"})
        for filename in ("benchmark.yml", "pages.yml"):
            caller = load(filename)["jobs"]["pages" if filename == "benchmark.yml" else "deploy"]
            self.assertEqual(
                caller["permissions"], {"contents": "read", "pages": "write", "id-token": "write"}
            )
            self.assertNotIn("secrets", caller)
        build = workflow["jobs"]["build"]
        self.assertEqual(build["permissions"], {"contents": "read"})
        self.assertNotIn("concurrency", build)
        self.assertEqual(
            build["outputs"], {"artifact_name": "${{ steps.build.outputs.artifact_name }}"}
        )
        for name, job in workflow["jobs"].items():
            checkout = next(
                s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")
            )
            self.assertEqual(
                checkout["with"]["ref"],
                "${{ github.sha }}",
                "execute only the trusted caller revision",
            )
            self.assertEqual(checkout["with"]["persist-credentials"], "false")
            self.assertIn("PAGES_TARGET_SHA", job["env"])
            self.assertFalse(any(key.startswith("GITHUB_") for key in job["env"]))
        deploy = workflow["jobs"]["deploy"]
        self.assertEqual(deploy["needs"], "build")
        self.assertEqual(
            deploy["permissions"], {"contents": "read", "pages": "write", "id-token": "write"}
        )
        self.assertEqual(deploy["concurrency"], {"group": "pages", "cancel-in-progress": "false"})
        self.assertEqual(deploy["steps"][-2]["run"], "python -m benchmark.pages_handoff verify")
        self.assertTrue(deploy["steps"][-1]["uses"].startswith("actions/deploy-pages@"))
        self.assertEqual(
            deploy["steps"][-1]["with"]["artifact_name"], "${{ needs.build.outputs.artifact_name }}"
        )
        upload = next(
            s
            for s in build["steps"]
            if s.get("uses", "").startswith("actions/upload-pages-artifact@")
        )
        self.assertEqual(
            upload["with"],
            {
                "path": ".cache/pages-source/.cache/site",
                "name": "${{ steps.build.outputs.artifact_name }}",
            },
        )
        for forbidden in (
            "actions: write",
            "secrets.",
            "release create",
            "benchmark.official",
            "benchmark.publish",
        ):
            self.assertNotIn(forbidden, str(workflow))


if __name__ == "__main__":
    unittest.main()
