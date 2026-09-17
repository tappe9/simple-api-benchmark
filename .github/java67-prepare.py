"""Temporary, read-only-runner preparation of explicitly scoped Java integration edits.

This script changes only the disposable checkout and exports reviewable files.
It has no credentials and does not create Git objects, commits or remote refs.
Remove it before the final PR gates.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(name, old, new):
    path = ROOT / name
    content = path.read_text()
    if content.count(old) != 1:
        raise RuntimeError(f"expected exactly one integration anchor in {name}: {old!r}")
    path.write_text(content.replace(old, new))


entry = {"id": "java-spring-boot", "language": "Java", "framework": "Spring Boot", "display_name": "Java / Spring Boot", "source_path": "apps/java-spring-boot", "version_fields": ["java", "spring-boot", "tomcat", "postgresql", "hikaricp", "jackson", "gradle"], "acceptance_test": "tests/test_java_spring_boot_service.py", "failure_test": "tests/test_java_spring_boot_acceptance.py"}
replace("benchmark/implementations.json", '\n  ],\n  "cohorts":', ',\n    ' + json.dumps(entry, separators=(",", ":")) + '\n  ],\n  "cohorts":')
replace("benchmark/environment.py", "from .install_oha import SHA256, VERSION, platform_asset\n", "from .install_oha import SHA256, VERSION, platform_asset\nfrom .java_versions import JAVA_VERSION, pinned_versions as java_pinned_versions\n")
replace("benchmark/environment.py", "    require(\n        set(versions) == set(implementation_ids()),", '    versions["java-spring-boot"] = java_pinned_versions(ROOT / implementation("java-spring-boot")["source_path"])\n    require(\n        set(versions) == set(implementation_ids()),')
replace("benchmark/environment.py", 're.fullmatch(r"\\d+\\.\\d+\\.\\d+", value)\n                for value in values.values()', 're.fullmatch(JAVA_VERSION if identifier == "java-spring-boot" and field == "java" else r"\\d+\\.\\d+\\.\\d+", value)\n                for field, value in values.items()')
replace("benchmark/environment.py", '                "apps/*/requirements.lock",', '                "apps/*/requirements.lock",\n                "apps/*/gradle.lockfile",\n                "apps/*/gradle/verification-metadata.xml",\n                "apps/*/gradle/wrapper/gradle-wrapper.properties",\n                "apps/*/gradle/wrapper/gradle-wrapper.jar",')
replace("benchmark/ci.py", '"Node.js": "node", "Python": "python"}', '"Node.js": "node", "Python": "python", "Java": "java"}')
replace("benchmark/ci.py", '    "python": (),  # Python', '    "java": ("java", "javac", "jar", "javadoc", "gradle"),\n    "python": (),  # Python')
java_service = '''
  java-spring-boot:
    <<: *api-defaults
    build:
      context: ./apps/java-spring-boot
    environment:
      <<: *database-environment
    healthcheck:
      test:
        - CMD
        - java
        - -Xmx16m
        - -XX:+UseSerialGC
        - -cp
        - /app/lib/*
        - dev.simpleapibenchmark.Healthcheck
      interval: 2s
      timeout: 3s
      retries: 30
      start_period: 5s

'''
replace("docker-compose.yml", "\nnetworks:\n", java_service + "networks:\n")
java_setup = '''      - name: Install pinned Java toolchain
        if: matrix.toolchain == 'java'
        run: |
          curl --fail --silent --show-error --location --max-time 180 'https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.4.1%2B1/OpenJDK25U-jdk_x64_linux_hotspot_25.0.4.1_1.tar.gz' -o "$RUNNER_TEMP/java.tar.gz"
          echo "dbb698396d478e7fa2b1e50f4103324b2a99b90569ee27c33f2261f9215cf41e  $RUNNER_TEMP/java.tar.gz" | sha256sum -c -
          mkdir -p "$RUNNER_TEMP/java"
          tar -xzf "$RUNNER_TEMP/java.tar.gz" --strip-components=1 -C "$RUNNER_TEMP/java"
          echo "JAVA_HOME=$RUNNER_TEMP/java" >> "$GITHUB_ENV"
          echo "$RUNNER_TEMP/java/bin" >> "$GITHUB_PATH"
'''
replace(".github/workflows/ci.yml", "      - name: Run implementation acceptance and failure gates\n", java_setup + "      - name: Run implementation acceptance and failure gates\n")
replace("tests/test_benchmark_registry.py", '                "python-flask",\n', '                "python-flask",\n                "java-spring-boot",\n')
replace("tests/test_benchmark_ci.py", '    {"implementation": "python-flask", "toolchain": "python"},\n', '    {"implementation": "python-flask", "toolchain": "python"},\n    {"implementation": "java-spring-boot", "toolchain": "java"},\n')
replace("tests/test_benchmark_ci.py", '    "python": (),\n', '    "python": (),\n    "java": ("java", "javac", "jar", "javadoc", "gradle"),\n')
replace("tests/test_benchmark_ci.py", "test_required_toolchain_and_common_harness_remain_available_for_all_eight", "test_required_toolchain_and_common_harness_remain_available_for_all_registered")
replace("tests/test_workflows.py", '        rust = next(step for step in steps if step.get("name") == "Install pinned Rust toolchain")', '''        java = next(step for step in steps if step.get("name") == "Install pinned Java toolchain")
        self.assertEqual(java["if"], "matrix.toolchain == 'java'")
        self.assertIn("sha256sum -c -", java["run"])
        self.assertIn("jdk-25.0.4.1%2B1", java["run"])
        self.assertNotIn("continue-on-error", java)
        rust = next(step for step in steps if step.get("name") == "Install pinned Rust toolchain")''')
replace("tests/test_java_spring_boot_service.py", 'ROOT = Path(__file__).resolve().parents[1]\nsys.path.insert(0, str(ROOT))', 'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))')
replace("tests/test_java_spring_boot_service.py", 'APP = ROOT / "apps/java-spring-boot"', 'ROOT = Path(__file__).resolve().parents[1]\nAPP = ROOT / "apps/java-spring-boot"')
subprocess.run([sys.executable, "-m", "benchmark.registry", "--write"], cwd=ROOT, check=True)
files = ["benchmark/environment.py", "benchmark/ci.py", "benchmark/java_versions.py", "tests/test_benchmark_registry.py", "tests/test_benchmark_ci.py", "tests/test_benchmark_java_candidate.py", "tests/test_benchmark_java_versions.py", "tests/test_workflows.py", "tests/test_java_spring_boot_service.py", "tests/test_java_spring_boot_acceptance.py"]
subprocess.run([sys.executable, "-m", "ruff", "check", "--fix", "--target-version", "py310", "--config", "apps/python-fastapi/pyproject.toml", *files], cwd=ROOT, check=True)
subprocess.run([sys.executable, "-m", "ruff", "format", "--target-version", "py310", "--config", "apps/python-fastapi/pyproject.toml", *files], cwd=ROOT, check=True)
files += ["benchmark/implementations.json", "benchmark/implementations.mk", "site/registry.mjs", "docker-compose.yml", ".github/workflows/ci.yml"]
out = ROOT / ".cache/java-development/files"
for name in files:
    target = out / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / name).read_bytes())
changes = subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT, text=True).splitlines()
if not set(changes) <= set(files):
    raise RuntimeError("preparation touched files outside its explicit allowlist")
patch = subprocess.check_output(["git", "diff", "--", *files], cwd=ROOT)
(ROOT / ".cache/java-development/change.patch").write_bytes(patch)
print(patch.decode())
