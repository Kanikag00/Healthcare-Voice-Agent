import sys, os
import numpy as np
import sounddevice as sd
import uuid

# path to Backend so we can import main_graph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Backend", "Agents", "Appointment_Agent"))

from stt import WhisperSTT
from tts import KokoroTTS

SAMPLE_RATE      = 16000   # Whisper expects 16kHz
CHUNK_DURATION   = 0.1     # 100ms chunks while recording
SILENCE_THRESHOLD = 0.01   # RMS below this = silence
SILENCE_CUTOFF   = 1.5     # seconds of silence → stop recording


def record_until_silence() -> np.ndarray:
    chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION)
    recorded      = []
    silent_chunks = 0
    max_silent    = int(SILENCE_CUTOFF / CHUNK_DURATION)  # 15 chunks

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32') as stream:
        print("🎤 Listening...", flush=True)
        while True:
            chunk, _ = stream.read(chunk_samples)
            chunk = chunk.flatten()
            recorded.append(chunk)

            rms = np.sqrt(np.mean(chunk ** 2))
            if rms < SILENCE_THRESHOLD:
                silent_chunks += 1
            else:
                silent_chunks = 0  # reset on any speech

            # only stop after at least some speech was recorded
            if silent_chunks >= max_silent and len(recorded) > max_silent:
                break

    return np.concatenate(recorded)


def run(phone_number: str = "9873892000"):
    # ── lazy import so graph only loads when run() is called ──
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command
    from main_graph import graph

    stt    = WhisperSTT(model_size="turbo")
    tts    = KokoroTTS()
    memory = MemorySaver()
    compiled = graph.compile(checkpointer=memory)
    config   = {"configurable": {"thread_id": f"voice-{uuid.uuid4().hex[:8]}"}}

    def get_agent_msg(result):
        snapshot = compiled.get_state(config)
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            return snapshot.tasks[0].interrupts[0].value
        return result.get("response", "")

    print("\n" + "=" * 50)
    print("  Healthcare Voice Agent — Voice Mode")
    print("  Press Ctrl+C to end the call")
    print("=" * 50 + "\n")

    # ── Opening greeting ──────────────────────────────
    opening = "Hello! Welcome to the hospital. Please let me know how I can help you."
    print(f"Agent  : {opening}\n")
    tts.speak(opening)
    # ─────────────────────────────────────────────────

    def has_pending_interrupt() -> bool:
        snapshot = compiled.get_state(config)
        return bool(snapshot.tasks and snapshot.tasks[0].interrupts)

    first_turn = True

    while True:
        # 1. Record patient speech
        audio = record_until_silence()

        # 2. Transcribe
        transcript = stt.transcribe(audio)
        if not transcript:
            print("  (no speech detected, listening again...)\n")
            continue
        print(f"Patient: {transcript}", flush=True)

        # 3. Send to graph
        # Use Command(resume=...) only when the graph is paused at an interrupt.
        # After a flow completes (e.g. appointment booked), no interrupt is pending,
        # so the next message must start a fresh invocation through the router.
        try:
            if not first_turn and has_pending_interrupt():
                result = compiled.invoke(Command(resume=transcript), config)
            else:
                result = compiled.invoke(
                    {"patient_message": transcript, "phone_number": phone_number},
                    config,
                )
                first_turn = False
        except KeyboardInterrupt:
            print("\n(Call interrupted)")
            break

        # 4. Get response text
        agent_msg = get_agent_msg(result)
        if not agent_msg:
            continue
        print(f"Agent  : {agent_msg}\n", flush=True)

        # 5. Speak — mic stays off while agent is speaking
        tts.speak(agent_msg)

        # 6. End call if graph signals it
        if result.get("end_call"):
            print("(Call ended)\n")
            break


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--phone", default="9873892000")
    args = parser.parse_args()
    run(phone_number=args.phone)
