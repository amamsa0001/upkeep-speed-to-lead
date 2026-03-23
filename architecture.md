# Architecture Diagram — UpKeep Speed-to-Lead Orchestrator

## Current Setup (Local + ngrok)

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────────┐
│   HubSpot Form  │────>│    ngrok     │────>│  Your PC (localhost) │
│  (demo request) │     │  (tunnel)    │     │   python main.py     │
└─────────────────┘     └──────────────┘     └──────────┬──────────┘
                                                        │
                              ┌──────────────────────────┤
                              │              │           │
                              v              v           v
                        ┌──────────┐  ┌──────────┐ ┌──────────┐
                        │  OpenAI  │  │ Sendblue │ │  Slack   │
                        │ GPT-5.4  │  │ iMessage │ │ Webhook  │
                        │  mini    │  │  /SMS    │ │          │
                        └──────────┘  └─────┬────┘ └──────────┘
                                            │
                                            v
                                     ┌─────────────┐
                                     │ Lead's Phone │
                                     │  (iMessage)  │
                                     └──────┬──────┘
                                            │
                                      reply │
                                            v
                        ┌──────────┐  ┌──────────┐
                        │  ngrok   │<─│ Sendblue │
                        │ (tunnel) │  │ (inbound │
                        └────┬─────┘  │ webhook) │
                             │        └──────────┘
                             v
                     ┌───────────────┐
                     │ Your PC again │──> OpenAI ──> Sendblue ──> Slack
                     │ (processes    │
                     │  the reply)   │
                     └───────────────┘
```

**Problems:** PC must be on. ngrok must be running. URL changes on restart.


## Railway Setup (Production)

```
┌─────────────────┐         ┌──────────────────────────────────────┐
│   HubSpot Form  │────────>│         Railway Server               │
│  (demo request) │  POST   │  https://upkeep.up.railway.app       │
└─────────────────┘  /webhooks/hubspot                             │
                             │                                     │
                             │  1. Receive lead data               │
                             │  2. Save to SQLite                  │
                             │  3. Call OpenAI for scoring          │
                             │  4. Send iMessages via Sendblue     │
                             │  5. Post Slack notification          │
                             │                                     │
                             └──────────┬───────┬──────────────────┘
                                        │       │          │
                              ┌─────────┘       │          └─────────┐
                              v                 v                    v
                        ┌──────────┐     ┌──────────┐         ┌──────────┐
                        │  OpenAI  │     │ Sendblue │         │  Slack   │
                        │ GPT-5.4  │     │  API     │         │ Webhook  │
                        │  mini    │     └─────┬────┘         └──────────┘
                        └──────────┘           │
                                               v
                                        ┌─────────────┐
                                        │ Lead's Phone │
                                        │  (iMessage)  │
                                        └──────┬──────┘
                                               │
                                         reply │
                                               v
                                        ┌──────────┐
                                        │ Sendblue │  POST /webhooks/sendblue
                                        │ (inbound)│──────────────────────┐
                                        └──────────┘                      │
                                                                          v
                             ┌──────────────────────────────────────────────┐
                             │         Railway Server (same one)            │
                             │                                              │
                             │  1. Receive reply                            │
                             │  2. Load conversation from SQLite            │
                             │  3. Call OpenAI for reply evaluation          │
                             │  4. Send qualifying question via Sendblue    │
                             │  5. Update Slack with conversation            │
                             └──────────────────────────────────────────────┘
```

**No ngrok. No PC. Runs 24/7. Permanent URL.**


## Conversation Flow

```
FORM SUBMIT
    │
    v
┌─────────────────────────────────────────────────┐
│ INITIAL OUTREACH (2 messages)                   │
│                                                 │
│  Abdullah: "Hey Sam, Abdullah here from UpKeep. │
│            Just saw your demo request."         │
│                    [15 sec + typing indicator]   │
│  Abdullah: "What got you looking into a CMMS?"  │
│                                                 │
│  >>> Slack: NEW LEAD - HOT (9/10) <<<           │
└─────────────────────────────────────────────────┘
    │
    v  (lead replies)
┌─────────────────────────────────────────────────┐
│ TURN 1 — QUALIFYING                            │
│                                                 │
│  Lead: "Our work order system is a mess"        │
│                    [15 sec + typing indicator]   │
│  Abdullah: "Are you on a paper system right     │
│            now or using some kind of software?"  │
│                                                 │
│  >>> Slack: LEAD UPDATE (7/10) <<<              │
└─────────────────────────────────────────────────┘
    │
    v  (lead replies)
┌─────────────────────────────────────────────────┐
│ TURN 2 — HANDOFF                               │
│                                                 │
│  Lead: "Mostly paper and spreadsheets"          │
│                    [15 sec + typing indicator]   │
│  Abdullah: "Got it. Going to have someone from  │
│            our team give you a call."            │
│                                                 │
│  >>> Slack: ESCALATE — Call ASAP <<<            │
└─────────────────────────────────────────────────┘
```


## External Services — What's Configured Where

```
SERVICE        CONFIGURED IN        POINTS TO
─────────────  ───────────────────  ──────────────────────────────────
OpenAI         .env (API key)       api.openai.com (outbound only)
Sendblue       .env (API key)       api.sendblue.co (outbound only)
Sendblue hook  Sendblue's servers   YOUR_URL/webhooks/sendblue
Slack          .env (webhook URL)   hooks.slack.com (outbound only)
HubSpot hook   HubSpot workflow     YOUR_URL/webhooks/hubspot
```

When you move to Railway, you update YOUR_URL in two places:
1. HubSpot workflow webhook URL
2. Sendblue inbound webhook (one API call)

Everything else stays the same.
