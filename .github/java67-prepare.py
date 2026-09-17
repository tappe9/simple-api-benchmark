"""Temporary preparation of reviewed durable public documentation only.

This uncredentialed helper is removed before final PR gates. It never writes
plans, investigation notes, commits, refs, or benchmark results.
"""
from pathlib import Path
import hashlib,json,subprocess
r=Path(__file__).resolve().parents[1]
expected = {'README.md': {'before': '4c8d745d554bcd7ece5403892fde6268c9129ca1', 'after': '76a5ea4b0c8d0f9f60c322ab6a6a577b1b7145c4'}, 'README.ja.md': {'before': '27cedaec537919e97379d44ea2530f3a3f5ec9f6', 'after': 'f2f69ddd8bc98e928e935cb677ce3b58ee445983'}, 'CONTRIBUTING.md': {'before': 'c62d99b70cab232926ede1078b0009def3191d4b', 'after': 'a4a774be53a58e1af52e41c03fd008037f26e64e'}, 'ARCHITECTURE.md': {'before': '496383d40288ef84c50ea24c1d815b2c32a9cb4c', 'after': '78aca583561922acee0abc3d1f4d1c773d31619e'}, 'ROADMAP.md': {'before': '4ecfa6674705acd52d31a38574cb6d948902f5ca', 'after': '0472b929708f17a7f6c2dbbaaf3c707fcb2a528f'}, 'docs/IMPLEMENTATIONS.md': {'before': 'f817a58550297f2e2c17f5af017a09527fd6fd98', 'after': 'a61b40860bd80323341e853002aadbf30e4aa586'}, 'docs/AUTOMATION.md': {'before': '0b14391346c8fec7b71ddcf145cbcee625ba9be2', 'after': 'f9b07b5bd3a44e4e8330c00eff0568bc8f980943'}, 'docs/METHODOLOGY.md': {'before': '05187b6e46b72d29a048319ef5fc3ec40eedc5b3', 'after': '7f42d37388b5aa1fd97775c2c9cb4ba69595797c'}, 'docs/JAVA-SPRING-BOOT.md': {'before': None, 'after': 'cd755d3ff77900cdb630dc75beb6c5e935ce2175'}}
def blob(data):
 return hashlib.sha1(b'blob '+str(len(data)).encode('ascii')+b'\0'+data).hexdigest()
subprocess.run(['git','diff','--exit-code','HEAD'],cwd=r,check=True)
for name, hashes in expected.items():
 p=r/name
 actual=blob(p.read_bytes()) if p.is_file() and not p.is_symlink() else None
 if actual != hashes['before'] or (hashes['before'] is None and p.exists()):
  raise RuntimeError('documentation baseline mismatch: '+name)
changes={}
def replace(name, old, new):
 assert name in expected
 p=r/name;s=p.read_text();assert s.count(old)==1,(name,old[:100],s.count(old));p.write_text(s.replace(old,new));changes[name]=True
replace('README.md','contains eight API implementations','contains nine API implementations')
replace('README.md','Current `main` includes all eight CI-covered implementations, the active `eight-stack-v1` cohort with verified published results, and a Pages dashboard with history navigation.', 'Current `main` includes nine CI-covered implementations. The active `eight-stack-v1` cohort has verified published results and a Pages dashboard with history navigation. Java / Spring Boot is registered for validation but is not part of the official cohort or published results.')
replace('README.md','All eight API implementations and the shared contract suite are available:', '''## Java / Spring Boot implementation

`apps/java-spring-boot/` uses Temurin 25.0.4.1+1, Spring Boot 4.1.1,
Spring MVC/Tomcat, JDBC/HikariCP, and checksum-verified Gradle 9.7.1.
It follows the same API, single-process, 1 CPU / 512 MiB and ten-connection
limits. It is the **ninth registered implementation**, not an additional official
result. `eight-stack-v1` and all published measurements remain unchanged.

```bash
make test-java-spring-boot
make test-contract CONTRACT_IMPL=java-spring-boot
```

The acceptance target needs the exact JDK, Python 3.10+, Make and Docker Compose
v2 on a POSIX host. The container-only contract target does not need a host JDK.
See the [Java implementation guide](docs/JAVA-SPRING-BOOT.md) for build integrity,
startup/shutdown behavior, supported build paths and the unmeasured boundary.

All nine API implementations and the shared contract suite are available:''')
replace('README.md','# all eight APIs, one at a time','# all nine registered APIs, one at a time')
replace('README.ja.md','検証ルールを使う8つのAPI実装があります。','検証ルールを使う9つのAPI実装があります。')
replace('README.ja.md','現在の`main`は8実装すべてがCI対象で、有効な`eight-stack-v1`の検証済み結果を公開しています。Pagesではダッシュボードと過去の結果を閲覧できます。','現在の`main`は9実装がCI対象です。公式比較は引き続き`eight-stack-v1`の8実装で、Pagesに検証済み結果と履歴を公開しています。Java / Spring Bootは検証対象として登録済みですが、公式測定・公開結果には含まれません。')
p=r/'README.ja.md';s=p.read_text();anchor=next(line for line in s.splitlines() if '8' in line and ('共通契約' in line or '共通contract' in line or '共通のcontract' in line));print('Japanese boundary anchor:',anchor)
replace('README.ja.md',anchor,'''## Java / Spring Boot実装

`apps/java-spring-boot/`はTemurin 25.0.4.1+1、Spring Boot 4.1.1、
Spring MVC / Tomcat、JDBC / HikariCP、チェックサムを検証するGradle 9.7.1を使用します。
共通のAPI、単一プロセス、1 CPU・512 MiB、DB接続上限10を維持します。
**9番目の登録済み実装ですが、公式測定対象への追加ではありません。**
`eight-stack-v1`と公開済みの測定値は変更しません。

```bash
make test-java-spring-boot
make test-contract CONTRACT_IMPL=java-spring-boot
```

受入テストには、POSIXホスト上の固定JDK、Python 3.10以降、Make、Docker Compose v2が必要です。
コンテナのみを使う共通契約テストには、ホストのJDKは不要です。
固定依存関係、起動・終了の検証、公式測定と分ける理由は
[Java実装ガイド](docs/JAVA-SPRING-BOOT.md)を参照してください。

9実装すべてを、共通のAPI契約で検証できます。''')
p=r/'README.ja.md';s=p.read_text();lines=[x for x in s.splitlines() if x.startswith('make test-contract ')];print('Japanese contract commands',lines)
for line in lines:
 if '#' in line and '8' in line: replace('README.ja.md',line,line.replace('8','9'))
replace('CONTRIBUTING.md','### Shared contract checks','''### Java / Spring Boot checks

Install the exact Temurin JDK recorded in `apps/java-spring-boot/.java-version`
(currently `25.0.4.1+1`), plus Python 3.10+, Make and Docker Compose v2 on a POSIX
host. A global Gradle installation is not needed. Run the native checks without
Docker, or the complete production acceptance target:

```bash
(cd apps/java-spring-boot && ./gradlew --no-daemon test installDist)
make test-java-spring-boot
make test-contract CONTRACT_IMPL=java-spring-boot
```

The committed Wrapper checksum, distribution checksum, strict dependency locks
and artifact verification metadata are mandatory. Validation must not regenerate
those files or download an alternative JDK silently. The production acceptance
checks live SQL/BIGINT responses, JSON errors, pool and container limits, finite
startup failure, SIGTERM shutdown and project-scoped cleanup. See the
[Java guide](docs/JAVA-SPRING-BOOT.md) for the dependency-update procedure.
Java registration does not expand the active official cohort or authorize a run.

### Shared contract checks''')
replace('CONTRIBUTING.md','# all eight registered implementations, sequentially','# all nine registered implementations, sequentially')
replace('CONTRIBUTING.md','`node-express`, `python-fastapi`, and `python-flask`.','`node-express`, `python-fastapi`, `python-flask`, and `java-spring-boot`.')
replace('CONTRIBUTING.md','all toolchains and shared workflow/site dependencies. See the','all toolchains, including the exact Java JDK, and shared workflow/site dependencies. See the')
replace('docs/IMPLEMENTATIONS.md','The eight registered implementations, in deterministic registry order, are:\nGo / Gin, Go / Echo, Rust / Actix Web, Rust / Axum, Node.js / Fastify,\nNode.js / Express, Python / FastAPI, and Python / Flask. Registration enables','The nine registered implementations, in deterministic registry order, are:\nGo / Gin, Go / Echo, Rust / Actix Web, Rust / Axum, Node.js / Fastify,\nNode.js / Express, Python / FastAPI, Python / Flask, and Java / Spring Boot. Registration enables')
replace('docs/IMPLEMENTATIONS.md','extracts all eight\nstacks','extracts all nine\nstacks')
replace('docs/IMPLEMENTATIONS.md','### Eight-stack rollout boundary (#50)','''### Java registration boundary (#67)

`java-spring-boot` is registered with a Java-only host toolchain, real-container
acceptance and the unchanged shared contract. Its static version extractor reads
the committed JDK build, Gradle Wrapper, strict lockfile and SHA-256 verification
metadata without executing Java or Gradle. Other implementation jobs do not need
a host JDK. See [Java / Spring Boot](JAVA-SPRING-BOOT.md).

Neither cohort changes membership or order. Official metadata still contains
only the eight active implementations; Java is not filled into old reports with
zeroes or missing values. A future Java-inclusive cohort and any official run
need a separate decision, including an assessment of JVM warm-up under the common
profile. Registration and passing tests are not measured performance evidence.

### Eight-stack rollout boundary (#50)''')
replace('docs/AUTOMATION.md','Rust jobs install Rust with rustfmt/Clippy. Python implementation jobs need no\nadditional language setup.','Rust jobs install Rust with rustfmt/Clippy. Only Java jobs install the exact\nTemurin JDK using its fixed release URL and verified SHA-256; Gradle is supplied\nby the committed checksum-verified Wrapper. Python implementation jobs need no\nadditional language setup.')
replace('docs/AUTOMATION.md','unrelated host Go/Node/Rust tools','unrelated host Go/Node/Rust/Java tools')
replace('docs/METHODOLOGY.md','## When to remeasure','''Current `main` uses the versioned `eight-stack-v1` cohort for official measurement;
its membership is listed in the [registry guide](IMPLEMENTATIONS.md). Java /
Spring Boot is the ninth registered implementation for acceptance and contract
checks, but is outside both existing official cohorts. Its single JVM uses the
same resource and pool limits, normal JSON serialization, JDBC and direct
recursive Fibonacci. There is no Java result or performance claim from these
correctness tests. Before any future cohort change, assess JVM warm-up under the
common profile rather than silently extending Java's five-second warm-up alone.
See the [Java implementation guide](JAVA-SPRING-BOOT.md).

## When to remeasure''')
replace('docs/METHODOLOGY.md','All eight registered implementations can be checked','All nine registered implementations can be checked')
replace('ARCHITECTURE.md','GitHub Actions should measure every backend in the same job.','GitHub Actions should measure every active cohort member sequentially in the same job.')
replace('ARCHITECTURE.md','    R --> A4[Python / FastAPI and Flask]','    R --> A4[Python / FastAPI and Flask]\n    M -. acceptance and contracts only .-> A5[Java / Spring Boot]\n    A5 --> P')
replace('ARCHITECTURE.md','### PostgreSQL','''#### Java / Spring Boot

`apps/java-spring-boot/` uses a single Temurin 25.0.4.1+1 JVM with Spring Boot
4.1.1, Spring MVC/Tomcat, ordinary record serialization and JDBC/HikariCP.
`DatabaseSettings` validates the shared five `DATABASE_*` values without putting
credentials into the JDBC URL. `DatabaseConfiguration` bounds the pool at ten
connections and validates `SELECT 1` before startup completes. Repository reads
use a prepared statement and try-with-resources; signed BIGINT IDs remain numeric
JSON, missing rows return 404, and SQL failures return a sanitized 500. Each CPU
request calculates Fibonacci(30) by direct recursion.

The production image is non-root, inherits the common resource/isolation limits,
contains only runtime libraries and shuts down HTTP and the pool on SIGTERM.
Architecture-selected BuildKit stages checksum-verify the exact JDK/JRE archives;
both OS base images are digest pinned. Gradle Wrapper and dependency verification
are strict. The small standalone health probe does not start Spring or connect
to the database. No ORM, WebFlux, native image, virtual threads or additional
server processes are enabled. Java is CI-covered but not an official cohort
member; see [the Java guide](docs/JAVA-SPRING-BOOT.md).

### PostgreSQL''')
replace('ARCHITECTURE.md','covers all eight registered stacks','covers all nine registered stacks')
replace('ARCHITECTURE.md','│   └── python-flask/','│   ├── python-flask/\n│   └── java-spring-boot/')
replace('ARCHITECTURE.md','builds and checks all eight registered applications','builds and checks all nine registered applications')
replace('ROADMAP.md','| Versioned eight-stack cohort |','| Java / Spring Boot registration | Ninth implementation with dedicated host toolchain, checksum-verified build, real-container acceptance and shared contracts ([#67](https://github.com/tappe9/simple-api-benchmark/issues/67)). Outside the active official cohort; no Java result is published. |\n| Versioned eight-stack cohort |')
replace('ROADMAP.md','Java / Spring Boot and C# / ASP.NET Core may be evaluated one at a time. These are\ncandidates, not commitments or implemented benchmark entries. Historical-result\nnavigation is already available, not a future candidate.','C# / ASP.NET Core may be evaluated as a separate implementation candidate, not a\ncommitment. Java / Spring Boot is already registered; its inclusion in a future\nofficial cohort remains a separate decision that must assess the common warm-up\nand measurement profile. Historical-result navigation is already available.')
p=r/'docs/JAVA-SPRING-BOOT.md';assert not p.exists();p.write_text('''# Java / Spring Boot

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
''');changes[str(p.relative_to(r))]=True
for name in ('README.md','README.ja.md'):
 old=subprocess.check_output(['git','show','6e25eb07759bd6eed4de9ab9ee3d1dd35562932b:'+name],cwd=r,text=True)
 new=(r/name).read_text();start='<!-- benchmark-results:start -->';end='<!-- benchmark-results:end -->'
 assert old.split(start)[1].split(end)[0]==new.split(start)[1].split(end)[0],name
print('Updated durable docs:',json.dumps(list(changes)))

if set(changes) != set(expected):
 raise RuntimeError('unexpected public documentation manifest')
changed=set(subprocess.check_output(['git','diff','--name-only'],cwd=r,text=True).splitlines())
new=set(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=r,text=True).splitlines())
if changed | new != set(expected):
 raise RuntimeError('unexpected checkout modifications')
out=r/'.cache/java-documentation'
for name, hashes in expected.items():
 p=r/name
 if p.is_symlink() or blob(p.read_bytes()) != hashes['after']:
  raise RuntimeError('unreviewed public documentation bytes: '+name)
 target=out/'files'/name
 target.parent.mkdir(parents=True,exist_ok=True)
 target.write_bytes(p.read_bytes())
(out/'manifest.json').write_text(json.dumps(expected,indent=2)+'\n')
