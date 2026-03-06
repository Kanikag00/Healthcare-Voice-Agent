# Healthcare Voice Agent

An AI-powered voice agent for hospital call handling. Patients call in and the agent routes their request — appointments, lab reports, billing, or general FAQs — and handles the full conversation flow.

## Current Status

**V1 is complete and functional.**

- Intent routing via LLM (gemma2:2b via Ollama)
- Appointment booking, cancellation, and rescheduling (multi-turn)
- Lab report lookup by phone number
- Billing inquiry with insurance breakdown
- General FAQ via RAG (Pinecone + mxbai-embed-large embeddings)
- Emergency keyword detection (bypasses LLM, instant transfer)
- Session state managed in Redis (30-min TTL)
- Patient records stored in Supabase

## Architecture

```
POST /chat
  └── VoiceAgent
        ├── Router          — classifies intent (Appointment / Lab / Billing / Other / CallEnd / Emergency)
        ├── AppointmentAgent — book, cancel, reschedule (sub-agents)
        ├── LabReportAgent
        ├── BillingAgent
        └── FrontDeskAgent  — RAG over hospital FAQ (Pinecone)
```

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) running locally with `gemma2:2b` and `mxbai-embed-large` pulled
- Redis running on `localhost:6379`
- Supabase project with tables: `patients`, `doctors`, `appointments`, `lab_reports`, `bills`, `audit_logs`
- Pinecone index populated via `Agents/FrontDesk_Agent/ingest.py`

## Setup

```bash
cd V1-Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_KEY, PINECONE_API_KEY, PINECONE_INDEX
```

## Testing

**Option 1 — CLI (no server needed):**
```bash
python voice_agent.py
```
Runs an interactive terminal session directly against the agent logic.

**Option 2 — API test client (requires server running):**
```bash
# Terminal 1: start the server
uvicorn main:app --reload --port 8000

# Terminal 2: run the interactive test client
python test_client.py
```
`test_client.py` simulates a full multi-turn phone call — it starts a session, prints the greeting, and lets you type messages until the call ends.

## Known Limitations

- `gemma2:2b` struggles with slot selection edge cases (~67% accuracy) and new-patient DOB parsing (~50%)
- "Yes, cancel it" can occasionally be misread as a call-end intent
- LLM sometimes hallucinates `time_preference` from relative dates like "next Monday"
