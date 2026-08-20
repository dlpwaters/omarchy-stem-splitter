# Contributing

Issues and focused pull requests are welcome.

Before submitting a change:

1. Keep processing local and avoid adding accounts, telemetry, or background services.
2. Do not add automatic system-package installation or privilege escalation.
3. Pin new Python dependencies and document every persistent path or network endpoint.
4. Run `./scripts/validate.sh`.
5. Test removal and full separation in FLAC, WAV, and MP4 when changing the engine wrapper.

Do not commit model weights, generated stems, private audio, virtual environments, or credentials.
