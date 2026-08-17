import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)

class PseudoGramClient:
    def __init__(self, base_url: str = settings.MOCK_API_BASE_URL, api_key: str = settings.PSEUDOGRAM_API_KEY):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def send_dm(self, recipient_user_id: str, message: str, comment_id: str, idempotency_key: str) -> httpx.Response:
        url = f"{self.base_url}/v1/dm/send"
        headers = {
            "X-API-Key": self.api_key,
            "Idempotency-Key": idempotency_key,
            "Content-Type": "application/json"
        }
        payload = {
            "recipient_user_id": recipient_user_id,
            "message": message,
            "comment_id": comment_id
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            logger.info(f"Sending DM to user {recipient_user_id} with comment {comment_id} and idempotency key {idempotency_key}")
            response = await client.post(url, json=payload, headers=headers)
            return response

    async def get_dm_status(self, dm_id: str) -> httpx.Response:
        url = f"{self.base_url}/v1/dm/{dm_id}"
        headers = {
            "X-API-Key": self.api_key
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            logger.info(f"Querying status for DM ID: {dm_id}")
            response = await client.get(url, headers=headers)
            return response
