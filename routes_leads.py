from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

from database import get_lead_by_id, get_transcript, list_leads
from models import LeadDetail, LeadDetailResponse, LeadListResponse, LeadSummary, MessageRecord

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
    }


@router.get("/leads", response_model=LeadListResponse)
async def get_leads(classification: Optional[str] = None):
    rows = await list_leads(classification)
    leads = [
        LeadSummary(
            id=r["id"],
            first_name=r["first_name"],
            last_name=r["last_name"],
            company=r["company"],
            phone=r["phone"],
            urgency_score=r["urgency_score"],
            classification=r["classification"],
            conversation_stage=r["conversation_stage"],
            turn_count=r["turn_count"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return LeadListResponse(leads=leads, count=len(leads))


@router.get("/leads/{lead_id}", response_model=LeadDetailResponse)
async def get_lead(lead_id: int):
    row = await get_lead_by_id(lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead = LeadDetail(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        email=row["email"],
        phone=row["phone"],
        company=row["company"],
        job_title=row["job_title"],
        industry=row["industry"],
        reason_for_interest=row["reason_for_interest"],
        urgency_score=row["urgency_score"],
        classification=row["classification"],
        rationale=row["rationale"],
        recommended_action=row["recommended_action"],
        conversation_stage=row["conversation_stage"],
        turn_count=row["turn_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )

    messages = await get_transcript(lead_id)
    transcript = [
        MessageRecord(
            direction=m["direction"],
            content=m["content"],
            created_at=m["created_at"],
        )
        for m in messages
    ]

    return LeadDetailResponse(lead=lead, transcript=transcript)
