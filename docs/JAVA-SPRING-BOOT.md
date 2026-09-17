# Java / Spring Boot

## Registration is not official measurement

`java-spring-boot` is the ninth registered implementation. CI builds it and checks
it against the same API contract as the other implementations. It is **not** a
member of `eight-stack-v1` or frozen `four-stack-v1`. Neither historical data nor
the current result receives synthetic Java values. There is no official Java
performance result from adding or testing this implementation.

## Fixed build inputs

| Component | Version |
| --- | --- |
| Temurin JDK and production JRE | `25.0.4.1+1` |
| Spring Boot | `4.1.1` |
| Tomcat | `11.0.24` |
| PostgreSQL JDBC driver | `42.7.13` |
| HikariCP | `7.0.2` |
| Jackson databind | `3.1.5` |
| Gradle Wrapper | `9.7.1` |

`.java-version` fixes the complete runtime build, including the build number.
The Gradle build rejects a different executing JDK; automatic toolchain downloads
are disabled. The committed `gradle.lockfile` fixes runtime and test dependency
configurations under strict locking. `gradle/verification-metadata.xml` verifies
dependency artifacts and metadata with SHA-256. The Wrapper JAR and distribution
also have fixed checksums. Validation does not rewrite this evidence.

Both Temurin OS bases are fixed by OCI index digest. Their bundled JDK predates
the selected hotfix, so the build replaces it with exact checksum-verified JDK
and JRE archives. Architecture-specific scratch stages use BuildKit's
`ADD --checksum`; only the selected `amd64` or `arm64` download stage is needed.
There is no floating package installation or requirement for curl in the image.
The final image copies the verified JRE and runtime library directory, not test
libraries, a build daemon, development tools or an application launcher shell.

The Dockerfile provides x86-64 and ARM64 archive paths. The required GitHub CI
runs real-container acceptance on Linux x86-64. An ARM64 path and verified
archive checksum are not a claim of executed ARM64 acceptance.

## Runtime behavior

Spring MVC and embedded Tomcat run in one JVM process on port 8080 using
HTTP/1.1. JVM and servlet implementation threads are not additional server
processes; the common container limit remains 1 CPU / 512 MiB. Virtual threads,
WebFlux, ORM, native-image compilation and special result serializers are not
used. The JVM sets `MaxRAMPercentage=60.0` to leave headroom for non-heap memory.

The application reads `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`,
`DATABASE_USER` and `DATABASE_PASSWORD`. Address and port validation prevents
connection-URL parameter injection. Credentials are supplied separately to the
pool and redacted from the settings object's string representation. Startup
executes `SELECT 1`; invalid settings, authentication failure and unreachable DB
must terminate within a finite deadline without exposing credentials or SQL.

HikariCP has `maximumPoolSize=10` and `minimumIdle=0`, finite acquisition and
validation timeouts, and the PostgreSQL session application name
`simple-api-java`. Every `/db/{id}` request executes a prepared statement using
the parsed signed 64-bit ID. Connections, statements and result sets are closed
with try-with-resources. Missing rows return 404, malformed/out-of-range IDs 400,
and SQL failures only `{"error":"internal server error"}` with status 500.
Ordinary Java records are serialized by the framework, including exact numeric
BIGINT IDs beyond JavaScript's safe-integer range. Every `/cpu` request computes
Fibonacci(30) by direct recursion, without caching or precomputation.

The image runs as `10001:10001`. Compose retains the common dropped capabilities,
no-new-privileges, private database network, loopback-only host port and disabled
restart policy. The health command is a separate small JVM HTTP probe with a
small heap and bounded response; it never starts Spring or queries the DB.
It is not a measurement process. The existing external-readiness measurement
policy is unchanged. SIGTERM stops HTTP gracefully and closes the pool.

## Development and verification

On a POSIX host, install the exact Temurin JDK above, Python 3.10+, Make and Docker
Compose v2 with BuildKit and `up --wait` support. No global Gradle is required.
Do not run competing API services on the shared local port 8080.

```bash
# Native tests and production distribution, without Docker.
(cd apps/java-spring-boot && ./gradlew --no-daemon test installDist)

# Strict host build plus real PostgreSQL/container acceptance.
make test-java-spring-boot

# Shared HTTP contract through Docker; no host JDK is required.
make test-contract CONTRACT_IMPL=java-spring-boot

# Static metadata and failure-check regression tests, without Java or Docker.
python -m unittest discover -s tests -p 'test_benchmark_java*.py'
python -m unittest discover -s tests -p 'test_java_spring_boot_acceptance.py'
```

Native compilation enables all javac lint warnings and treats them as errors.
The native suite covers normal JSON/health/CPU behavior, repeated DB reads,
sanitized failures, BIGINT boundaries, invalid input and settings/health checks.
Real-container acceptance additionally proves that SQL row changes affect the
response, checks the observed pool bound under concurrent requests, validates
resource/process/network identities, exercises DB failures, and verifies finite
failed startup and SIGTERM cleanup. Test helpers reject incomplete or misleading
failure evidence. Cleanup touches only the acceptance run's own Compose project.
These are correctness checks, not performance measurements.

The CI matrix derives `java` from the registry language. Only its Java entry
installs the pinned JDK. Other language acceptance jobs guard Java executables
alongside their other unrelated host toolchains. Shared version extraction reads
committed files without invoking Java or Gradle. The existing fail-closed
`required` aggregate must include the new implementation; no gate is optional.

## Updating dependencies or measuring Java

Treat an update as a reviewed baseline change. Verify official JDK/JRE release
assets, their published checksums and the Docker index identities; update both
supported architecture paths and the host JDK pin together. For a deliberate
Gradle or Spring update, resolve locks and verification metadata in an isolated
trusted environment, review every changed dependency and artifact checksum,
then run normal validation without lock/verification-writing options. Never
accept a missing hash, disable strict verification, trust arbitrary artifacts,
or regenerate locks merely to turn a failing gate green.

A Java-inclusive official cohort needs a separate decision and issue. Assess JVM
warm-up under the common measurement profile; do not silently extend only Java's
five-second warm-up or change existing eight-stack results. Any justified real
official run, automatic audited publication and Pages update still require
explicit authorization. Publication/protection redesign and Issue #59's live
producer-to-Pages verification remain separate work.
