# Contributing

Issues and focused pull requests are welcome.

Before submitting a change:

1. Keep processing local and avoid adding accounts, telemetry, or permanent background services.
2. Do not add automatic system-package installation or privilege escalation.
3. Pin new Python dependencies and document every persistent path or network endpoint.
4. Run `./scripts/validate.sh`.
5. Test Best and Fast removal plus full separation when changing the engine wrapper.
6. Confirm an active job survives closing the panel and restarting Omarchy Shell, then verify cancellation leaves no worker or published partial output.

Do not commit model weights, generated stems, private audio, virtual environments, or credentials.
