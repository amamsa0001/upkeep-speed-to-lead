from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


# --- HubSpot Webhook ---

class HubSpotProperties(BaseModel):
    firstname: str
    lastname: str
    email: Optional[str] = None
    phone: str
    company: Optional[str] = None
    jobtitle: Optional[str] = None
    industry: Optional[str] = None
    reason_for_interest: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        digits = re.sub(r"[^\d+]", "", v)
        if not digits.startswith("+"):
            digits = "+1" + digits.lstrip("1")
        return digits


class HubSpotWebhook(BaseModel):
    properties: HubSpotProperties


# --- Sendblue Inbound Webhook ---
# Matches the actual Sendblue inbound webhook payload from docs.sendblue.com

class SendblueInbound(BaseModel):
    accountEmail: Optional[str] = None
    content: str
    is_outbound: bool = False
    status: Optional[str] = None
    error_code: Optional[int] = None
    error_message: Optional[str] = None
    error_reason: Optional[str] = None
    error_detail: Optional[str] = None
    message_handle: Optional[str] = None
    date_sent: Optional[str] = None
    date_updated: Optional[str] = None
    from_number: str
    number: str  # E.164 phone of the end-user
    to_number: Optional[str] = None
    was_downgraded: Optional[bool] = None
    plan: Optional[str] = None
    media_url: Optional[str] = None
    message_type: Optional[str] = None
    group_id: Optional[str] = None
    participants: Optional[list[str]] = None
    send_style: Optional[str] = None
    opted_out: bool = False
    sendblue_number: Optional[str] = None
    service: Optional[str] = None
    group_display_name: Optional[str] = None


# --- OpenAI Structured Outputs ---

class InitialScoreResult(BaseModel):
    urgency_score: int
    classification: str  # hot | warm | low-fit
    rationale: str
    messages: list[str]
    qualifying_question: str
    recommended_action: str


class ReplyEvalResult(BaseModel):
    updated_urgency_score: int
    classification: str
    rationale: str
    reply_messages: list[str]
    should_escalate: bool
    recommended_action: str
    conversation_stage: str  # qualifying | escalating | closing


# --- API Responses ---

class HubSpotResponse(BaseModel):
    lead_id: int
    urgency_score: int
    classification: str
    messages_sent: int
    elapsed_seconds: float


class SendblueResponse(BaseModel):
    lead_id: int
    updated_urgency_score: int
    classification: str
    should_escalate: bool
    replies_sent: int


# --- Lead Display ---

class MessageRecord(BaseModel):
    direction: str
    content: str
    created_at: str


class LeadSummary(BaseModel):
    id: int
    first_name: str
    last_name: str
    company: Optional[str]
    phone: str
    urgency_score: int
    classification: str
    conversation_stage: str
    turn_count: int
    created_at: str


class LeadDetail(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: Optional[str]
    phone: str
    company: Optional[str]
    job_title: Optional[str]
    industry: Optional[str]
    reason_for_interest: Optional[str]
    urgency_score: int
    classification: str
    rationale: Optional[str]
    recommended_action: Optional[str]
    conversation_stage: str
    turn_count: int
    created_at: str
    updated_at: str


class LeadDetailResponse(BaseModel):
    lead: LeadDetail
    transcript: list[MessageRecord]


class LeadListResponse(BaseModel):
    leads: list[LeadSummary]
    count: int
