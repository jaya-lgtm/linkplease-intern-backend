# FAILURES.md: LinkPlease Real Failure Scenarios

This document outlines four real failure scenarios that this SQLite + background worker implementation might experience in production, along with their impact, mitigations, and future remediation strategies.

---

## Failure Scenario 1: SQLite Write Lock Escalation (Database Locked)
* **Condition**: A massive burst of concurrent requests (e.g., 2000 webhook events within 2 seconds).
* **What happens**: Even with WAL mode and `busy_timeout` enabled, SQLite locks the entire database file for write operations. If the write contention takes longer than the configured timeout (30 seconds) to resolve, SQLAlchemy queries will raise a `sqlite3.OperationalError: database is locked` exception.
* **Impact**: Incoming webhooks trying to write events/comments fail, returning HTTP 500 errors to Pseudogram and losing event data. Background workers fail to claim or update jobs.
* **How to fix it**: 
  1. Migrate the data layer from SQLite to a client-server relational database like PostgreSQL, which supports fine-grained row-level locking.
  2. Implement an in-memory message broker (e.g., Redis with Celery or a lightweight thread-safe memory queue) to buffer incoming webhook payloads, writing them to SQLite sequentially in a single writer thread.

---

## Failure Scenario 2: Process Crash During External DM Request
* **Condition**: The backend server process abruptly crashes (due to OOM, force kills, or system restarts) *after* the DM worker successfully dispatches the external HTTP request to PseudoGram, but *before* the worker can parse the response and commit the status change (to `accepted` or `failed`) in the SQLite database.
* **What happens**:
  - The job remains in `sending` status in the SQLite database.
  - On application startup, the recovery routine detects the stale `sending` job and reverts its status back to `queued`.
  - However, the external request may have already been accepted by PseudoGram's server.
* **Impact**: Retrying the job creates an ambiguous delivery state where we might accidentally send a duplicate DM.
* **Mitigation & Future Improvements**:
  - **Mitigation:** We send a deterministic `Idempotency-Key` (formatted as `rule_id:user_id`) in our API requests. When the job is retried, the PseudoGram API recognizes the key and returns the originally created `dm_id` rather than dispatching a duplicate message.
  - **Future Improvement:** Transition to a transactional Outbox pattern combined with visibility leases/locks (e.g., `lock_expires_at` timestamps on job records). This ensures that worker leases naturally expire and can be reclaimed safely, without blind state recovery on startup.

---

## Failure Scenario 3: Ambiguous Delivery of Stuck Accepted Jobs
* **Condition**: A DM job is in `accepted` status, but the PseudoGram API continues to return `"queued"` (not delivered or failed) beyond our 15-minute Accepted TTL.
* **What happens**:
  - The reconciliation worker detects that the job has exceeded the 15-minute TTL.
  - It increments the retry attempt count and schedules a retry (or marks the job as `failed` if max retries are exceeded).
* **Impact**: If the original upstream request was delayed rather than lost, and eventually processes, retrying the request could lead to a duplicate delivery, or marking it as failed could be inaccurate.
* **Mitigation**:
  - Our deterministic idempotency key (`rule_id:user_id`) ensures that when the job is retried, PseudoGram will deduplicate it on its end and return the same `dm_id`, reducing the risk of duplicates if the original request eventually processes.

---

## Failure Scenario 4: Rolling-Window Disagreement (Clock Skew/Drift)
* **Condition**: Disagreement between our local backend rate limiter and upstream rolling-window boundaries (e.g. clock drift or unsynchronized servers).
* **What happens**: The local backend rate limiter calculates rolling windows using its local timestamps, while the PseudoGram API tracks them using its own server clock.
* **Impact**: The backend may send requests believing it is within the limit, but the PseudoGram API rejects them with a `429 Rate Limited` response. This triggers retry cycles and causes delays.
* **Mitigation**:
  - We handle `429` responses dynamically by reading the `Retry-After` header and sleeping the worker thread gracefully to prevent further requests, realigning our worker dynamically with the upstream rate limits.
