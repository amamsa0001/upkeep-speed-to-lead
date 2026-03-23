import logging
import re
import time

from fastapi import APIRouter, HTTPException, Request

from config import settings
from database import (
    get_lead_by_phone,
    get_transcript,
    insert_lead,
    insert_message,
    update_lead,
)
from models import (
    HubSpotResponse,
    SendblueInbound,
    SendblueResponse,
)
from scoring import evaluate_reply, score_initial_lead
from sendblue import send_message_sequence
from slack import notify_escalation, notify_new_lead

logger = logging.getLogger("upkeep.webhooks")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _extract_hubspot_prop(properties: dict, *keys: str) -> str | None:
    """Extract a value from HubSpot properties, trying multiple key names.
    Handles both formats:
      - HubSpot workflow: {"firstname": {"value": "Sam", "versions": [...]}}
      - Direct/demo form:  {"firstname": "Sam"}
    """
    for key in keys:
        val = properties.get(key)
        if val is None:
            continue
        if isinstance(val, dict):
            return val.get("value")
        return str(val)
    return None


def _normalize_phone(phone: str) -> str:
    digits = re.sub(r"[^\d]", "", phone)  # Strip everything except digits
    if digits.startswith("1") and len(digits) == 11:
        return "+" + digits
    return "+1" + digits.lstrip("1")


@router.post("/hubspot", response_model=HubSpotResponse)
async def hubspot_webhook(request: Request):
    start = time.monotonic()
    body = await request.json()

    # Handle both formats: direct {"properties": {...}} or HubSpot workflow full payload
    properties = body.get("properties", body)

    first_name = _extract_hubspot_prop(properties, "firstname", "first_name") or "Unknown"
    last_name = _extract_hubspot_prop(properties, "lastname", "last_name") or "Unknown"
    email = _extract_hubspot_prop(properties, "email", "work_email")
    phone_raw = _extract_hubspot_prop(properties, "phone", "mobile_number", "mobilephone", "hs_calculated_phone_number")
    company = _extract_hubspot_prop(properties, "company", "company_name")
    job_title = _extract_hubspot_prop(properties, "jobtitle", "role", "job_title")
    industry = _extract_hubspot_prop(properties, "industry")
    reason = _extract_hubspot_prop(properties, "reason_for_interest", "message", "notes")

    if not phone_raw:
        raise HTTPException(status_code=422, detail="No phone number found in payload")

    phone = _normalize_phone(phone_raw)

    logger.info(f"HubSpot webhook received for {first_name} {last_name} ({phone})")

    # 1. Insert lead
    lead_data = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "company": company,
        "job_title": job_title,
        "industry": industry,
        "reason_for_interest": reason,
    }
    try:
        lead_id = await insert_lead(lead_data)
    except Exception:
        # Phone already exists — check if they're in an active conversation
        from database import clear_messages, get_lead_by_phone as _get
        existing = await _get(phone)
        if existing:
            lead_id = existing["id"]
            # Don't reset if lead is mid-conversation — just return current state
            if existing["conversation_stage"] in ("sending", "qualifying", "escalating"):
                logger.info(f"Ignoring duplicate HubSpot webhook — lead {lead_id} is in active conversation ({existing['conversation_stage']})")
                elapsed = time.monotonic() - start
                return HubSpotResponse(
                    lead_id=lead_id,
                    urgency_score=existing["urgency_score"],
                    classification=existing["classification"],
                    messages_sent=0,
                    elapsed_seconds=round(elapsed, 2),
                )
            # Lead is in "new" or "closing" — safe to reset for fresh session
            await update_lead(lead_id, {
                "first_name": first_name, "last_name": last_name,
                "email": email, "company": company,
                "job_title": job_title, "industry": industry,
                "reason_for_interest": reason,
                "conversation_stage": "new", "turn_count": 0,
                "urgency_score": 0, "classification": "unscored",
                "rationale": None, "recommended_action": None,
            })
            await clear_messages(lead_id)  # Fresh conversation
            logger.info(f"Lead {lead_id} reset for new session")
        else:
            raise
    lead_data["id"] = lead_id
    logger.info(f"Lead created/updated with ID {lead_id}")

    # 2. Score with OpenAI
    try:
        score_result = await score_initial_lead(lead_data)
        logger.info(
            f"Lead scored: {score_result.urgency_score}/10 ({score_result.classification})"
        )
    except Exception as e:
        logger.error(f"OpenAI scoring failed: {e}")
        raise HTTPException(status_code=500, detail="Scoring failed")

    # 3. Update lead with score — set stage to "sending" to block incoming replies
    await update_lead(lead_id, {
        "urgency_score": score_result.urgency_score,
        "classification": score_result.classification,
        "rationale": score_result.rationale,
        "recommended_action": score_result.recommended_action,
        "conversation_stage": "sending",
    })

    # 4. Send messages via Sendblue
    try:
        messages_sent = await send_message_sequence(phone, score_result.messages)
        for msg in score_result.messages:
            await insert_message(lead_id, "outbound", msg)
        logger.info(f"Sent {messages_sent} messages to {phone}")
    except Exception as e:
        logger.error(f"Sendblue send failed: {e}")
        messages_sent = 0

    # Mark as qualifying — now ready to accept replies
    await update_lead(lead_id, {"conversation_stage": "qualifying"})

    # 5. Notify Slack — store message ts for future updates
    try:
        slack_ts = await notify_new_lead(lead_data, score_result)
        if slack_ts:
            await update_lead(lead_id, {"slack_message_ts": slack_ts})
    except Exception as e:
        logger.error(f"Slack notification failed: {e}")

    elapsed = time.monotonic() - start
    logger.info(f"HubSpot webhook processed in {elapsed:.1f}s")

    return HubSpotResponse(
        lead_id=lead_id,
        urgency_score=score_result.urgency_score,
        classification=score_result.classification,
        messages_sent=messages_sent,
        elapsed_seconds=round(elapsed, 2),
    )


@router.post("/sendblue", response_model=SendblueResponse)
async def sendblue_webhook(payload: SendblueInbound):
    # Ignore outbound status callbacks — only process actual inbound replies
    if payload.is_outbound:
        logger.info(f"Ignoring outbound status callback for {payload.number}")
        return SendblueResponse(
            lead_id=0, updated_urgency_score=0, classification="ignored",
            should_escalate=False, replies_sent=0,
        )

    logger.info(f"Sendblue inbound from {payload.number}: {payload.content[:50]}...")

    # 1. Find lead by phone
    lead = await get_lead_by_phone(payload.number)
    if not lead:
        logger.warning(f"No lead found for phone {payload.number}")
        raise HTTPException(status_code=404, detail="No lead found for this phone number")

    lead_id = lead["id"]

    # Ignore replies while initial outreach is still sending
    if lead["conversation_stage"] in ("new", "sending"):
        logger.info(f"Ignoring reply from {payload.number} — outreach still in progress")
        return SendblueResponse(
            lead_id=lead_id,
            updated_urgency_score=lead["urgency_score"],
            classification=lead["classification"],
            should_escalate=False,
            replies_sent=0,
        )

    # 2. Store inbound message and increment turn count
    await insert_message(lead_id, "inbound", payload.content)
    new_turn_count = lead["turn_count"] + 1
    await update_lead(lead_id, {"turn_count": new_turn_count})
    lead["turn_count"] = new_turn_count

    # 3. Load full transcript
    transcript = await get_transcript(lead_id)

    # 4. Check if we've exceeded max turns — force handoff
    if new_turn_count > settings.max_conversation_turns:
        handoff_msg = "Thanks for the info. Someone from our team will be reaching out to you shortly."
        try:
            await send_message_sequence(payload.number, [handoff_msg])
            await insert_message(lead_id, "outbound", handoff_msg)
        except Exception as e:
            logger.error(f"Sendblue handoff send failed: {e}")

        await update_lead(lead_id, {"conversation_stage": "closing"})

        return SendblueResponse(
            lead_id=lead_id,
            updated_urgency_score=lead["urgency_score"],
            classification=lead["classification"],
            should_escalate=True,
            replies_sent=1,
        )

    # 5. Evaluate reply with OpenAI
    try:
        eval_result = await evaluate_reply(lead, transcript, payload.content)
        logger.info(
            f"Reply evaluated: {eval_result.updated_urgency_score}/10 "
            f"({eval_result.classification}, stage={eval_result.conversation_stage})"
        )
    except Exception as e:
        logger.error(f"OpenAI reply evaluation failed: {e}")
        raise HTTPException(status_code=500, detail="Reply evaluation failed")

    # 6. Update lead
    await update_lead(lead_id, {
        "urgency_score": eval_result.updated_urgency_score,
        "classification": eval_result.classification,
        "rationale": eval_result.rationale,
        "recommended_action": eval_result.recommended_action,
        "conversation_stage": eval_result.conversation_stage,
    })

    # 7. Send reply messages
    replies_sent = 0
    try:
        replies_sent = await send_message_sequence(
            payload.number, eval_result.reply_messages
        )
        for msg in eval_result.reply_messages:
            await insert_message(lead_id, "outbound", msg)
    except Exception as e:
        logger.error(f"Sendblue reply send failed: {e}")

    # 8. Notify Slack — update existing message if we have a ts
    try:
        full_transcript = await get_transcript(lead_id)
        slack_ts = lead.get("slack_message_ts")
        await notify_escalation(lead, eval_result, payload.content, full_transcript, slack_ts)
    except Exception as e:
        logger.error(f"Slack escalation notification failed: {e}")

    return SendblueResponse(
        lead_id=lead_id,
        updated_urgency_score=eval_result.updated_urgency_score,
        classification=eval_result.classification,
        should_escalate=eval_result.should_escalate,
        replies_sent=replies_sent,
    )
