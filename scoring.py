import json
import logging

from openai import AsyncOpenAI

from config import settings
from models import InitialScoreResult, ReplyEvalResult
from prompts import (
    INITIAL_SCORING_SYSTEM,
    INITIAL_SCORING_USER,
    REPLY_EVAL_SYSTEM,
    REPLY_EVAL_USER,
)

logger = logging.getLogger("upkeep.scoring")

client = AsyncOpenAI(api_key=settings.openai_api_key)


async def score_initial_lead(lead: dict) -> InitialScoreResult:
    user_msg = INITIAL_SCORING_USER.format(
        first_name=lead["first_name"],
        last_name=lead["last_name"],
        email=lead.get("email", "N/A"),
        phone=lead["phone"],
        company=lead.get("company", "Unknown"),
        job_title=lead.get("job_title", "Unknown"),
        industry=lead.get("industry", "Unknown"),
        reason_for_interest=lead.get("reason_for_interest", "Not provided"),
    )

    logger.info("Calling OpenAI for initial scoring...")
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": INITIAL_SCORING_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )

    raw = response.choices[0].message.content
    logger.info("OpenAI initial scoring response received")
    data = json.loads(raw)
    return InitialScoreResult(**data)


def format_transcript(transcript: list[dict]) -> str:
    lines = []
    for msg in transcript:
        tag = "ALEX" if msg["direction"] == "outbound" else "LEAD"
        lines.append(f"[{tag}] {msg['content']}")
    return "\n".join(lines)


async def evaluate_reply(
    lead: dict, transcript: list[dict], new_reply: str
) -> ReplyEvalResult:
    transcript_text = format_transcript(transcript)

    user_msg = REPLY_EVAL_USER.format(
        first_name=lead["first_name"],
        last_name=lead["last_name"],
        company=lead.get("company", "Unknown"),
        job_title=lead.get("job_title", "Unknown"),
        industry=lead.get("industry", "Unknown"),
        reason_for_interest=lead.get("reason_for_interest", "Not provided"),
        urgency_score=lead["urgency_score"],
        classification=lead["classification"],
        turn_count=lead["turn_count"],
        transcript=transcript_text,
        new_reply=new_reply,
    )

    logger.info("Calling OpenAI for reply evaluation...")
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": REPLY_EVAL_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )

    raw = response.choices[0].message.content
    logger.info("OpenAI reply evaluation response received")
    data = json.loads(raw)
    return ReplyEvalResult(**data)
