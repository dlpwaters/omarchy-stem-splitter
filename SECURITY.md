# Security policy

## Supported version

Security fixes are applied to the latest release on the `main` branch.

## Reporting a vulnerability

Please do not include private audio, credentials, or other sensitive material in a public issue. Report a vulnerability through GitHub's private vulnerability reporting feature for this repository when available, or contact the maintainer through the address listed on the GitHub profile.

Stem Splitter performs local subprocess execution with fixed argument lists. Each processing job runs in a transient `systemd --user` service with a fixed unit name and control-group cancellation; no permanent service is installed. Reports involving path validation, unintended file access, dependency substitution, service-unit ownership, or command execution are especially useful.

The engine environment is reproducible and fail-closed: `requirements.lock` contains the complete dependency graph with accepted distribution hashes, and `build-requirements.lock` pins and hashes the PEP 517 toolchain used for `diffq`, the sole dependency without a Linux wheel. All other packages require binary wheels. The helper verifies the exact managed CPython build plus the complete installed distribution set. `models.lock.json` binds every supported model component to an HTTPS URL, exact byte size, and SHA-256; verification completes before third-party model-loading code runs.
