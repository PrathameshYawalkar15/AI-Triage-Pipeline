# Billing Service — VAT & Rounding Invariants

## Rule INV-TAX-02
Line-item tax amounts MUST be rounded half-up to 2 decimal places (`0.01`) per line before summing into the invoice total.

## Triage Guidance
- **Symptom:** `AssertionError` comparing `calculate_invoice_total(...)` against expected ledger totals on multi-item invoices.
- **Root Cause:** If `src/billing/tax_calculator.py` was modified in the current commit, classify as `product_regression` with `block_release` until per-line rounding is restored.
