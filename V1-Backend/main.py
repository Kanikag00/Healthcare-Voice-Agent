from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from voice_agent import VoiceAgent

app = FastAPI(title="Healthcare Voice Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

voice_agent = VoiceAgent()


class StartCallRequest(BaseModel):
    session_id: str
    phone_number: str


class ChatRequest(BaseModel):
    session_id: str
    phone_number: str
    message: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/start")
def start_call(req: StartCallRequest):
    try:
        return voice_agent.start_call(req.session_id, req.phone_number)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        return voice_agent.process_request(req.session_id, req.phone_number, req.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))