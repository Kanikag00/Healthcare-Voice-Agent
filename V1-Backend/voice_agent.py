from Agents.router import Router
from Agents.Appointment_Agent.appointment_agent import AppointmentAgent
from Agents.FrontDesk_Agent.frontdesk_agent import FrontDeskAgent
from Agents.Lab_Report_Agent.lab_report_agent import LabReportAgent
from Agents.Billing_Agent.billing_agent import BillingAgent
from database import Database
import json
from session_manager import Session_Manager

EMERGENCY_KEYWORDS = [
    "chest pain", "heart attack", "cardiac arrest", "can't breathe", "cannot breathe",
    "difficulty breathing", "breathless", "choking", "unconscious", "not breathing",
    "severe bleeding", "heavy bleeding", "stroke", "paralysis", "seizure", "convulsion",
    "overdose", "poisoning", "anaphylaxis", "allergic reaction", "severe pain",
    "head injury", "broken bone", "fracture", "accident", "fell down", "fainted",
    "collapsed", "high fever", "unresponsive", "emergency"
]


class VoiceAgent:
    def __init__(self):
        self.router = Router()
        self.appointment_agent = AppointmentAgent()
        self.frontdesk_agent = FrontDeskAgent()
        self.lab_report_agent = LabReportAgent()
        self.billing_agent = BillingAgent()
        self.db = Database()
        self.session_manager = Session_Manager()

    def start_call(self, session_id, phone_number):
        self.session_manager.create_session(session_id, phone_number)
        return {
            "response": "Thank you for calling City General Hospital. I'm your virtual assistant. How can I help you today?",
            "end_call": False
        }

    def process_request(self, session_id, phone_number, patient_message):

        print("processing request - ", patient_message)

        session = self.session_manager.get_session(session_id)
        if session is None:
            session = self.session_manager.create_session(session_id, phone_number)

        # Keyword-based emergency check — bypass LLM router for safety-critical terms
        if any(keyword in patient_message.lower() for keyword in EMERGENCY_KEYWORDS):
            self.session_manager.delete_session(session_id)
            return {
                "response": "Transferring you to our emergency ward now. Please stay on the line.",
                "end_call": True
            }

        # Always classify the new message
        classification = self.router.requirement(patient_message)
        new_intent = classification.get("requirement")
        confidence = classification.get("confidence", 0.0)
        summary = classification.get("summary", "")
            

        # If it's a call-ending or emergency intent, respect it immediately
        if new_intent in ("CallEnd", "Emergency"):
            intent = new_intent
        elif session["current_intent"] is not None:
            # Mid-flow — keep using the saved intent
            intent = session["current_intent"]
        else:
            # First message or no active flow — use the new classification
            intent = new_intent
            self.session_manager.update_session(session_id, current_intent=intent)

        # CallEnd — patient wants to hang up
        if intent == "CallEnd":
            self.session_manager.delete_session(session_id)
            return {"response": "Thank you for calling! Have a great day.", "end_call": True}

        # Route to agent
        elif intent == "Appointment":
            agent_response = self.appointment_agent.handle_request(session_id, patient_message)

            # If appointment flow completed, reset all appointment state so next booking starts fresh
            session = self.session_manager.get_session(session_id)
            if session and session.get("state") == "COMPLETED":
                self.session_manager.update_session(
                    session_id,
                    current_intent=None,
                    state="INITIAL",
                    sub_action=None,
                    appointment_details=None,
                    available_slots=[],
                    selected_slot=None
                )

            return {"response": agent_response, "end_call" : False}

        elif intent == "Lab Report":
            agent_response = self.lab_report_agent.handle_request(session_id, patient_message)

            session = self.session_manager.get_session(session_id)
            if session and session.get("state") == "COMPLETED":
                self.session_manager.update_session(session_id, current_intent=None, state="INITIAL")

            # Agent signals transfer to frontdesk when patient not found
            if agent_response == "TRANSFER_TO_FRONTDESK":
                return {
                    "response": "I wasn't able to locate your records. Let me connect you to our front desk for assistance.",
                    "end_call": False
                }

            return {"response": agent_response, "end_call": False}

        elif intent == "Billing":
            agent_response = self.billing_agent.handle_request(session_id, patient_message)

            session = self.session_manager.get_session(session_id)
            if session and session.get("state") == "COMPLETED":
                self.session_manager.update_session(session_id, current_intent=None, state="INITIAL")

            return {"response": agent_response, "end_call": False}

        elif intent == "Other":
            agent_response = self.frontdesk_agent.handle_request(session_id, patient_message)
            # Single-turn Q&A — reset intent so next message goes through router fresh
            self.session_manager.update_session(session_id, current_intent=None)
            return {"response": agent_response, "end_call": False}

        else:
            return {
                "response": "I'd be happy to help you with that. Let me connect you with our front desk who can better assist with your question. Please hold for a moment.",
                "end_call": True
            }


if __name__ == "__main__":
    voice_agent = VoiceAgent()
    session_id = "test-session-004"
    phone_number = "+91-98765-00197"

    print("=== Healthcare Voice Agent Test ===")
    print("Type your messages below. Say 'bye' or 'that's it' to end.\n")

    while True:
        patient_message = input("Patient: ")
        if not patient_message.strip():
            continue

        response = voice_agent.process_request(session_id, phone_number, patient_message)
        print(f"\nAgent: {response.get('response', response)}\n")

        if response.get("end_call") is True:
            break
