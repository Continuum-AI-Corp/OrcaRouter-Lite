"""Shared monetary units for the budget subsystem.

`ApiKey.budget_limit_cents` is stored in cents, but every comparison against
`ApiKey.spent_microcents` and `RequestLog.cost_microcents` is done in
microcents. Two places scale that column by the same factor: the request-path
charge (`packages.auth.spend`) and the boot repair that clamps a counter to a
key's cap (`packages.db.migrate`). The constant lives here, below both layers,
so neither can drift from the other by a factor of 10_000.
"""

from __future__ import annotations

# 1 cent = 10_000 microcents; 1 USD = 1_000_000 microcents, matching the cost
# math in chat.py. Every cap_microcents value is this column times this number.
MICROCENTS_PER_CENT = 10_000
