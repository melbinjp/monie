# Requirements Document

## Introduction

This feature hardens Project Monie — an event-driven, multi-strategy options trading bot for Indian NSE F&O markets — into a robust, fault-tolerant, risk-controlled system running live on AWS EC2. The enhancement targets five outcomes: (1) eliminating single points of failure, starting with the Upstox daily token refresh that today depends solely on Telegram; (2) non-stop operation through crash auto-recovery, process supervision, and state reconciliation; (3) graceful handling of broker outages, websocket drops, stale data, and resource exhaustion; (4) strict, measurable risk control; and (5) rigorous strategy validation to measure edge before risking real capital.

This document deliberately frames the system around reliability, fault tolerance, and risk control. It makes no claim of guaranteed profitability. The goal is to keep the engine running, contain losses within defined limits, and require demonstrated paper-trading edge before live capital is unlocked.

This spec targets production readiness for live capital. The paper-trading validation and observability stage is in scope and SHALL be completed before go-live, and the system SHALL comply with the SEBI retail algorithmic trading framework in force.

These requirements describe observable system behavior (the "what"). Implementation details (the "how") are deferred to the design phase.

## Glossary

- **Trading_Engine**: The complete Project Monie application process, including the EventBus, StrategyOrchestrator, OMS, RiskManager, and broker integrations.
- **Token_Manager**: The component responsible for acquiring, validating, refreshing, and persisting the Upstox access token.
- **Telegram_Channel**: The existing Telegram bot interface used for remote control and the current `/token` command.
- **OAuth_Refresh**: The automated, non-interactive Upstox authentication flow that obtains a new access token without a human pasting a token.
- **Token_HTTP_Endpoint**: A local authenticated HTTP endpoint that accepts a new Upstox access token as a fallback channel independent of Telegram.
- **Process_Supervisor**: The operating-system service manager (systemd unit `monie.service`) that launches and restarts the Trading_Engine.
- **State_Reconciler**: The component that, on startup, compares persisted internal state against live broker positions and resolves discrepancies.
- **Connection_Manager**: The component that maintains the market-data websocket connection and handles reconnection.
- **Data_Feed_Manager**: The component that supplies market quotes to strategies, including selection between primary and fallback data sources.
- **Data_Source**: A provider of market quotes (Upstox websocket, Upstox REST, or Shoonya).
- **Broker_Failover_Manager**: The component that detects broker API unavailability and applies the configured degraded-mode response.
- **Resource_Monitor**: The component that monitors EC2 disk, memory, and log growth.
- **Health_Alerter**: The component that emits operational health alerts across one or more notification channels.
- **Risk_Manager**: The existing component enforcing circuit breakers, per-order caps, exposure caps, and rate limits.
- **Black_Swan_Guard**: The existing component detecting gaps, flash crashes, velocity shocks, stale quotes, and high VIX.
- **Backtest_Engine**: The component that replays historical market data through strategies to produce performance and edge metrics.
- **Staging_Manager**: The existing 5-level firmware-lock component that gates live trading on demonstrated paper-trading performance.
- **Event_Bus**: The existing asynchronous bounded-queue message broker routing events between components.
- **Square_Off**: The act of closing all open positions by submitting offsetting orders.
- **Trading_Session**: The NSE market window on a trading day, from 09:15 to 15:30 IST.
- **Stale_Quote**: A market quote whose price has not changed for a configured duration, indicating a possible feed halt.
- **Deployment_Topology**: The defined AWS region, EC2 instance class, resource specification, recovery configuration, and time-synchronization configuration for the host that runs the Trading_Engine.
- **Instance_Monitor**: The component that verifies host placement and instance class on startup and monitors host-level compute health, including CPU-credit balance, CPU steal time, and throttling, on burstable instance families.
- **Order_Round_Trip_Latency**: The elapsed wall-clock time from generation of an entry or exit signal to receipt of the broker's order acknowledgement, measured in milliseconds.
- **Protective_Order**: A broker-persisted stop-loss or GTT_Order placed at the broker that limits or closes the loss on an open position, and that remains active at the broker independently of the Trading_Engine process, the EC2 instance, and the network connection.
- **GTT_Order**: A Good-Till-Triggered order persisted at Upstox that executes when its configured trigger price is reached and remains active without an open application connection.
- **Safe_Mode**: A degraded operating state in which the Risk_Manager rejects all new entry orders while the Trading_Engine continues to manage exits and existing Protective_Orders.
- **Liveness_Watchdog**: A monitor that verifies the Trading_Engine is actively processing work, distinguishing a responsive process from a hung process that still exists at the operating-system level.
- **Backup_Manager**: The component that creates durable, off-instance copies or snapshots of persisted state files and audit logs so that a destroyed instance can be rebuilt without losing trade and staging history.
- **AI_Advisor**: An optional, off-by-default supervisory AI component that produces advisory outputs (market-regime classification, anomaly and log triage, post-trade analysis, natural-language operator status, and pre-approved remediation suggestions) and never directly executes trading actions outside a whitelisted, risk-checked action set.
- **Secret_Store**: Secure storage for credentials — broker API keys, the Upstox access token, the Telegram token, AI provider keys, and the Token_HTTP_Endpoint shared secret — that keeps secret values out of the source repository and restricts access to the operating-system user that runs the Trading_Engine.
- **Instance_ID**: A unique identifier assigned to a single running instance of the Trading_Engine at startup, distinct from the identifier of any other instance that has run or is running.
- **Instance_Epoch**: A monotonically increasing integer fencing counter that is incremented and persisted to a durable shared record each time an instance of the Trading_Engine starts, used to order instances in time so that a higher value identifies a later instance.
- **Active_Instance_Registry**: A durable, provider-agnostic shared record holding the current leader instance's Instance_ID, Instance_Epoch, and most recent heartbeat timestamp, used to coordinate which single instance is active.
- **Instance_Lease**: A time-bounded claim to active-leader status recorded in the Active_Instance_Registry, refreshed by heartbeat and considered fresh while its heartbeat timestamp is within the configured lease time-to-live; it is a coordination lease, not an operating-system or distributed lock.
- **External_Watchdog**: A monitor that runs independently of the host running the Trading_Engine (on a different node or availability zone, or as a serverless or scheduled function) and checks the Active_Instance_Registry lease heartbeat from outside the trading host.
- **Node_Auto_Replacement**: A Deployment_Topology capability that automatically replaces a failed trading node without manual intervention, expressed provider-agnostically as an auto-scaling group of one, a managed container service, or an equivalent mechanism on any provider.
- **Audit_Trail**: A durable, tamper-evident, append-only record of every live order, where each entry captures at minimum the timestamp, symbol, side, price, quantity, broker-assigned order identifier, and Algo_Identifier, and where tamper-evidence is provided by a mechanism such as hash chaining or write-once storage that makes undetected modification of prior entries detectable.
- **Algo_Identifier**: The exchange/broker-assigned algorithmic-trading identifier required by the SEBI retail algorithmic trading framework, sourced from the configured UPSTOX_ALGO_ID and UPSTOX_ALGO_NAME values, and distinct from the internal Instance_ID and Instance_Epoch instance-epoch tag.
- **SEBI_Algo_Framework**: The Securities and Exchange Board of India circular "Safer Participation of Retail Investors in Algorithmic Trading" dated 4 February 2025, mandatory in full from 1 April 2026, which governs broker-routed retail algorithmic order flow, algo identification, registration thresholds, and API security controls.
- **Compliance_Kill_Switch**: A control that halts submission of all new orders to the broker while leaving exit and Protective_Order management for existing positions unaffected, consistent with the existing circuit breaker and Safe_Mode behavior.
- **Performance_Report**: An analyzable summary of paper-trading results, produced per strategy and in aggregate over a configurable date range, reporting net PnL, win rate, maximum drawdown, average execution latency, average slippage, and trade count.
- **Go_Live_Readiness**: An explicit, measurable review that consumes recorded paper-trading metrics together with the Staging_Manager Level 4 and Level 5 criteria to gate the transition from PAPER mode to live order routing, requiring both satisfied measurable criteria and a deliberate operator confirmation.

## Requirements

### Requirement 1: Resilient Upstox Token Acquisition

**User Story:** As the bot operator, I want the Upstox access token to be acquired and refreshed through multiple independent channels, so that the Trading_Engine can obtain a valid token even when Telegram is unavailable.

A token is considered valid when its recorded expiry timestamp is later than the current system time.

#### Acceptance Criteria

1. WHEN the Trading_Engine starts, THE Token_Manager SHALL attempt token acquisition in priority order: stored valid token, then OAuth_Refresh, then Token_HTTP_Endpoint, then Telegram_Channel, allowing at most 30 seconds per channel attempt before advancing to the next channel.
2. WHEN OAuth_Refresh completes successfully, THE Token_Manager SHALL persist the new access token to durable storage using an atomic write.
3. IF the atomic write of a newly acquired token fails, THEN THE Token_Manager SHALL retain the previously persisted token unchanged and emit an alert through the Health_Alerter.
4. WHEN a new access token is persisted, THE Token_Manager SHALL update the in-memory configuration and re-authenticate the Upstox broker session within 10 seconds and without requiring a process restart.
5. IF OAuth_Refresh fails, THEN THE Token_Manager SHALL attempt the next channel in priority order and record the failure reason in the log.
6. IF all token-acquisition channels fail, THEN THE Token_Manager SHALL leave the Trading_Engine without a valid token and emit a critical alert through the Health_Alerter.
7. IF the Token_HTTP_Endpoint receives a token-submission request that does not present the configured shared secret, THEN THE Token_HTTP_Endpoint SHALL reject the request without altering the stored token.
8. WHEN a valid token is acquired through any channel, THE Token_Manager SHALL emit a confirmation alert through the Health_Alerter within 10 seconds, identifying the channel used.

### Requirement 2: Automated Token Validation and Scheduled Refresh

**User Story:** As the bot operator, I want the token validated and refreshed on a schedule before the Trading_Session, so that the Trading_Engine is authenticated at market open without manual action.

#### Acceptance Criteria

1. WHEN a token validation check is initiated, THE Token_Manager SHALL validate the active token by performing one authenticated Upstox API call.
2. WHEN a validation API call returns a successful authenticated response within 5 seconds, THE Token_Manager SHALL classify the active token as valid; otherwise THE Token_Manager SHALL classify it as invalid.
3. WHEN the system clock reaches the daily pre-market refresh time of 09:00 IST on a trading day, THE Token_Manager SHALL attempt OAuth_Refresh and complete it before the Trading_Session begins.
4. IF token validation fails or OAuth_Refresh fails, THEN THE Token_Manager SHALL retry acquisition at fixed 5-minute intervals until a valid token is obtained or the system clock reaches 09:30 IST, whichever occurs first.
5. IF no valid token is available by 09:30 IST on a trading day, THEN THE Health_Alerter SHALL emit exactly one critical alert stating that automated trading is unavailable for the day.
6. WHILE no valid token is available, THE Risk_Manager SHALL reject submission of new live orders.

### Requirement 3: Process Supervision and Crash Auto-Recovery

**User Story:** As the bot operator, I want the Trading_Engine to restart automatically after a crash or EC2 reboot, so that the system resumes operation without manual intervention.

#### Acceptance Criteria

1. WHERE the Process_Supervisor manages the Trading_Engine, WHEN the Trading_Engine process terminates unexpectedly (exit with a non-zero exit status or any termination not initiated by an operator-issued stop command), THE Process_Supervisor SHALL restart the Trading_Engine within 30 seconds of detecting the termination.
2. WHEN the EC2 instance completes a reboot, THE Process_Supervisor SHALL start the Trading_Engine within 60 seconds of the operating system reaching its multi-user ready state and without requiring an interactive login session.
3. WHEN the Trading_Engine starts following an unexpected termination, THE Health_Alerter SHALL emit an alert indicating that a recovery restart occurred, including the timestamp of the restart and the cumulative unexpected-restart count for the current 10-minute window.
4. IF the Trading_Engine terminates unexpectedly 5 or more times within any rolling 10-minute window, THEN THE Health_Alerter SHALL emit a critical alert indicating that a crash loop has been detected.
5. IF the Trading_Engine is stopped by an operator-issued stop command or exits with a zero exit status, THEN THE Process_Supervisor SHALL NOT restart the Trading_Engine.
6. WHILE a crash loop condition (5 or more unexpected terminations within a rolling 10-minute window) is active, THE Process_Supervisor SHALL halt further automatic restart attempts until an operator-issued start command is received.

### Requirement 4: State Persistence and Reconciliation After Restart

**User Story:** As the bot operator, I want internal state reconciled against the broker after a restart, so that the Trading_Engine resumes with an accurate view of open positions and risk exposure.

#### Acceptance Criteria

1. WHEN the Trading_Engine starts, THE State_Reconciler SHALL retrieve live open positions from the active broker, retrying up to 3 times with exponential backoff, before strategies begin evaluation.
2. IF broker position retrieval fails after the configured retries, THEN THE State_Reconciler SHALL halt strategy evaluation and emit a critical alert through the Health_Alerter.
3. WHEN the State_Reconciler retrieves live broker positions, THE Risk_Manager SHALL rebuild tracked open exposure from those positions before strategies begin evaluation.
4. IF a position exists at the broker that is absent from persisted state, THEN THE State_Reconciler SHALL adopt the broker position as authoritative and emit a discrepancy alert through the Health_Alerter.
5. IF persisted state references an active position that is absent at the broker, THEN THE State_Reconciler SHALL mark that position closed in persisted state and emit a discrepancy alert through the Health_Alerter.
6. WHEN persisted state whose recorded trade date equals the current trading date is recovered on startup, THE State_Reconciler SHALL restore active leg tracking for that date.
7. IF persisted state carries a recorded trade date earlier than the current trading date, THEN THE State_Reconciler SHALL discard that day's leg tracking and initialize clean state for the current date.
8. IF the persisted state file is unreadable or corrupt, THEN THE State_Reconciler SHALL initialize clean state and emit an alert through the Health_Alerter rather than terminating the Trading_Engine.

### Requirement 5: Market-Data Websocket Reconnection

**User Story:** As the bot operator, I want the market-data websocket to reconnect automatically after a drop, so that strategies continue receiving live quotes without manual restart.

#### Acceptance Criteria

1. WHEN the market-data websocket connection drops during a Trading_Session, THE Connection_Manager SHALL attempt reconnection using exponential backoff with a delay of 1 second before the first attempt, doubling the delay after each failed attempt, and capping the delay at 60 seconds per attempt.
2. WHILE the market-data websocket remains disconnected during a Trading_Session, THE Connection_Manager SHALL continue retrying reconnection at the capped 60-second interval without an upper limit on the number of attempts until reconnection succeeds or the Trading_Session ends.
3. WHEN the websocket reconnects, THE Connection_Manager SHALL resubscribe within 5 seconds to every symbol that was in the subscribed set immediately before the disconnection.
4. IF resubscription to one or more symbols fails after the websocket reconnects, THEN THE Connection_Manager SHALL retry the failed symbol subscriptions and SHALL preserve the previously subscribed symbol set without dropping symbols.
5. WHILE the websocket is disconnected during a Trading_Session, THE Data_Feed_Manager SHALL serve quotes from the REST fallback Data_Source, refreshing each subscribed symbol at an interval of no more than 5 seconds.
6. IF the websocket remains continuously disconnected for more than 120 seconds during a Trading_Session, THEN THE Health_Alerter SHALL emit an alert that identifies the affected market-data websocket and reports the disconnection duration in seconds.

### Requirement 6: Stale Data Detection and Trading Halt

**User Story:** As the bot operator, I want trading halted when market data goes stale, so that the Trading_Engine does not act on prices that no longer reflect the market.

#### Acceptance Criteria

1. WHILE a valid quote price (a numeric value greater than 0) remains identical to its immediately preceding valid quote price for a continuous elapsed wall-clock duration of 600 seconds or more, THE Black_Swan_Guard SHALL classify the quote as a Stale_Quote.
2. WHEN a valid quote price differs from the last recorded quote price, THE Black_Swan_Guard SHALL reset the stale-detection elapsed-time counter to 0 seconds and record the new price as the last recorded quote price.
3. IF a received quote price is missing, null, or less than or equal to 0, THEN THE Black_Swan_Guard SHALL neither reset the stale-detection elapsed-time counter nor classify the quote as a Stale_Quote.
4. WHEN a Stale_Quote is detected during a Trading_Session, THE Risk_Manager SHALL reject submission of all new entry orders while leaving existing open positions unchanged.
5. WHEN a Stale_Quote is detected, THE Health_Alerter SHALL emit exactly one alert indicating a possible market-data halt, including the elapsed staleness duration in seconds.
6. WHEN a valid quote price changes after a Stale_Quote has been detected, THE Risk_Manager SHALL permit submission of new entry orders, subject to all other risk checks.

### Requirement 7: Data Source Failover

**User Story:** As the bot operator, I want the Trading_Engine to fail over to an alternate market-data source, so that a single data-provider outage does not stop quote delivery.

#### Acceptance Criteria

1. IF the primary Data_Source returns no valid quote for 60 continuous seconds during a Trading_Session, where a valid quote is a quote message with a non-null price and a timestamp not older than 5 seconds, THEN THE Data_Feed_Manager SHALL switch to the configured fallback Data_Source within 2 seconds of the 60-second threshold being reached.
2. WHEN the Data_Feed_Manager switches the active Data_Source, THE Health_Alerter SHALL emit, within 5 seconds of the switch, an alert identifying the previous Data_Source name and the current Data_Source name.
3. IF no fallback Data_Source is configured, or the configured fallback Data_Source also returns no valid quote for 60 continuous seconds, THEN THE Data_Feed_Manager SHALL retain the last active Data_Source selection and emit through the Health_Alerter an alert indicating that no available Data_Source is delivering valid quotes.
4. WHEN the primary Data_Source resumes returning valid quotes continuously for 30 seconds while the fallback Data_Source is active, THE Data_Feed_Manager SHALL switch back to the primary Data_Source.
5. WHEN the system status report is requested, THE Data_Feed_Manager SHALL include in the report the name of the currently active Data_Source.

### Requirement 8: Broker API Outage Handling

**User Story:** As the bot operator, I want broker API outages handled defensively, so that the Trading_Engine avoids unsafe actions when it cannot confirm order or position state.

#### Acceptance Criteria

1. IF a broker order-placement request fails due to an API error (HTTP-level failure, connection error, or no response within a 5-second per-attempt timeout), THEN THE Trading_Engine SHALL retry the request up to 3 additional times using exponential backoff starting at a 1-second delay and doubling each attempt, capped at 30 seconds per delay.
2. IF a broker order-placement request fails after 3 retry attempts, THEN THE Trading_Engine SHALL record the failure with the order's idempotent tag and timestamp in persistent storage without resubmitting the same order.
3. WHEN a broker order-placement request fails after 3 retry attempts, THE Trading_Engine SHALL emit an alert through the Health_Alerter identifying the failed order within 5 seconds of the final failed attempt.
4. WHILE the broker positions API is unreachable, defined as 3 or more consecutive position-query failures or no successful position query within the preceding 60 seconds, THE Risk_Manager SHALL reject submission of every new entry order and return a rejection indication to the caller.
5. WHEN the broker positions API returns a successful position query after being unreachable, THE Risk_Manager SHALL resume accepting new entry orders.
6. THE Trading_Engine SHALL attach a unique idempotent order tag, unique across all orders for the Trading_Session, to every order before submission so that retried orders carrying the same tag are deduplicated by the broker.

### Requirement 9: Disk and Resource Management

**User Story:** As the bot operator, I want disk and resource pressure managed automatically, so that long-running operation does not exhaust EC2 storage or memory.

#### Acceptance Criteria

1. THE Resource_Monitor SHALL evaluate available free disk space and current process memory usage at a configured interval not exceeding 60 seconds.
2. WHILE free disk space is below 200 MB, THE Resource_Monitor SHALL archive rotated log files to reclaim space within one monitoring interval of detection.
3. WHILE free disk space is below 200 MB, THE Resource_Monitor SHALL truncate the rotated log files that have been archived within one monitoring interval of archival.
4. WHEN free disk space falls below 100 MB, THE Health_Alerter SHALL emit a critical-severity alert reporting low disk space, including the current free-space value, within one monitoring interval of detection.
5. THE Event_Bus SHALL bound its event queue to a configured maximum size between 1 and 1,000,000 events.
6. IF an event is published while the Event_Bus queue is at its configured maximum size, THEN THE Event_Bus SHALL reject the event and increment a dropped-event counter by one.
7. WHEN the Event_Bus dropped-event counter increases during a Trading_Session, THE Health_Alerter SHALL emit an alert reporting event-queue saturation, including the current dropped-event count, within one monitoring interval of the increase.
8. WHEN process memory usage exceeds a configured threshold between 1 MB and the EC2 instance total memory, THE Health_Alerter SHALL emit a critical-severity alert reporting high memory usage, including the current memory-usage value, within one monitoring interval of detection.

### Requirement 10: Multi-Channel Health Alerting

**User Story:** As the bot operator, I want health alerts delivered through more than one channel, so that I am notified of critical conditions even when one channel is unavailable.

#### Acceptance Criteria

1. WHEN the Health_Alerter emits a critical alert, THE Health_Alerter SHALL deliver the alert through at least two independent notification channels within 5 seconds of the triggering condition.
2. IF delivery through one notification channel fails or does not confirm success within 10 seconds, THEN THE Health_Alerter SHALL attempt delivery through each remaining configured channel, retrying each failed channel up to 3 times with a delay of 5 seconds between attempts.
3. IF delivery through all configured notification channels fails after all retry attempts are exhausted, THEN THE Health_Alerter SHALL record a delivery-failure entry in the system log indicating the alert identifier and the affected channels, and SHALL preserve the undelivered alert for the next delivery cycle.
4. WHILE a Trading_Session is active, THE Health_Alerter SHALL emit a heartbeat alert at a configured interval between 30 seconds and 3600 seconds (default 300 seconds) that confirms the Trading_Engine is operating.
5. IF the operator does not receive a heartbeat alert within two consecutive configured heartbeat intervals during an active Trading_Session, THEN THE Health_Alerter SHALL classify the Trading_Engine as non-responsive and SHALL emit a critical alert through at least two independent notification channels.
6. WHEN any circuit breaker trips, THE Health_Alerter SHALL emit a critical alert that identifies the circuit breaker name and states the trigger reason.

### Requirement 11: Daily Loss Circuit Breaker

**User Story:** As the bot operator, I want a daily loss limit enforced, so that cumulative losses on any single day are contained.

#### Acceptance Criteria

1. WHEN the realized-plus-unrealized daily loss reaches or exceeds the configured daily-loss limit, THE Risk_Manager SHALL trip the daily-loss circuit breaker within 1 second of detection and record a critical log entry stating the breach.
2. WHEN the daily-loss circuit breaker trips, THE Trading_Engine SHALL Square_Off all open positions.
3. IF a Square_Off attempt triggered by the daily-loss circuit breaker fails, THEN THE Trading_Engine SHALL retry the Square_Off up to 3 times and emit an alert through the Health_Alerter if positions remain open after the final attempt.
4. WHILE the daily-loss circuit breaker is tripped, THE Risk_Manager SHALL reject every new order that is not an exit order and return a rejection reason, leaving existing open positions unchanged.
5. WHEN a new Trading_Session begins on a trading day, THE Risk_Manager SHALL reset the daily-loss circuit breaker, set the daily loss counter to zero, and set the daily trade count to zero.
6. THE Risk_Manager SHALL derive the daily-loss limit as the configured daily-loss percentage of current trading capital.
7. WHILE trading is active, THE Risk_Manager SHALL recalculate the daily loss against the daily-loss limit each time updated PnL is received.
8. IF the configured daily-loss percentage is outside the inclusive range of 0.1 percent to 100 percent, THEN THE Trading_Engine SHALL reject the configuration at startup and emit a critical alert.

### Requirement 12: Per-Trade and Exposure Caps

**User Story:** As the bot operator, I want per-order and total-exposure caps enforced before execution, so that no single order or aggregate position exceeds defined risk bounds.

#### Acceptance Criteria

1. WHEN an order is validated, IF the order quantity is strictly greater than the configured maximum order quantity (default 1800, configurable within the range 1 to 100000), THEN THE Risk_Manager SHALL reject the order and return a rejection reason without recording the order.
2. WHEN a sell-entry order with a price greater than 0 is validated, IF the order notional value (order quantity multiplied by order price) is strictly greater than 40 percent of current trading capital, THEN THE Risk_Manager SHALL reject the order and return a rejection reason without recording the order or increasing tracked exposure.
3. WHEN a sell-entry order with a price greater than 0 is validated, IF the projected total open exposure (current tracked open exposure plus the order notional value) is strictly greater than 200 percent of current trading capital, THEN THE Risk_Manager SHALL reject the order and return a rejection reason without recording the order or increasing tracked exposure.
4. WHILE the number of orders recorded within the rolling 60-second window is greater than or equal to the configured maximum orders per minute (default 20, configurable within the range 1 to 1000), THE Risk_Manager SHALL reject each further order until the oldest recorded order ages beyond the 60-second window.
5. IF a sell-entry order has a price less than or equal to 0, THEN THE Risk_Manager SHALL bypass the notional-value and exposure checks for that order.
6. WHEN a sell-entry order with a price greater than 0 passes all validation checks, THE Risk_Manager SHALL record the order timestamp and increase tracked open exposure by the order notional value.
7. WHEN a buy fill closes a sell position, THE Risk_Manager SHALL reduce tracked open exposure by the value of the closed position, flooring the tracked open exposure at zero.
8. WHEN an order quantity is less than or equal to the configured maximum order quantity and all other applicable checks pass, THE Risk_Manager SHALL accept the order.

### Requirement 13: Flash-Crash and Black-Swan Protection

**User Story:** As the bot operator, I want automatic protection against extreme market moves, so that the Trading_Engine reduces risk during flash crashes and volatility shocks.

#### Acceptance Criteria

1. IF the index price rises or falls by more than 0.5 percent relative to the highest or lowest index price observed within any rolling 5-second window, and at least 5 price samples are available within that window, THEN THE Black_Swan_Guard SHALL classify the condition as a velocity shock.
2. WHEN a velocity shock is classified, THE Trading_Engine SHALL submit market exit orders to Square_Off all open positions within 2 seconds of classification.
3. IF the index price rises or falls beyond the VIX-derived rolling threshold, computed as the greater of 0.5 percent and (India VIX divided by 100) multiplied by 4.0 percent, relative to the highest or lowest index price observed within any rolling 180-second window, THEN THE Black_Swan_Guard SHALL classify the condition as a structural-volatility event.
4. WHILE a structural-volatility event is active, THE Risk_Manager SHALL reject each new entry order and return a rejection reason indicating that entries are suspended due to structural volatility.
5. IF India VIX exceeds the configured maximum threshold (default 30.0, configurable within the range 10.0 to 100.0), THEN THE Risk_Manager SHALL reject new entry orders until India VIX falls to or below the configured maximum threshold.
6. WHEN the system clock reaches the configured straddle exit time of 15:15:00 IST, THE Trading_Engine SHALL submit market exit orders to Square_Off all open straddle positions within 2 seconds.
7. WHEN a velocity shock is classified, THE Trading_Engine SHALL trip the circuit breaker and reject all new entry orders until the circuit breaker is manually reset.
8. WHILE a structural-volatility event is active, THE Risk_Manager SHALL accept and forward exit orders for processing.
9. IF fewer than 5 price samples are available within the applicable rolling window, THEN THE Black_Swan_Guard SHALL NOT classify a velocity shock or a structural-volatility event and SHALL retain the existing protection state unchanged.

### Requirement 14: Backtesting for Measured Edge

**User Story:** As the bot operator, I want strategies backtested against historical data, so that I can measure each strategy's edge before risking capital.

#### Acceptance Criteria

1. WHEN a backtest is run for a strategy over a historical dataset containing at least one valid trading session, THE Backtest_Engine SHALL produce all four result metrics: net PnL (currency value inclusive of all simulated charges), win rate (percentage of trades with net PnL greater than zero, range 0 to 100), maximum drawdown (percentage of peak balance, range 0 to 100), and trade count (non-negative integer).
2. THE Backtest_Engine SHALL apply the same per-order, exposure, and circuit-breaker risk rules used in live trading, using identical configured threshold values, such that no simulated trade or aggregate exposure exceeds those configured limits.
3. WHEN a backtest completes with at least one recorded trade, THE Backtest_Engine SHALL persist the trade-by-trade results to a report file, with one row per trade including at minimum the trade date, gross PnL, charges, net PnL, and running balance.
4. WHERE a stress-scenario dataset is provided, THE Backtest_Engine SHALL produce the same four result metrics defined in criterion 1 for that scenario, computed solely from the stress-scenario dataset.
5. FOR ALL backtests run with identical strategy configuration and identical input data, THE Backtest_Engine SHALL produce identical values for all four result metrics defined in criterion 1 across repeated runs.
6. IF the input dataset is missing, empty, or contains no session with both a valid entry row (between 09:15 and 09:25) and a valid exit row (between 15:10 and 15:20), THEN THE Backtest_Engine SHALL terminate without persisting a report file and SHALL return an indication that no trades were generated.
7. IF the simulated account balance reaches or falls below zero during a backtest, THEN THE Backtest_Engine SHALL stop processing further sessions, retain all trade results recorded up to that point, and return an indication that the account was depleted.

### Requirement 15: Paper-to-Live Staging Validation

**User Story:** As the bot operator, I want live capital gated behind demonstrated paper-trading performance, so that real money is only risked after the system proves measurable edge and execution quality.

#### Acceptance Criteria

1. WHILE the Staging_Manager current level is less than 5, THE Trading_Engine SHALL route all orders in PAPER mode and SHALL reject any configuration requesting UPSTOX live order routing, regardless of the configured broker value.
2. WHEN a Trading_Session ends on a trading day whose date does not equal the Staging_Manager last-processed evaluation date, THE Staging_Manager SHALL evaluate that day's recorded metrics exactly once, update level progress, clear that day's metrics, and set the last-processed evaluation date to that day's date.
3. IF a Trading_Session ends on a trading day whose date equals the Staging_Manager last-processed evaluation date, THEN THE Staging_Manager SHALL skip evaluation and leave all level progress counters unchanged.
4. IF the Trading_Engine records a fatal exception while the current level equals 1, THEN THE Staging_Manager SHALL reset the Level 1 clean-day counter to zero while preserving the current level value and all other counters.
5. WHEN a Level 4 evaluation window reaches 15 completed trading days, THE Staging_Manager SHALL advance the current level to 5 only if all of the following hold: win rate is at least 55 percent, cumulative net PnL is greater than zero, average execution latency across the 15-day window is below 250 milliseconds, and average slippage across the 15-day window is below 1.0 percent.
6. IF a Level 4 evaluation window reaches 15 completed trading days and any one of the four advancement conditions in criterion 5 is not met, THEN THE Staging_Manager SHALL reset the Level 4 window start date to the current trading day and reset the Level 4 win count, total-day count, and cumulative net PnL to zero, leaving the current level at 4.
7. WHEN the Staging_Manager advances the current level to 5, THE Trading_Engine SHALL continue operating in PAPER mode until the operator manually enables UPSTOX live mode.
8. WHEN the Staging_Manager completes any level evaluation, THE Staging_Manager SHALL append one durable audit record containing the evaluation timestamp, the evaluated level, the metric values used in the decision, and the resulting outcome (advance, reset, or no-change), such that the record persists across process restarts.

### Requirement 16: Event-Driven Architecture Resilience

**User Story:** As the bot operator, I want the event bus to remain stable under load, so that bursts of market activity do not crash or stall the Trading_Engine.

#### Acceptance Criteria

1. IF an event handler raises an exception while processing an event, THEN THE Event_Bus SHALL log an error record identifying the handler name and event type, SHALL continue dispatching the same event to all remaining registered handlers, and SHALL continue processing subsequent events from the queue without stopping the routing loop.
2. WHILE dispatching events, THE Event_Bus SHALL limit the number of concurrently executing handler tasks to a configured maximum, defaulting to 50, and SHALL hold any additional handler tasks until a concurrency slot becomes available.
3. WHEN a single handler takes longer than a configured slow-handler threshold, defaulting to 100 milliseconds, to process one event, THE Event_Bus SHALL increment the slow-handler occurrence count by one and SHALL log a warning record identifying the handler name, the measured duration in milliseconds, and the event type.
4. WHEN the system status report is requested, THE Event_Bus SHALL return the current queue depth, the configured maximum queue capacity, the cumulative processed-event count, the cumulative dropped-event count, the cumulative slow-handler count, and the current subscriber count.
5. WHEN an event is published from a thread other than the event loop thread, THE Event_Bus SHALL enqueue that event onto the event loop in a thread-safe manner without raising an exception to the publishing thread.
6. IF an event is published while the queue is at its configured maximum capacity, THEN THE Event_Bus SHALL discard the event, SHALL increment the dropped-event count by one, and SHALL log an error record identifying the discarded event type, without raising an exception to the publishing caller.

### Requirement 17: Infrastructure Sizing and Placement

**User Story:** As the bot operator, I want the EC2 host placed and sized for low-latency trading with monitored compute headroom, so that the Trading_Engine is not starved of resources or slowed by network distance to the broker.

#### Acceptance Criteria

1. THE Deployment_Topology SHALL specify, as the deployment region for the host that runs the Trading_Engine, a hosting region geographically nearest the broker and exchange (for NSE and Upstox an India region such as AWS ap-south-1 Mumbai, or the equivalent region on another cloud or VPS provider).
2. WHEN the Trading_Engine starts, IF the detected host region does not match the configured deployment region defined by the Deployment_Topology, THEN THE Instance_Monitor SHALL emit a critical alert through the Health_Alerter identifying the detected region and the configured deployment region.
3. THE Deployment_Topology SHALL specify an EC2 instance class that provides at least 2 vCPUs and at least 2 GB of usable RAM.
4. WHEN the Trading_Engine starts, IF the host instance provides fewer than 2 vCPUs or less than 2 GB of total RAM, THEN THE Instance_Monitor SHALL emit a critical alert through the Health_Alerter reporting the detected vCPU count and total RAM.
5. WHERE the host EC2 instance belongs to a burstable instance family, THE Instance_Monitor SHALL sample CPU-credit balance, CPU steal time, and CPU throttling at an interval not exceeding 60 seconds.
6. WHERE the host EC2 instance belongs to a burstable instance family, WHEN the CPU-credit balance falls below a configured early-warning threshold or CPU steal time rises above a configured percentage threshold, THE Health_Alerter SHALL emit an alert reporting the measured value within one monitoring interval, while new entry orders remain permitted.
7. THE Deployment_Topology SHALL define an Order_Round_Trip_Latency budget, defaulting to 1000 milliseconds and configurable within the inclusive range 100 milliseconds to 10000 milliseconds.
8. WHEN a measured Order_Round_Trip_Latency exceeds the configured latency budget, THE Health_Alerter SHALL emit an alert reporting the measured latency in milliseconds within 5 seconds of measurement.
9. THE Deployment_Topology SHALL define exactly one primary reference production deployment as the production target, specifying a concrete committed instance specification of at least 2 vCPUs and at least 4 GB of RAM that is either non-burstable or burstable with unlimited mode enabled, hosted in the India region nearest NSE and Upstox (such as AWS ap-south-1 Mumbai), while documenting alternative cloud or VPS providers as portability options.

### Requirement 18: Broker-Side Protective Orders

**User Story:** As the bot operator, I want a protective order placed at the broker for every open position, so that open positions remain protected even if the EC2 instance, the network, or the application becomes completely unavailable.

#### Acceptance Criteria

1. WHEN a position entry fill is confirmed, THE Trading_Engine SHALL place a Protective_Order for that position at the broker within 5 seconds of the fill confirmation.
2. THE Protective_Order SHALL be a broker-persisted order type (broker stop-loss order or GTT_Order) that remains active at the broker while the Trading_Engine process, the EC2 instance, or the network connection is unavailable.
3. IF a Protective_Order placement request fails, THEN THE Trading_Engine SHALL retry placement up to 3 times using exponential backoff starting at a 1-second delay and doubling each attempt, capped at 30 seconds per delay.
4. IF a Protective_Order cannot be confirmed at the broker after the configured retry attempts, THEN THE Trading_Engine SHALL Square_Off the associated position and emit a critical alert through the Health_Alerter, rather than retaining the position without a confirmed Protective_Order.
5. WHEN a Protective_Order is confirmed at the broker, THE Trading_Engine SHALL record the broker-assigned Protective_Order identifier in persisted state.
6. WHEN the Trading_Engine starts, THE State_Reconciler SHALL retrieve active Protective_Orders from the broker and verify that every reconciled open position has a corresponding active Protective_Order at the broker.
7. IF the State_Reconciler finds a reconciled open position without an active Protective_Order at the broker, THEN THE Trading_Engine SHALL place a Protective_Order for that position or Square_Off that position, and SHALL emit a discrepancy alert through the Health_Alerter.
8. WHEN a position is closed, THE Trading_Engine SHALL cancel any remaining active Protective_Order associated with that position at the broker.
9. WHILE a position is open, THE Trading_Engine SHALL maintain exactly one confirmed broker-persisted Protective_Order for that position, and IF an open position is found to have no confirmed Protective_Order at the broker, THEN THE Trading_Engine SHALL treat the condition as a violation and Square_Off that position.

### Requirement 19: Autonomous Unattended Operation

**User Story:** As the bot operator, I want the system to run a full trading day end-to-end with no human interaction, so that the engine operates safely in my absence and fails into a protected state rather than continuing unsafely.

#### Acceptance Criteria

1. THE Trading_Engine SHALL perform token acquisition, capital synchronization, strategy entries, strategy exits, end-of-day Square_Off, end-of-day evaluation, and recovery from transient failures across a full Trading_Session using automated channels only.
2. THE Trading_Engine SHALL complete every routine operational task during a Trading_Session using automated channels only, such that no routine operational task depends on the Telegram_Channel or on any single human-in-the-loop channel.
3. WHEN a transient failure occurs in token acquisition, market-data connectivity, or broker connectivity during a Trading_Session, THE Trading_Engine SHALL attempt automated recovery according to the applicable retry and failover rules without human intervention.
4. WHEN the system clock reaches the configured end-of-day square-off time on a trading day, THE Trading_Engine SHALL Square_Off all open positions and perform end-of-day evaluation automatically.
5. IF a condition arises that cannot be resolved automatically and requires human attention, THEN THE Trading_Engine SHALL enter Safe_Mode and emit a critical alert through at least two independent notification channels.
6. WHILE in Safe_Mode, THE Risk_Manager SHALL reject all new entry orders while continuing to accept and forward exit orders and Protective_Order management for existing positions.
7. IF a condition requiring human attention concerns the safety of an open position and remains unresolved for a configured duration, defaulting to 300 seconds, THEN THE Trading_Engine SHALL Square_Off the affected positions rather than continuing to hold them in an unmanaged state.

### Requirement 20: Infrastructure Resilience and Recovery

**User Story:** As the bot operator, I want host-level recovery, durable backups, hang detection, and accurate time, so that the system survives instance failures, hung processes, and clock drift without losing history or stalling silently.

#### Acceptance Criteria

1. THE Deployment_Topology SHALL enable EC2 automatic recovery so that an instance failing an EC2 system status check or an instance status check is recovered without manual intervention.
2. THE Backup_Manager SHALL create a durable backup of persisted state files and audit logs at a configured interval not exceeding 24 hours.
3. THE Backup_Manager SHALL store each backup in a location independent of the host instance's primary volume, such that the backup remains retrievable after the instance is terminated.
4. IF a backup operation fails, THEN THE Health_Alerter SHALL emit an alert identifying the failed backup within one backup interval.
5. THE Liveness_Watchdog SHALL require the Trading_Engine to record a liveness signal at an interval not exceeding a configured period, defaulting to 60 seconds.
6. IF the Trading_Engine does not record a liveness signal within two consecutive configured periods while the process remains running, THEN THE Liveness_Watchdog SHALL classify the process as hung and SHALL trigger a restart of the Trading_Engine.
7. WHEN the Liveness_Watchdog triggers a restart, THE Health_Alerter SHALL emit a critical alert indicating that a hung-process restart occurred, including the timestamp of the restart.
8. THE Deployment_Topology SHALL configure a time-synchronization service (NTP or chrony) to run continuously on the host EC2 instance.
9. WHEN the Trading_Engine starts, IF the measured system-clock offset from the network time source exceeds a configured tolerance, defaulting to 1000 milliseconds, THEN THE Health_Alerter SHALL emit an alert reporting the measured offset in milliseconds.

### Requirement 21: Optional AI-Agent Augmentation

**User Story:** As the bot operator, I want optional AI augmentation that is supervisory only and strictly bounded, so that AI can add insight when enabled without ever bypassing risk controls or delaying protective actions.

#### Acceptance Criteria

1. THE AI_Advisor SHALL be disabled by default.
2. WHERE the AI_Advisor is enabled, THE AI_Advisor SHALL act only in a supervisory or advisory capacity, limited to market-regime classification, anomaly and log triage, post-trade analysis, natural-language operator status, and pre-approved remediation suggestions.
3. WHERE the AI_Advisor is enabled, every trading action influenced by an AI_Advisor output SHALL pass through the same Risk_Manager caps and circuit breakers applied to non-AI-influenced actions before submission.
4. THE AI_Advisor SHALL NOT bypass, disable, or modify any Risk_Manager cap or circuit breaker.
5. WHERE the AI_Advisor is enabled, every AI-influenced action SHALL be restricted to a configured whitelist of action types, and THE Trading_Engine SHALL reject any AI-proposed action outside that whitelist.
6. WHERE the AI_Advisor is enabled, THE Trading_Engine SHALL append to the audit log, for each AI_Advisor invocation, the invocation inputs and the resulting outputs.
7. WHERE the AI_Advisor is invoked within or adjacent to the trading loop, THE Trading_Engine SHALL impose a strict timeout on the AI_Advisor call, defaulting to 2000 milliseconds and configurable within the inclusive range 100 milliseconds to 10000 milliseconds, after which THE Trading_Engine SHALL proceed using deterministic non-AI logic.
8. IF the AI_Advisor exceeds its configured timeout, returns an error, or is disabled, THEN THE Trading_Engine SHALL execute deterministic non-AI logic for the affected decision.
9. THE AI_Advisor SHALL NOT block or delay the submission of any exit order or Square_Off operation.

### Requirement 22: Secrets and Production Security Hardening

**User Story:** As the bot operator, I want all secrets stored and accessed securely and the local token endpoint locked down, so that credentials are not exposed in the repository or over the network.

#### Acceptance Criteria

1. THE Trading_Engine SHALL load all secrets — broker API keys, the Upstox access token, the Telegram token, AI provider keys, and the Token_HTTP_Endpoint shared secret — from the Secret_Store rather than from plaintext values committed to the source repository.
2. THE Trading_Engine SHALL exclude every secret-bearing file from version control.
3. THE Secret_Store SHALL restrict read and write access to each on-disk secret file to the operating-system user that runs the Trading_Engine.
4. IF a required secret is missing or unreadable at startup, THEN THE Trading_Engine SHALL emit a critical alert through the Health_Alerter and SHALL reject live order routing until the secret is available.
5. THE Token_HTTP_Endpoint SHALL bind only to the loopback interface or otherwise restrict access such that the endpoint is not reachable from public networks.
6. THE Token_HTTP_Endpoint SHALL require the configured shared secret on every token-submission request before altering the stored token.
7. WHEN a secret value would be written to a log entry or a status report, THE Trading_Engine SHALL mask the secret value such that the raw secret does not appear in the log entry or status report.

### Requirement 23: Instance Identity and Transaction Tagging

**User Story:** As the bot operator, I want every running instance to carry a unique identity and a monotonic fencing epoch stamped onto all its writes and broker orders, so that the work of one instance can always be distinguished from the work of any other instance.

#### Acceptance Criteria

1. WHEN the Trading_Engine starts, THE Trading_Engine SHALL assign an Instance_ID that is unique across all instances that have run or are running.
2. WHEN the Trading_Engine starts, THE Trading_Engine SHALL read the current Instance_Epoch from the durable shared record, increment it by one, and persist the incremented Instance_Epoch to the durable shared record using an atomic write before strategies begin evaluation.
3. IF the durable shared record holding the Instance_Epoch is unreadable or the atomic write of the incremented Instance_Epoch fails at startup, THEN THE Trading_Engine SHALL reject live order routing and emit a critical alert through the Health_Alerter rather than proceeding without a persisted Instance_Epoch.
4. WHEN the Trading_Engine writes a state record, an event record, or a log entry, THE Trading_Engine SHALL stamp that record with the current Instance_ID and Instance_Epoch.
5. WHEN the Trading_Engine submits an order to the broker, THE Trading_Engine SHALL embed the current Instance_Epoch in the broker order tag such that the resulting tag length does not exceed the broker's maximum order-tag length.
6. WHEN the system status report is requested, THE Trading_Engine SHALL include the current Instance_ID and Instance_Epoch in the report.

### Requirement 24: Active-Instance Coordination via Lease

**User Story:** As the bot operator, I want active-leader coordination handled through a lightweight epoch-fenced lease rather than a hard distributed lock, so that exactly one instance places new entry orders at a time while a brief overlap is bounded by exposure caps and broker-side protective orders.

#### Acceptance Criteria

1. THE Active_Instance_Registry SHALL hold the current leader Instance_ID, the leader Instance_Epoch, and the most recent heartbeat timestamp in durable, provider-agnostic storage.
2. WHILE an instance holds the Instance_Lease, THE Trading_Engine SHALL refresh the heartbeat timestamp in the Active_Instance_Registry at a configured interval, defaulting to 15 seconds.
3. WHEN the Trading_Engine starts and observes a fresh Instance_Lease held by another instance, THE Trading_Engine SHALL claim leadership only by writing an Instance_Epoch strictly higher than the recorded leader Instance_Epoch to the Active_Instance_Registry.
4. WHEN an instance observes in the Active_Instance_Registry an Instance_Epoch strictly higher than its own holding the Instance_Lease, THE Trading_Engine SHALL relinquish leadership, stop submitting new entry orders, and Square_Off its own open positions.
5. WHILE an instance does not hold the Instance_Lease, THE Risk_Manager SHALL reject new entry orders submitted from that instance while continuing to accept and forward exit orders.
6. THE Active_Instance_Registry coordination mechanism SHALL be a heartbeat-refreshed, epoch-fenced lease and SHALL NOT be implemented as an operating-system lock or a distributed lock.
7. WHILE two instances are briefly active during a leadership transition, THE Risk_Manager exposure caps and the broker-side Protective_Orders SHALL remain in force such that combined open exposure stays within the configured exposure limits.

### Requirement 25: Duplicate and Rogue Instance Detection and Reconciliation

**User Story:** As the bot operator, I want duplicate or superseded instances detected and their orders reconciled by epoch, so that a stale instance cannot keep acting without being noticed and corrected.

#### Acceptance Criteria

1. IF two or more fresh Instance_Leases bearing different Instance_IDs are observed within the configured lease time-to-live, THEN THE Health_Alerter SHALL emit a critical alert identifying the competing Instance_IDs and their Instance_Epoch values.
2. WHEN the leader instance queries broker orders and positions and finds an order tagged with an Instance_Epoch lower than the leader's Instance_Epoch, THE Trading_Engine SHALL cancel that order or take ownership of it and SHALL emit an alert through the Health_Alerter.
3. WHEN the Trading_Engine starts, THE State_Reconciler SHALL use the Instance_Epoch embedded in broker order tags to distinguish orders placed by the current instance from orders placed by a superseded instance.

### Requirement 26: External Watchdog and Auto-Healing Node

**User Story:** As the bot operator, I want an external watchdog and automatic node replacement that work on any cloud or VPS provider, so that a failed trading host is detected from outside and replaced without manual intervention while keeping exactly one active trading node.

#### Acceptance Criteria

1. THE External_Watchdog SHALL run independently of the host running the Trading_Engine, on a different node or availability zone or as a serverless or scheduled function, and SHALL check the Active_Instance_Registry lease heartbeat from outside the trading host.
2. IF the leader heartbeat timestamp in the Active_Instance_Registry is older than a configured staleness threshold, defaulting to 90 seconds, THEN THE External_Watchdog SHALL trigger recovery by restarting or replacing the trading node and SHALL emit an alert through at least two independent notification channels.
3. THE Deployment_Topology SHALL provide Node_Auto_Replacement that automatically replaces a failed trading node without manual intervention, expressed provider-agnostically as an auto-scaling group of one, a managed container service, or an equivalent mechanism on any provider.
4. THE Deployment_Topology SHALL keep exactly one trading node active at a time through auto-healing replacement rather than active-active operation, consistent with the active-leader coordination defined in Requirement 24.

### Requirement 27: Regulatory Compliance (SEBI Retail Algorithmic Trading Framework)

**User Story:** As the bot operator, I want live order flow to comply with the SEBI retail algorithmic trading framework, so that automated trading remains within the broker-routed regulatory boundaries mandated for retail algorithmic participation.

This requirement is grounded in the SEBI_Algo_Framework — the circular "Safer Participation of Retail Investors in Algorithmic Trading" dated 4 February 2025, mandatory in full from 1 April 2026.

#### Acceptance Criteria

1. WHEN the Trading_Engine submits a live order, THE Trading_Engine SHALL route the order solely through the broker's exchange-approved API path.
2. WHEN the Trading_Engine submits a live order, THE Trading_Engine SHALL attach the Algo_Identifier (the configured UPSTOX_ALGO_ID and UPSTOX_ALGO_NAME) in addition to the internal Instance_Epoch instance-epoch tag.
3. WHEN a live order is submitted, THE Trading_Engine SHALL append to the Audit_Trail one durable, tamper-evident entry recording the timestamp, symbol, side, price, quantity, broker-assigned order identifier, and Algo_Identifier.
4. WHERE the sustained order-submission rate would exceed the regulatory registration threshold of 10 orders per second, THE Trading_Engine SHALL require the strategy to be registered with the exchange via the broker before live routing, and THE Risk_Manager SHALL cap the order-submission rate below 10 orders per second by default.
5. THE Trading_Engine SHALL operate within the broker's mandatory API security controls, including two-factor authentication and daily auto-logout with daily access-token expiry, satisfied through the automated daily token refresh defined in Requirements 1 and 2.
6. WHEN the Compliance_Kill_Switch is activated, THE Trading_Engine SHALL halt submission of all new orders while continuing to manage exits and existing Protective_Orders, consistent with the existing circuit breaker and Safe_Mode behavior.
7. IF a required compliance precondition (a valid Algo_Identifier, an approved broker routing path, or Audit_Trail availability) is not satisfied, THEN THE Trading_Engine SHALL reject live order routing, remain in PAPER mode, and emit an alert through the Health_Alerter.

### Requirement 28: Paper-Trading Observability, Analysis, Optimization, and Go-Live Readiness

**User Story:** As the bot operator, I want paper-trading results recorded, analyzed, tunable, and gated behind a measurable readiness review, so that the live transition is driven by observed paper performance rather than assumption.

#### Acceptance Criteria

1. WHILE the Trading_Engine operates in PAPER mode, THE Trading_Engine SHALL record per-trade and per-strategy metrics to durable storage, including entry and exit timestamps, entry and exit prices, simulated slippage, simulated charges, net PnL, holding time, strategy name, and the prevailing VIX and market-regime context.
2. WHEN a Performance_Report is requested for a configurable date range, THE Trading_Engine SHALL produce, per strategy and in aggregate, net PnL, win rate, maximum drawdown, average execution latency, average slippage, and trade count computed from the recorded paper-trading metrics.
3. WHEN a status report or metrics output is requested during an active PAPER-mode Trading_Session, THE Trading_Engine SHALL expose the current paper-trading metrics without stopping the Trading_Engine.
4. THE Trading_Engine SHALL support adjustment of strategy parameters and risk thresholds through configuration without requiring source-code changes.
5. WHEN a Go_Live_Readiness review is performed, THE Trading_Engine SHALL evaluate the recorded paper-trading metrics together with the Staging_Manager Level 4 and Level 5 criteria, and SHALL gate the transition from PAPER mode to live order routing on both the measurable readiness criteria being met and a deliberate operator confirmation.
6. WHEN the Go_Live_Readiness criteria are not met, THE Trading_Engine SHALL remain in PAPER mode.
