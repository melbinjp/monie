# Complete Institutionalisation Report
Date: 2026-04-13
Project: Monie Trading Bot

## 1) Current State (After This Hardening Pass)
The codebase has moved from research-grade with critical live-risk gaps toward a safer pre-production posture.

Status snapshot:
- Live-readiness: Improved, but not yet institutional-grade production-ready.
- Token safety: Live token should still be withheld until remaining blockers are closed.
- Runtime stability: Improved for event-symbol consistency and strategy fill handling.
- Control-plane security: Improved for Telegram command authorization.
- Execution auditability: Improved with OMS-to-broker order-tag continuity.
- Risk accounting: Improved with startup exposure reconciliation and sell-entry-aware checks.

## 2) What Was Changed in This Pass

### A. Symbol Canonicalization (Critical Safety Path)
Problem:
- Different symbol formats across WebSocket and REST could make strategy gates and flash-crash protections behave differently.

Changes:
- Added canonical symbol utility:
  - core/symbols.py
- WebSocket now emits canonical symbols via normalization:
  - core/brokers/upstox_websocket.py
- REST fallback poller now emits canonical symbols too:
  - core/brokers/upstox.py
- Consumers now use robust symbol checks:
  - main.py (flash-crash monitor)
  - strategies/intraday_straddle.py
  - strategies/volatility_harvester.py
  - strategies/theta_crusher.py
  - strategies/afternoon_momentum.py

Impact:
- Flash-crash monitoring and VIX gating behavior is now deterministic across WS/REST feed paths.

### B. FillEvent Runtime Bug Fix (Strategy Correctness)
Problem:
- Afternoon strategy used event.price instead of FillEvent.fill_price, causing runtime failures during real fills.

Changes:
- Corrected FillEvent field usage:
  - strategies/afternoon_momentum.py

Impact:
- Prevents fill-processing crashes and broken PnL reporting in that strategy.

### C. Telegram Command Authorization (Control Plane Security)
Problem:
- Incoming command updates did not enforce chat authorization before dispatch.

Changes:
- Added strict update authorization helper and gate in command loop:
  - telegram_handler.py
- Added missing /resume dispatch route:
  - telegram_handler.py

Impact:
- Unauthorized command attempts are rejected and logged.
- Resume command now works from menu/command path.

### D. OMS to Broker Order-Tag Continuity (Idempotency/Audit)
Problem:
- Broker adapters could regenerate tags instead of honoring OMS order_tag.

Changes:
- OMS now forwards event.order_tag to broker place_order:
  - core/oms.py
- Base broker interface updated with optional order_tag parameter:
  - core/brokers/base_broker.py
- Brokers updated to honor provided order_tag:
  - core/brokers/upstox.py
  - core/brokers/paper.py
  - core/brokers/shoonya.py

Impact:
- End-to-end order tagging is now coherent, improving dedupe intent and audit traceability.

### E. Exposure Logic Hardening
Problem:
- Exposure checks treated non-sell actions as if they increased exposure in projected calculations.
- Startup reconcile did not rebuild open exposure from broker positions.

Changes:
- Exposure and notional checks now apply correctly to SELL entries only:
  - core/risk_manager.py
- Added exposure rebuild method from broker positions:
  - core/risk_manager.py
- OMS reconciliation now rebuilds risk exposure at boot:
  - core/oms.py

Impact:
- Reduces false rejections and exposure drift after restart/recovery.

## 3) Validation Performed
- Static/editor error scan completed after changes.
- Result: no reported errors.

## 4) Residual Risks Still Open (Before Live Token)
These are still important before institutional live deployment:

1. Broker-native protective exit architecture
- Strategies still primarily rely on bot-driven synthetic exits for SL behavior.
- Add broker-native protective order handling (or equivalent hedge-first emergency controls) for short option legs.

2. Command-plane hardening depth
- Current chat-id authorization is in place, but add stricter allowlist controls (user id checks, optional command secret, audit log enrichment).

3. Position/order reconciliation depth
- Reconciliation currently rebuilds exposure and logs positions.
- Add deeper order-state recovery and idempotent restart sequencing for all active legs/orders.

4. Production ops hardening
- Deployment and key handling should be tightened (host key pinning, secrets handling, rotation policies).

5. Test coverage for hardening paths
- Add dedicated tests for symbol normalization invariants, telegram auth guard, and order_tag propagation.

## 5) Go/No-Go Recommendation
- Recommendation: NO-GO for live capital right now.
- Reason: major safety posture improved, but residual institutional blockers remain.
- Live token should be provided only after the residual risks above are closed and re-validated.

## 6) Suggested Next Hardening Sprint (High Priority)
1. Implement broker-native protective order model and emergency hedge fallback.
2. Add reconciliation integration tests simulating restart with open shorts.
3. Add command auth defense-in-depth (chat + user allowlist + optional shared secret).
4. Add CI checks for symbol canonicalization and order-tag invariants.
5. Run controlled paper soak test with forced WS drop/reconnect and stale-feed scenarios.
