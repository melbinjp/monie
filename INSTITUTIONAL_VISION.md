# Monie: Institutional Architecture Manifesto

This document serves as the foundational baseline and governing philosophy for all future development on the Monie Autonomous Trading Bot. Any code merged into this repository MUST pass strict adherence to the principles outlined below.

## 🏛️ The 4 Pillars of Institutional Trading

1. **Absolute Fault Tolerance (The Unbreakable Engine)**
   * **Rule**: Code must never assume APIs or networks are stable.
   * **Implementation**: Every external outbound request must be shielded by an exponential backoff circuit. WebSockets must auto-reconnect asynchronously. `QueueFull` exceptions, thread-drops, or Rate Limit violations must trigger failsafes, log alerts, and gracefully degrade without crashing the main Python event loop.

2. **State Integrity & Crash Recovery**
   * **Rule**: In-memory state is an illusion. The bot must survive localized server destruction.
   * **Implementation**: State must be backed by an ACID-compliant protocol (e.g., SQLite WAL mode). Upon boot, the execution core (`OMS`) must independently reconcile physical broker arrays against local databases, synthesizing recovery events (`FillEvent(SYSTEM_RECOVERY)`) across the `EventBus` to transparently rebuild strategy memory states without incurring duplicate leverage positioning.

3. **Broker Agnosticism & Normalization**
   * **Rule**: Vendor lock-in is a fatal architectural flaw.
   * **Implementation**: Strategies evaluate strictly normalized syntax (e.g., `INDIA_VIX`, `NIFTY_50`). Broker gateways (`UpstoxWebSocket`, `Shoonya`) are mandated to translate native broker string variants into this universal format *before* the EventBus ingests them. Accessing underlying Broker specific APIs outside of the abstract `base_broker.py` adapter boundary is strictly forbidden. 

4. **Self-Calibrating Dynamism**
   * **Rule**: Hardcoded thresholds for financial geometry are extreme liabilities.
   * **Implementation**: Stop losses, trailing tolerances, market spike rejections, and latency limits must adapt dynamically to surrounding market environments or physical network regimes (e.g., deriving spike violation tolerances directly from real-time dynamic VIX bounds or network Ping calculations).

## ⚡ Computational Standards (HFT Latency Guardrails)

* **Zero-Lag Event Serialization**: Tasks deployed through the `EventBus` or Orchestration loops must utilize non-blocking fire-and-forget strategies (`asyncio.create_task()`). Awaiting heavy REST limits inside hot-paths introduces structural latency drag natively breaking breakout momentum algorithms.
* **O(K) Scalar Mathematical Primacy**: Functions within sub-millisecond execution scopes (like Black Swan Guard roll calculations) are forbidden from generating array/list structures, instantiating closure functions natively per-tick, or looping `try/except RuntimeError` checks continuously. Scalar accumulation over `O(1)` or strictly bounded `O(K)` reverse iterations is explicitly enforced.
* **Zero-Downtime Hot Reloading**: Algorithmic authorization tokens mapping independent APIs must be structurally capable of hot-reloading from threaded background overlays without destroying or tearing down live quantitative positions.

---
*By engaging with this codebase, the developer affirms all modifications inherently fortify and pass the Institutional Manifest.*
