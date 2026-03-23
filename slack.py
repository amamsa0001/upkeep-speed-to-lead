import logging

import httpx

from config import settings
from models import InitialScoreResult, ReplyEvalResult

logger = logging.getLogger("upkeep.slack")


def _classification_emoji(classification: str) -> str:
    return {"hot": ":fire:", "warm": ":star:", "low-fit": ":snowflake:"}.get(
        classification, ":grey_question:"
    )


def _format_transcript(transcript: list[dict], lead_name: str) -> str:
    lines = []
    for m in transcript:
        if m["direction"] == "outbound":
            lines.append(f'Abdullah: "{m["content"]}"')
        else:
            lines.append(f'{lead_name}: "{m["content"]}"')
    return "\n".join(lines)


async def _post_slack(text: str) -> str | None:
    """Post a new Slack message. Returns the message ts (ID) if using bot token."""
    if settings.slack_bot_token and settings.slack_channel_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                    json={"channel": settings.slack_channel_id, "text": text},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("ok"):
                    logger.info("Slack message posted")
                    return data.get("ts")
                else:
                    logger.error(f"Slack API error: {data.get('error')} — falling back to webhook")
        except Exception as e:
            logger.error(f"Slack bot token failed: {e} — falling back to webhook")

    # Fallback to legacy webhook (no update support)
    if settings.slack_webhook_url:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.slack_webhook_url, json={"text": text})
            resp.raise_for_status()
            logger.info("Slack notification sent (webhook, no update support)")
        return None

    logger.warning("No Slack credentials configured, skipping notification")
    return None


async def _update_slack(ts: str, text: str):
    """Update an existing Slack message by its ts (ID)."""
    if not settings.slack_bot_token or not settings.slack_channel_id:
        # Can't update with webhooks — post a new message instead
        await _post_slack(text)
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://slack.com/api/chat.update",
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            json={"channel": settings.slack_channel_id, "ts": ts, "text": text},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            logger.info("Slack message updated")
        else:
            logger.error(f"Slack update error: {data.get('error')}")


async def notify_new_lead(lead: dict, score: InitialScoreResult) -> str | None:
    """Post initial lead notification. Returns Slack message ts for future updates."""
    emoji = _classification_emoji(score.classification)
    name = f"{lead['first_name']} {lead['last_name']}"
    phone = lead["phone"]
    masked_phone = f"***{phone[-4:]}" if len(phone) >= 4 else phone

    conversation = "\n".join(f'Abdullah: "{m}"' for m in score.messages)

    text = (
        f"{emoji} *NEW LEAD - {score.classification.upper()}*\n"
        f"{name} | {phone}\n"
        f"{lead.get('job_title', 'N/A')} at {lead.get('company', 'N/A')} | {lead.get('industry', 'N/A')}\n"
        f"\n"
        f"*Problem:* {lead.get('reason_for_interest', 'N/A')}\n"
        f"*Score:* {score.urgency_score}/10 | *Action:* {score.recommended_action}\n"
        f"\n"
        f"*Conversation:*\n"
        f'Abdullah: ":iphone: _[Sent via iMessage to {masked_phone}]_\n'
        f"{conversation}"
    )

    return await _post_slack(text)


async def notify_escalation(
    lead: dict, eval_result: ReplyEvalResult, new_reply: str,
    transcript: list[dict], slack_ts: str | None = None,
):
    """Update the existing Slack message (or post new if no ts)."""
    emoji = _classification_emoji(eval_result.classification)
    name = f"{lead['first_name']} {lead['last_name']}"
    lead_first = lead["first_name"]
    phone = lead["phone"]
    masked_phone = f"***{phone[-4:]}" if len(phone) >= 4 else phone

    conversation = _format_transcript(transcript, lead_first)

    if eval_result.should_escalate:
        header = f":rotating_light: *ESCALATE - {eval_result.classification.upper()}* | {eval_result.recommended_action}"
    else:
        header = f"{emoji} *LEAD UPDATE - {eval_result.classification.upper()}*"

    text = (
        f"{header}\n"
        f"{name} | {phone}\n"
        f"{lead.get('job_title', 'N/A')} at {lead.get('company', 'N/A')} | {lead.get('industry', 'N/A')}\n"
        f"\n"
        f"*Problem:* {lead.get('reason_for_interest', 'N/A')}\n"
        f"*Score:* {eval_result.updated_urgency_score}/10 | *Stage:* {eval_result.conversation_stage}\n"
        f"\n"
        f"*Conversation:*\n"
        f'Abdullah: ":iphone: _[Sent via iMessage to {masked_phone}]_\n'
        f"{conversation}\n"
        f"\n"
        f"*Action:* {eval_result.recommended_action}"
    )

    if slack_ts:
        await _update_slack(slack_ts, text)
    else:
        await _post_slack(text)
