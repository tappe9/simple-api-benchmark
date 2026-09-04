# Security Policy

## Supported versions

The project is currently preparing v0.1. Until the first release, security fixes are applied only to the latest commit on `main`.

After releases begin, this table will list supported versions.

| Version | Supported |
|---|---|
| `main` | Yes |
| Unreleased snapshots and forks | No guarantee |

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability reporting or open a private security advisory from the repository's **Security** tab. Include:

- the affected file or workflow;
- the impact;
- steps to reproduce;
- any suggested mitigation;
- whether the issue has been disclosed elsewhere.

If private reporting is unavailable, contact the maintainer through the GitHub profile without including exploit details in a public thread.

## Security-sensitive areas

This repository builds and runs containerized code from multiple ecosystems. Important risk areas include:

- Dockerfiles and container entry points;
- GitHub Actions permissions;
- dependency installation scripts;
- downloaded benchmark tools;
- result publishing;
- shell command construction;
- PostgreSQL credentials used by local test containers.

## Contributor safety

Do not run untrusted pull request branches on a machine containing production credentials, personal secrets, or access to sensitive networks.

Pull request workflows must:

- use the minimum required permissions;
- avoid repository or deployment write credentials;
- avoid persistent self-hosted runners unless they are isolated;
- avoid publishing official results.

Only trusted code from the default branch may update published benchmark results.

## Benchmark data

Benchmark results must not include secrets, access tokens, private hostnames, or personally identifiable information. Environment metadata should be limited to values needed to understand the test conditions.
