# CI Runner Secrets & Environment Drift

## Required Integration Secrets
All `test_stripe_sync` tests require `STRIPE_SANDBOX_WEBHOOK_SECRET` injected via the CI runner environment.

## Triage Guidance
- **Symptom:** Multiple tests fail immediately in `tests/conftest.py` with `KeyError: 'STRIPE_SANDBOX_WEBHOOK_SECRET'`.
- **Root Cause:** Usually triggered by switching runner pools or ephemeral runner images in `.github/workflows/ci.yml` that lack the secret group mapping. Classify as `environment_or_infra` with `hold_with_mitigation`.
