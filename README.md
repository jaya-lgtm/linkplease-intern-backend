# LinkPlease Tech Intern Backend Assignment

LinkPlease is a robust, production-minded FastAPI backend designed to process automated Instagram comment keyword-to-DM flows. It safely consumes webhook events from Pseudogram, matches them against configured rules, queues sending jobs persistently in SQLite, respects API rate limits (10 DMs/rolling 60s), retries failed requests with exponential backoff, and reconciles delivery statuses asynchronously.

---

## 1. Project Architecture

The application is structured around a decoupled, event-driven pattern designed for fast webhook responses (< 5 seconds) and reliable, atomic background processing:

```
                  ┌──────────────────────┐
                  │    Pseudogram API    │
                  └──────────┬───────────┘
                             │ (Webhook payload & Signature)
                             ▼
                    ┌──────────────────┐
                    │  POST /webhook   │
                    └────────┬─────────┘
                             │
            ┌────────────────┴────────────────┐
            ▼ (Atomic Event Deduplication)    ▼ (Comment State Track)
    ┌──────────────┐                  ┌──────────────┐
    │  events DB   │                  │ comments DB  │
    └──────────────┘                  └──────────────┘
                                              │ (Case-insensitive match)
                                              ▼
                                      ┌──────────────┐
                                      │   Rules DB   │
                                      └──────┬───────┘
                                             │ (Create DM Job)
                                             ▼
                                      ┌──────────────┐
                                      │  dm_jobs DB  │ (Unique rule_id, user_id)
                                      └──────┬───────┘
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼ (Claim job)                               ▼ (Query status)
              ┌─────────────────┐                        ┌─────────────────┐
              │    DM Worker    │                        │  Recon Worker   │
              └────────┬────────┘                        └────────┬────────┘
                       │ (Rate Limited & Retry)                   │ (Reconcile state)
                       ▼                                          ▼
            ┌─────────────────────┐                    ┌─────────────────────┐
            │ POST /v1/dm/send    │                    │ GET /v1/dm/{dm_id}  │
            └──────────┬──────────┘                    └──────────┬──────────┘
                       │                                          │
                       └───────────────────┬──────────────────────┘
                                           ▼
                                ┌─────────────────────┐
                                │   Pseudogram API    │
                                └─────────────────────┘
```

---

## 2. Technology Stack

* **Backend Framework**: Python 3.11, FastAPI, Uvicorn
* **Database**: SQLite (configured in WAL mode with normal sync and busy timeout)
* **ORM**: SQLAlchemy
* **Validations**: Pydantic v2 & Pydantic Settings
* **HTTP Client**: HTTPX (async client)
* **Testing Suite**: Pytest, Pytest-asyncio

---

## 3. Database Design

SQLite is used as a persistent queue and store. The database has the following tables:

* **`rules`**: Stores keyword-to-DM configurations.
* **`comments`**: Logs commenter ID, post ID, comment text, status (`active`/`deleted`), and creation timestamps.
* **`events`**: Logs processed webhook event IDs to prevent duplicate processing.
* **`dm_jobs`**: The persistent queue storing queued, sending, retry, accepted, delivered, and failed DM tasks. Enforces a database-level `UNIQUE(rule_id, user_id)` constraint.
* **`rate_limit_logs`**: Logs timestamps of actual DM send attempts to enforce rate limits across server restarts.
* **`duplicate_blocks`**: Stores reasons and metadata for blocked duplicate actions (for accurate metrics).

---

## 4. Key Engineering Strategies

### A. Webhook Signature Verification
Incoming requests to `/webhook` verify the `X-PseudoGram-Signature` header against `sha256=<hex>` computed using the raw request body and the secret `PSEUDOGRAM_API_KEY`. Verification uses `hmac.compare_digest` to protect against timing attacks.

### B. Double-Layer Idempotency & Deduplication
1. **Event Deduplication**: The `events` table enforces a primary key constraint on `event_id`. Duplicate events are caught atomically, registered in `duplicate_blocks`, and ignored.
2. **DM Delivery Idempotency**: The `dm_jobs` table enforces `UNIQUE(rule_id, user_id)`. If a user comments multiple times matching the same rule, the DB blocks duplicate jobs atomically.
3. **Mock API Idempotency Key**: Outgoing DM requests include an `Idempotency-Key` header formatted as `rule_id:user_id` to guarantee the API never delivers twice.

### C. Rate Limit Guard (10 DMs / Rolling 60s)
Before making an API call, the worker query counts records in `rate_limit_logs` from the last 60 seconds. If count is 10, the worker calculates the remaining expiration duration of the oldest log and sleeps before executing. This persistent log approach works across restarts and multiple workers.

### D. Retry & Backoff Logic
* **429 (Rate Limit)**: Reschedules the job based on the `Retry-After` header.
* **500 (API Error)**: Reschedules the job using exponential backoff (`2 ** attempts`) with random jitter, capped at 60s. Job transitions to `failed` after `MAX_DM_RETRIES` (default 5).
* **400 (Bad Request)**: Transitions job status to `failed` immediately.

### E. Reconciliation (Accepted is NOT Delivered)
API returns `202 Accepted` with `dm_id`. The reconciliation worker polls `GET /v1/dm/{dm_id}`. Once the status changes to `"delivered"`, our job is marked `"delivered"`, incrementing the `sent` count.

### F. Out-of-Order Deletions
* If `comment.deleted` arrives first, a comment record is created in `comments` with status `"deleted"`. When `comment.created` arrives later, it sees the deleted status and ignores scheduling.
* If a comment is deleted after job creation but before sending, the worker detects the status `"deleted"` and cancels the send.

---

## 5. API Documentation

### 1. Create a Rule
* **Endpoint**: `POST /rules`
* **Request**:
```bash
curl -X POST http://127.0.0.1:8000/rules \
  -H "Content-Type: application/json" \
  -d '{"keyword": "PRICE", "dm_message": "Here is the price list: $100"}'
```
* **Response (201 Created)**:
```json
{
  "rule_id": "rul_5cf38b1f81d1",
  "keyword": "PRICE",
  "dm_message": "Here is the price list: $100"
}
```

### 2. Stats
* **Endpoint**: `GET /stats`
* **Request**:
```bash
curl http://127.0.0.1:8000/stats
```
* **Response (200 OK)**:
```json
{
  "sent": 12,
  "failed": 2,
  "queued": 5,
  "duplicates_blocked": 45
}
```

### 3. Webhook Receiver
* **Endpoint**: `POST /webhook`
* **Request**:
```bash
curl -X POST http://127.0.0.1:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-PseudoGram-Signature: sha256=..." \
  -d '{
    "event_id": "evt_12345",
    "event_type": "comment.created",
    "sent_at": "2026-08-10T09:14:22.481Z",
    "data": {
      "comment_id": "cmt_abc",
      "post_id": "post_xyz",
      "text": "PRICE please!",
      "created_at": "2026-08-10T09:14:21.900Z",
      "from": {
        "user_id": "usr_999",
        "username": "tester"
      }
    }
  }'
```

---

## 6. How to Run Locally

### 1. Setup Virtual Environment
```bash
python -m venv venv
./venv/Scripts/activate  # On Windows
source venv/bin/activate # On Unix
pip install -r requirements.txt
```

### 2. Environment Variables
Create a `.env` file in the root directory:
```text
PSEUDOGRAM_API_KEY=your-api-key
DATABASE_URL=sqlite:///./app.db
WEBHOOK_SIGNATURE_REQUIRED=true
MAX_DM_RETRIES=5
MOCK_API_BASE_URL=https://pseudogram-api.onrender.com
```

### 3. Run FastAPI Application
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
FastAPI Swagger documentation will be available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

---

## 7. Running Tests

### Unit and Integration Tests
```bash
pytest -v
```

### Running the 500-Event Load Test
This test spins up the server, mocks client responses, triggers 500 concurrent events (including matching, non-matching, duplicate events, and duplicate users), and verifies webhook speed and rate-limiting enforcement.
```bash
python tests/load_test.py
```

---

## 8. Running with Docker

### Build and Run with docker-compose
```bash
docker-compose build
docker-compose up -d
```
The server will start on port `8000`. You can pass environment variables directly to docker-compose.
