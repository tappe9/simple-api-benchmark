"""Read the Java candidate's committed versions without running a toolchain."""

import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree

from .results import BenchmarkFailure, require

JAVA_VERSION = r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?\+[0-9]+"
WRAPPER_SHA256 = "7a9ce74cff467ca1bf60a4fcd9f05185acceda4d0f382434d393e17864262c5d"
DEPENDENCY_FILES = (
    "gradlew",
    "gradlew.bat",
    "gradle/wrapper/gradle-wrapper.jar",
    "gradle/wrapper/gradle-wrapper.properties",
    "gradle.lockfile",
    "gradle/verification-metadata.xml",
)


def pinned_versions(root: Path) -> dict[str, str]:
    def read(name):
        path = root / name
        require(path.is_file() and not path.is_symlink(), "missing Java version file: " + name)
        return path.read_text(encoding="utf-8")

    def unique(pattern, text):
        values = re.findall(pattern, text, re.MULTILINE)
        require(len(values) == 1, "ambiguous or missing locked Java version")
        return values[0]

    java = read(".java-version").strip()
    require(re.fullmatch(JAVA_VERSION, java) is not None, "Java must include a fixed build number")
    lock = read("gradle.lockfile")
    coordinates = {}
    for line in lock.splitlines():
        if not line or line.startswith("#") or line.startswith("empty="):
            continue
        found = re.fullmatch(r"([^:=]+):([^:=]+):([^=]+)=([^=]+)", line)
        require(found is not None, "invalid Gradle dependency lock entry")
        coordinate = found[1] + ":" + found[2]
        require(coordinate not in coordinates, "duplicate Gradle dependency lock entry")
        require(
            re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", found[3]) is not None,
            "dependency locks must contain exact release versions",
        )
        coordinates[coordinate] = (found[3], set(found[4].split(",")))

    def runtime(coordinate):
        require(coordinate in coordinates, "missing locked Java runtime: " + coordinate)
        version, configurations = coordinates[coordinate]
        require("runtimeClasspath" in configurations, "Java runtime is not locked for execution")
        return version

    boot = runtime("org.springframework.boot:spring-boot-dependencies")
    require(
        unique(
            r"org\.springframework\.boot:spring-boot-dependencies:([0-9.]+)", read("build.gradle")
        )
        == boot,
        "Spring Boot BOM and committed lock disagree",
    )
    wrapper = read("gradle/wrapper/gradle-wrapper.properties")
    gradle = unique(
        r"^distributionUrl=https\\://services\.gradle\.org/distributions/gradle-([0-9.]+)-bin\.zip$",
        wrapper,
    )
    unique(r"^distributionSha256Sum=([0-9a-f]{64})$", wrapper)
    require(
        hashlib.sha256((root / "gradle/wrapper/gradle-wrapper.jar").read_bytes()).hexdigest()
        == WRAPPER_SHA256,
        "Gradle wrapper checksum mismatch",
    )
    try:
        document = ElementTree.fromstring(read("gradle/verification-metadata.xml"))
    except ElementTree.ParseError as error:
        raise BenchmarkFailure("invalid Java dependency verification metadata") from error
    namespace = {"v": "https://schema.gradle.org/dependency-verification"}
    require(
        document.findtext("v:configuration/v:verify-metadata", namespaces=namespace) == "true",
        "Gradle metadata verification must remain enabled",
    )
    require(
        document.find("v:configuration/v:trusted-artifacts", namespace) is None,
        "Java dependency verification must not trust wildcard artifacts",
    )
    artifacts = document.findall("v:components/v:component/v:artifact", namespace)
    require(bool(artifacts), "Java dependency verification must not be empty")
    for artifact in artifacts:
        checksums = artifact.findall("v:sha256", namespace)
        require(
            bool(checksums)
            and all(re.fullmatch(r"[0-9a-f]{64}", value.get("value", "")) for value in checksums),
            "every Java dependency artifact needs a SHA-256 checksum",
        )
    return {
        "java": java,
        "spring-boot": boot,
        "tomcat": runtime("org.apache.tomcat.embed:tomcat-embed-core"),
        "postgresql": runtime("org.postgresql:postgresql"),
        "hikaricp": runtime("com.zaxxer:HikariCP"),
        "jackson": runtime("tools.jackson.core:jackson-databind"),
        "gradle": gradle,
    }
