import os
import time
import asyncio
import hmac
import hashlib
import json
import random
import threading
from unittest.mock import AsyncMock, patch
import httpx
import uvicorn

os.environ["DATABASE_URL"] = "sqlite:///./load_test.db"
os.environ["WEBHOOK_SIGNATURE_REQUIRED"] = "true"
os.environ["PSEUDOGRAM_API_KEY"] = "load-test-api-key"

from app.database import engine, Base, SessionLocal
from app.models import Rule, DMJob, DuplicateBlock, RateLimitLog

def calc_signature(body: bytes, key: str) -> str:
    return hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()

mock_send = AsyncMock()
mock_status = AsyncMock()

patch_send = patch("app.clients.pseudogram.PseudoGramClient.send_dm", mock_send)
patch_status = patch("app.clients.pseudogram.PseudoGramClient.get_dm_status", mock_status)

def run_server():
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, log_level="warning")

async def main_async():
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    await asyncio.sleep(2.0)

    async def send_dm_mock(recipient_user_id, message, comment_id, idempotency_key):
        dm_id = f"dm_{random.randint(100000, 999999)}"
        return httpx.Response(
            202,
            json={"dm_id": dm_id, "status": "queued"},
            headers={"Content-Type": "application/json"}
        )
    mock_send.side_effect = send_dm_mock

    async def get_dm_status_mock(dm_id):
        return httpx.Response(
            200,
            json={"dm_id": dm_id, "status": "delivered"},
            headers={"Content-Type": "application/json"}
        )
    mock_status.side_effect = get_dm_status_mock

    async with httpx.AsyncClient() as client:
        rule_payload = {
            "keyword": "discount",
            "dm_message": "Here is your 10% coupon: LOAD10"
        }
        res = await client.post("http://127.0.0.1:8001/rules", json=rule_payload)
        assert res.status_code == 201
        rule_data = res.json()
        rule_id = rule_data["rule_id"]
        print(f"Rule created: {rule_id}")

        events_payloads = []
        
        for i in range(1, 201):
            events_payloads.append({
                "event_id": f"evt_{i}",
                "event_type": "comment.created",
                "sent_at": "2026-08-10T09:14:22.481Z",
                "data": {
                    "comment_id": f"cmt_{i}",
                    "post_id": "post_abc",
                    "text": "I want a discount please!",
                    "created_at": "2026-08-10T09:14:21.900Z",
                    "from": {
                        "user_id": f"usr_{i}",
                        "username": f"user.{i}"
                    }
                }
            })

        for i in range(1, 101):
            events_payloads.append(events_payloads[i - 1])

        for i in range(1, 101):
            events_payloads.append({
                "event_id": f"evt_dup_user_{i}",
                "event_type": "comment.created",
                "sent_at": "2026-08-10T09:14:22.481Z",
                "data": {
                    "comment_id": f"cmt_dup_user_{i}",
                    "post_id": "post_abc",
                    "text": "discount code please",
                    "from": {
                        "user_id": f"usr_{i}",
                        "username": f"user.{i}"
                    }
                }
            })

        for i in range(201, 301):
            events_payloads.append({
                "event_id": f"evt_non_match_{i}",
                "event_type": "comment.created",
                "sent_at": "2026-08-10T09:14:22.481Z",
                "data": {
                    "comment_id": f"cmt_non_match_{i}",
                    "post_id": "post_abc",
                    "text": "just a hello message",
                    "from": {
                        "user_id": f"usr_{i}",
                        "username": f"user.{i}"
                    }
                }
            })

        random.shuffle(events_payloads)
        assert len(events_payloads) == 500

        print("Sending 500 events spread over 9 seconds...")
        start_time = time.time()
        
        async def send_webhook(evt):
            await asyncio.sleep(random.uniform(0.0, 9.0))
            
            start_req = time.time()
            body = json.dumps(evt).encode("utf-8")
            sig = calc_signature(body, "load-test-api-key")
            headers = {"X-PseudoGram-Signature": f"sha256={sig}"}
            try:
                res = await client.post("http://127.0.0.1:8001/webhook", data=body, headers=headers, timeout=10.0)
                req_dur = time.time() - start_req
                return res.status_code, req_dur
            except Exception as e:
                print(f"Error sending webhook: {e}")
                return 500, 10.0

        tasks = [send_webhook(evt) for evt in events_payloads]
        results = await asyncio.gather(*tasks)
        
        end_time = time.time()
        duration = end_time - start_time
        print(f"Sent 500 webhooks in {duration:.2f} seconds.")
        
        status_codes = [r[0] for r in results]
        req_durations = [r[1] for r in results]
        
        assert all(status == 200 for status in status_codes), f"Some webhooks failed: {status_codes}"
        
        max_duration = max(req_durations)
        print(f"Maximum individual request duration: {max_duration:.2f}s")
        assert max_duration < 5.0, f"Some webhooks were too slow: max {max_duration:.2f}s"
        assert duration < 15.0, f"Webhook batch took too long: {duration:.2f}s"
        print("All 500 webhooks returned 200, and every individual request completed within 5 seconds.")

        print("Waiting 4 seconds to observe rate limiting...")
        await asyncio.sleep(4.0)

        res_stats = await client.get("http://127.0.0.1:8001/stats")
        stats = res_stats.json()
        print(f"Stats after 4 seconds: {stats}")

        db = SessionLocal()
        rate_logs = db.query(RateLimitLog).count()
        print(f"RateLimitLog records in DB: {rate_logs}")
        assert rate_logs <= 10, f"Rate limit logs exceed 10: {rate_logs}"
        
        total_jobs = db.query(DMJob).count()
        delivered_jobs = db.query(DMJob).filter(DMJob.status == "delivered").count()
        accepted_jobs = db.query(DMJob).filter(DMJob.status == "accepted").count()
        sending_jobs = db.query(DMJob).filter(DMJob.status == "sending").count()
        
        print(f"DMJob state distribution: Total={total_jobs}, Delivered={delivered_jobs}, Accepted={accepted_jobs}, Sending={sending_jobs}")
        
        assert total_jobs == 200, f"Expected 200 jobs created, got {total_jobs}"
        assert (delivered_jobs + accepted_jobs + sending_jobs) <= 10, f"Exceeded rate limit! Sent jobs: {delivered_jobs + accepted_jobs + sending_jobs}"
        assert stats["duplicates_blocked"] == 200, f"Expected 200 duplicates blocked, got {stats['duplicates_blocked']}"
        
        db.close()
        print("LOAD TEST SUCCESSFUL!")

if __name__ == "__main__":
    if os.path.exists("./load_test.db"):
        try:
            os.remove("./load_test.db")
        except Exception:
            pass
            
    Base.metadata.create_all(bind=engine)
    
    patch_send.start()
    patch_status.start()
    
    try:
        asyncio.run(main_async())
    finally:
        patch_send.stop()
        patch_status.stop()
        if os.path.exists("./load_test.db"):
            try:
                os.remove("./load_test.db")
            except Exception:
                pass
