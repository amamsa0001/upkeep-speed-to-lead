# UpKeep Speed-to-Lead iMessage Orchestrator

AI-powered instant text outreach that turns demo requests into conversations in under 30 seconds.

Built for the **UpKeep GTM Growth Engineer** final interview — Challenge #1: Lead-to-Pipeline Conversion.

---

## Try the Demo

### Step 1: Text the number

Before submitting a demo request, send any text message to:

**+1 (786) 284-7802**

This is required because the iMessage delivery API (Sendblue) needs a prior conversation to exist before it can send outbound messages. In production, this constraint is removed by using a dedicated messaging backend or an upgraded API plan.

### Step 2: Submit a demo request

You have two options:

| Option | Link | Notes |
|--------|------|-------|
| **Railway Mock Form** | [web-production-aa81a.up.railway.app](https://web-production-aa81a.up.railway.app/) | Recommended for demos. Triggers the system instantly — bypasses HubSpot webhook delay. |
| **HubSpot Form** | [HubSpot Demo Request](https://share-na2.hsforms.com/2ZuCe7gVrSaG58r0BLi0rnQ428o8b) | Full production experience. HubSpot sends the webhook anywhere from instantly to ~6 minutes depending on its internal queue. |

Both options produce the same result — the lead is scored by AI, personalized iMessages are sent to your phone, and the sales team is notified in Slack.

### Step 3: Reply to the texts

Once you receive the initial outreach texts, reply naturally. The AI will:
1. Read your response and ask a relevant follow-up question
2. After your second reply, hand off to the sales team with a Slack escalation alert containing the full conversation transcript

---

## How It Works

1. **HubSpot webhook** fires on form submission
2. **OpenAI GPT** scores the lead (1-10 urgency, hot/warm/low-fit classification)
3. **AI generates** 2 personalized iMessages as a sales rep
4. **Sendblue API** delivers texts with typing indicators and natural delays
5. **Lead replies** are evaluated by AI, which asks smart follow-up questions
6. **After 2 turns**, AI hands off to the human team via **Slack** with full context
7. Slack messages **update in-place** — one thread per lead, not notification spam

---

## API Cost

The AI scoring and message generation runs on **GPT-5-mini**, which costs:

| | Per 1M tokens |
|---|---|
| Input | $0.75 |
| Output | $3.00 |

Each lead uses roughly 2,300 input tokens and 450 output tokens across a full conversation, which comes out to **~$0.003 per lead** — a third of a cent.

At scale, 1,000 leads/month would cost approximately **$3 in OpenAI API fees**.

---

## Presentation

[View the slide deck](https://docs.google.com/presentation/d/1ir-pIL4d811VKYV3V_MCXHI9NpfqIeGGff3WiSDYU8I/edit?usp=sharing)

---

## Tech Stack

- **Python / FastAPI** — async web framework
- **OpenAI GPT-5-mini** — lead scoring + message generation
- **Sendblue** — iMessage delivery with typing indicators
- **Slack Bot API** — real-time team notifications with in-place updates
- **SQLite** — conversation state and transcripts
- **Railway** — cloud hosting
- **HubSpot** — form submission webhook source
