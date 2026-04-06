import requests
import uuid

BASE_URL = "http://localhost:8000"
session_id = str(uuid.uuid4())
phone_number = "+91-98765-00197"

print("=== Healthcare Voice Agent (API Test) ===")
print(f"Session ID: {session_id}\n")

# Start the call — triggers greeting
resp = requests.post(f"{BASE_URL}/start", json={
    "session_id": session_id,
    "phone_number": phone_number
})
data = resp.json()
print(f"Agent: {data['response']}\n")

# Keep chatting until the call ends
while not data.get("end_call"):
    message = input("You: ").strip()
    if not message:
        continue

    resp = requests.post(f"{BASE_URL}/chat", json={
        "session_id": session_id,
        "phone_number": phone_number,
        "message": message
    })
    data = resp.json()
    print(f"\nAgent: {data['response']}\n")

print("--- Call ended ---")