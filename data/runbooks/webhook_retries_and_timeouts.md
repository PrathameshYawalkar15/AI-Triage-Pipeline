# Webhook Sandbox — Intermittent Timeouts

## Known Flaky Behavior
`sandbox-webhook.internal:8080` occasionally experiences cold-start latency spikes exceeding 2.0s during shared CI runs.

## Triage Guidance
- **Symptom:** `requests.exceptions.ReadTimeout` on `test_webhook_delivery_retry` with no changes in `src/billing/webhooks.py`.
- **Root Cause:** Classify as `flaky_test` with `safe_to_proceed` (or re-run once to confirm) when the git diff only touches docs or unrelated modules.
