# Healthcare Voice Agent

An AI-powered voice agent for hospital call handling. Patients call in and speak naturally — the agent routes their request, handles the full multi-turn conversation, and responds with synthesized speech.

## Architecture (LangGraph)

```
voice/voice_loop.py          ← voice entry point (mic → STT → graph → TTS)
Backend/main_graph.py        ← LangGraph orchestration
  ├── router_node            — classifies intent via LLM
  ├── appointment subgraph   — book / cancel / reschedule (multi-turn with interrupts)
  ├── billing_lookup/select  — bill lookup and breakdown
  ├── lab_lookup/...         — lab report lookup with phone fallback
  ├── frontdesk              — RAG over hospital FAQ (Pinecone)
  ├── emergency_node         — keyword-triggered, instant transfer
  └── call_end_node          — graceful goodbye
```

## Features

- **Appointment booking, cancellation, rescheduling** — full multi-turn flow with slot selection and new-patient registration
- **Lab report lookup** — by phone number, with alternate number fallback
- **Billing inquiry** — bill identification and itemised breakdown
- **General FAQ** — RAG over hospital knowledge base (Pinecone + `mxbai-embed-large`)
- **Emergency detection** — keyword list bypasses LLM, instant transfer response
- **Voice mode** — mic recording → Whisper transcription → graph → Kokoro TTS playback

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) running locally with the following models pulled:
  ```bash
  ollama pull llama3.1:8b
  ollama pull mxbai-embed-large
  ```
- Supabase project with tables: `patients`, `doctors`, `appointments`, `lab_reports`, `bills`
- Pinecone index populated (see [Ingest FAQ](#ingest-faq))
- For voice mode: a microphone and speaker; `sounddevice` requires PortAudio

## Setup

```bash
cd Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in: SUPABASE_URL, SUPABASE_KEY, PINECONE_API_KEY, PINECONE_INDEX
```

## Running

**Text mode (interactive terminal):**
```bash
cd Backend
source venv/bin/activate
python main_graph.py --phone 9873892000
# optional flags:
#   --debug     print internal state after each turn
#   --thread ID resume a previous session by thread ID
```

**Voice mode (mic + speaker):**
```bash
cd voice
source ../Backend/venv/bin/activate
python voice_loop.py --phone 9873892000
```

## Ingest FAQ

Populate the Pinecone index from `hospital_info.json` before first run:
```bash
cd Backend
python Agents/FrontDesk_Agent/ingest.py
```

# Embedding model comparison for FrontDesk RAG
python Agents/FrontDesk_Agent/benchmark.py
```

## Project Structure

```
Backend/
├── main_graph.py                        # LangGraph graph — entry point
├── state.py                             # AgentState TypedDict
├── database.py                          # Supabase client wrapper
├── Agents/
│   ├── router.py                        # Intent classifier
│   ├── Appointment_Agent/
│   │   ├── appointment_graph.py         # Appointment LangGraph subgraph
│   │   ├── book.py                      # Booking nodes
│   │   ├── modify_appointment.py        # Cancel / reschedule nodes
│   │   ├── prompts.py                   # Dynamic prompt builder
│   │   └── utils.py                     # Date parsing, slot helpers
│   ├── Billing_Agent/billing_agent.py
│   ├── Lab_Report_Agent/lab_report_agent.py
│   └── FrontDesk_Agent/
│       ├── frontdesk_agent.py           # RAG node
│       ├── ingest.py                    # Pinecone ingestion script
│       └── hospital_info.json           # FAQ knowledge base
├── benchmark.py
├── benchmark_v2.py
├── benchmark_conv.py
├── conversation_test.py
├── test_client.py
└── requirements.txt

voice/
├── voice_loop.py   # Main voice loop (record → STT → graph → TTS)
├── stt.py          # WhisperSTT (faster-whisper, turbo model)
└── tts.py          # KokoroTTS (BF Emma voice, 24kHz)
```
