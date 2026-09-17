"""Immutable Java metadata and dependency-verification rejection regressions."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.java_versions import pinned_versions
from benchmark.results import BenchmarkFailure

APP = Path(__file__).resolve().parents[1] / "apps/java-spring-boot"


class JavaVersionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "java"
        shutil.copytree(APP, self.root, ignore=shutil.ignore_patterns("build", ".gradle"))

    def reject_change(self, path, old, new):
        file = self.root / path
        text = file.read_text()
        self.assertIn(old, text)
        file.write_text(text.replace(old, new))
        with self.assertRaises(BenchmarkFailure):
            pinned_versions(self.root)

    def test_valid_committed_metadata_requires_no_native_toolchain(self):
        with patch("subprocess.run", side_effect=AssertionError("native tool invoked")):
            versions = pinned_versions(self.root)
        self.assertEqual(versions["java"], "25.0.4.1+1")
        self.assertEqual(versions["spring-boot"], "4.1.1")
        self.assertEqual(versions["gradle"], "9.7.1")
        self.assertEqual(set(versions), {"java", "spring-boot", "gradle", "tomcat", "postgresql", "hikaricp", "jackson"})

    def test_java_runtime_requires_an_exact_build(self):
        self.reject_change(".java-version", "25.0.4.1+1", "25")

    def test_changed_boot_bom_cannot_silently_disagree_with_lock(self):
        self.reject_change("build.gradle", "spring-boot-dependencies:4.1.1", "spring-boot-dependencies:4.1.2")

    def test_snapshot_dependency_is_rejected(self):
        self.reject_change("gradle.lockfile", "spring-boot-dependencies:4.1.1=", "spring-boot-dependencies:4.1.1-SNAPSHOT=")

    def test_duplicate_locked_dependency_is_rejected(self):
        file = self.root / "gradle.lockfile"
        line = next(line for line in file.read_text().splitlines() if line.startswith("org.postgresql:postgresql:"))
        with file.open("a") as output:
            output.write(line + "\n")
        with self.assertRaises(BenchmarkFailure):
            pinned_versions(self.root)

    def test_wrapper_checksum_is_verified_before_metadata_is_used(self):
        (self.root / "gradle/wrapper/gradle-wrapper.jar").write_bytes(b"not the committed wrapper")
        with self.assertRaises(BenchmarkFailure):
            pinned_versions(self.root)

    def test_distribution_checksum_cannot_be_removed(self):
        self.reject_change("gradle/wrapper/gradle-wrapper.properties", "distributionSha256Sum=", "removedChecksum=")

    def test_metadata_verification_cannot_be_disabled(self):
        self.reject_change("gradle/verification-metadata.xml", "<verify-metadata>true</verify-metadata>", "<verify-metadata>false</verify-metadata>")

    def test_wildcard_artifact_trust_is_rejected(self):
        self.reject_change("gradle/verification-metadata.xml", "</configuration>", '<trusted-artifacts><trust group=".*" regex="true"/></trusted-artifacts></configuration>')


if __name__ == "__main__":
    unittest.main()
