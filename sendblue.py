import asyncio
import logging

import httpx

from config import settings

logger = logging.getLogger("upkeep.sendblue")

SENDBLUE_API_URL = "https://api.sendblue.co/api/send-message"
SENDBLUE_TYPING_URL = "https://api.sendblue.co/api/send-typing-indicator"


def _headers():
    return {
        "sb-api-key-id": settings.sendblue_api_key,
        "sb-api-secret-key": settings.sendblue_api_secret,
        "Content-Type": "application/json",
    }


async def send_typing_indicator(to_number: str):
    payload = {"number": to_number}
    if settings.sendblue_from_number:
        payload["from_number"] = settings.sendblue_from_number

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(SENDBLUE_TYPING_URL, json=payload, headers=_headers())
            resp.raise_for_status()
            logger.info(f"Typing indicator sent to {to_number}")
    except Exception as e:
        logger.warning(f"Typing indicator failed for {to_number}: {e}")


async def send_message(to_number: str, content: str) -> dict:
    payload = {
        "number": to_number,
        "content": content,
    }
    if settings.sendblue_from_number:
        payload["from_number"] = settings.sendblue_from_number

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(SENDBLUE_API_URL, json=payload, headers=_headers())
        resp.raise_for_status()
        result = resp.json()
        if result.get("error_message"):
            logger.error(f"Sendblue error for {to_number}: {result['error_message']}")
            raise Exception(f"Sendblue: {result['error_message']}")
        logger.info(f"Sendblue message sent to {to_number}: {content[:50]}...")
        return result


async def send_message_sequence(
    to_number: str, messages: list[str], stagger: float | None = None
) -> int:
    if stagger is None:
        stagger = settings.message_stagger_seconds

    sent = 0
    for i, msg in enumerate(messages):
        # Show typing indicator, wait, then send
        await send_typing_indicator(to_number)
        await asyncio.sleep(stagger)
        await send_message(to_number, msg)
        sent += 1

    logger.info(f"Sent {sent} messages to {to_number}")
    return sent
