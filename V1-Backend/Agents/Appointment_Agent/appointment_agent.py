import ollama
import json
import os
from dotenv import load_dotenv
from .book import handle_book
from .cancel import handle_cancel
from .reschedule import handle_reschedule
from session_manager import Session_Manager
from database import Database

load_dotenv()


class AppointmentAgent:
    def __init__(self):
        self.model = os.getenv("LLM_MODEL", "gemma2:2b")
        self.session_manager = Session_Manager()
        self.db = Database()

    def handle_request(self, session_id, patient_message):

        print("APPOINTMENT AGENT CAlLED with patient message : ", patient_message)

        session = self.session_manager.get_session(session_id)

        if session["state"] == "INITIAL":

            # First time in appointment flow — add appointment data to session
            if session.get("sub_action") is None:
                session = self.session_manager.add_appointment_data(session_id)

            # Extract details from current message (pass existing details for context)
            details = self.get_appointment_details(patient_message, session.get("appointment_details"))
            print("DETAILS extracted : ", details)

            # Merge: only overwrite if new value is meaningful
            # (skip both None — field missing from LLM response — and "not mentioned")
            sub_action = details.get("sub_action")
            if sub_action is not None and sub_action != "not mentioned":
                session["sub_action"] = sub_action

            appt = session["appointment_details"]
            for field in ["specialty", "preferred_date", "time_preference"]:
                new_val = details.get(field)
                if new_val is not None and new_val != "not mentioned":
                    appt[field] = new_val

            doctor = details.get("doctor_name")
            if doctor is not None and doctor != "not mentioned":
                appt["doctor_name"] = doctor

            # Fallback: if LLM missed date/time, try parsing from the message directly
            if appt.get("preferred_date") is None or appt.get("time_preference") is None:
                fallback = self._fallback_date_time_extract(patient_message)
                if appt.get("preferred_date") is None and fallback.get("preferred_date"):
                    appt["preferred_date"] = fallback["preferred_date"]
                if appt.get("time_preference") is None and fallback.get("time_preference"):
                    appt["time_preference"] = fallback["time_preference"]

            # Fallback: if LLM missed specialty, scan message for known department keywords
            if appt.get("specialty") is None and appt.get("doctor_name") is None:
                appt["specialty"] = self._fallback_specialty_extract(patient_message)

            # Save merged data back to Redis
            self.session_manager.update_session(
                session_id,
                sub_action=session["sub_action"],
                appointment_details=appt
            )

        # Route based on sub_action (works for both INITIAL and follow-up states)
        if session["sub_action"] == "cancel":
            return handle_cancel(session_id, patient_message, self.generate_response, self.extract_info)

        elif session["sub_action"] == "reschedule":
            return handle_reschedule(session_id, patient_message, self.generate_response, self.extract_info)

        elif session["sub_action"] == "book":
            return handle_book(session_id, patient_message, self.generate_response, self.extract_info)

    def _fallback_date_time_extract(self, message):
        """Code-level fallback for when the LLM fails to extract date/time from simple inputs like 'friday' or 'morning'."""
        import parsedatetime
        from datetime import datetime

        result = {}
        msg = message.strip().lower()

        # Check if it's a time period
        time_periods = {"morning", "afternoon", "evening"}
        words = msg.split()

        time_found = None
        date_found = None

        for word in words:
            if word in time_periods:
                time_found = word

        # Strip time words before parsing date so "tomorrow morning" → parse "tomorrow" only
        date_words = [w for w in words if w not in time_periods]
        date_msg = " ".join(date_words) if date_words else msg
        cal = parsedatetime.Calendar()
        time_struct, status = cal.parse(date_msg)
        if status in (1, 3):  # 1=date, 3=datetime
            date_found = date_msg

        if date_found:
            result["preferred_date"] = date_found
        if time_found:
            result["time_preference"] = time_found

        return result

    def _correct_slot_time(self, time_str, patient_message):
        """Use parsedatetime to verify/correct time extracted by LLM from patient message.
        Fixes cases like gemma2:2b returning '14:00' when patient said '1PM' (should be '13:00').
        """
        import parsedatetime
        from datetime import datetime
        cal = parsedatetime.Calendar()
        time_struct, status = cal.parse(patient_message)
        if status in (2, 3):  # parsed a time or datetime
            parsed = datetime(*time_struct[:6])
            return parsed.strftime("%H:%M")
        return time_str

    def _fallback_specialty_extract(self, message):
        """Keyword scan for specialty when LLM fails to extract it."""
        SPECIALTY_KEYWORDS = {
            "cardiology": "cardiology", "cardiologist": "cardiology", "cardiac": "cardiology", "heart": "cardiology",
            "dermatology": "dermatology", "dermatologist": "dermatology", "skin": "dermatology",
            "neurology": "neurology", "neurologist": "neurology", "neuro": "neurology", "brain": "neurology",
            "orthopedics": "orthopedics", "orthopedic": "orthopedics", "ortho": "orthopedics", "bone": "orthopedics", "knee": "orthopedics", "joint": "orthopedics",
            "pediatrics": "pediatrics", "pediatrician": "pediatrics", "child": "pediatrics", "children": "pediatrics",
            "general medicine": "general medicine", "general physician": "general medicine", "gp": "general medicine",
        }
        msg = message.lower()
        for keyword, specialty in SPECIALTY_KEYWORDS.items():
            if keyword in msg:
                return specialty
        return None

    def get_appointment_details(self, patient_message, existing_details=None):
        context = ""
        if existing_details:
            filled = {k: v for k, v in existing_details.items() if v is not None}
            missing = [k for k, v in existing_details.items() if v is None]
            if filled or missing:
                examples = []
                if "preferred_date" in missing:
                    examples.append('If the patient says any date or any day of the week like "thursday" or "Monday" or "tomorrow", return preferred_date as that value.')
                if "time_preference" in missing:
                    examples.append('If the patient says the exact time or parts of the day (like "morning", "afternoon", "evening", "10 AM", "3 PM") or "not mentioned", return time_preference as that value.')
                if "specialty" in missing:
                    examples.append('If the patient says "dermatologist" or "cardiologist", return specialty as the department name.')

                context = (
                    f"\n\nCONTEXT: We are in a multi-turn conversation. "
                    f"We already know: {json.dumps(filled) if filled else 'nothing yet'}. "
                    f"We are still missing: {', '.join(missing)}. "
                    f"The patient's message is likely answering one of the missing fields. "
                    f"{' '.join(examples)}"
                )

        prompt = f"""Extract appointment details from this patient message: "{patient_message}"
                Return JSON with these 5 fields:
                - "sub_action": "book", "reschedule", or "cancel"
                - "doctor_name": doctor name or "not mentioned"
                - "specialty": department name (cardiology, dermatology, pediatrics, neurology, orthopedics, general medicine) or "not mentioned"
                - "preferred_date": the date or any day of week or reference of day (like "tomorrow", "Monday", "next Friday", "Feb 20") or "not mentioned"
                - "time_preference": the exact time or parts of the day (like "morning", "afternoon", "evening", "10 AM", "3 PM") or "not mentioned"

                IMPORTANT: Split date and time into separate fields.
                "Tuesday morning" → preferred_date: "Tuesday", time_preference: "morning"
                "tomorrow at 3 PM" → preferred_date: "tomorrow", time_preference: "3 PM"
                "next Monday evening" → preferred_date: "next Monday", time_preference: "evening"
                "morning" → preferred_date: "not mentioned", time_preference: "morning"
                "afternoon" → preferred_date: "not mentioned", time_preference: "afternoon"
                "Wednesday" → preferred_date: "Wednesday", time_preference: "not mentioned"

                If patient says "cardiologist", return specialty as "cardiology" (use department name, not doctor title).{context}"""
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0.1, "num_predict": 300}
            )
            text = response["message"]["content"].strip()
            result = json.loads(text)
            print("EXTRACTED DETAILS: ", result)
            return result

        except Exception as e:
            print(f"Error classifying intent: {e}")
            return {
                "sub_action": "not mentioned",
                "doctor_name": "not mentioned",
                "specialty": "not mentioned",
                "preferred_date": "not mentioned",
                "time_preference": "not mentioned"
            }   

    def generate_response(self, prompt):
        """Generic LLM response generator. Takes a prompt, returns a natural response."""
        print("GENERATE RESPONSE CALLED: ")
        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a warm, professional hospital receptionist. Address the patient as 'you'. NEVER use placeholders like [Patient Name] or [List]. Do NOT start your response with a greeting like 'Hello' or 'Hi'."},
                    {"role": "user", "content": prompt}
                ],
                options={"temperature": 0.3, "num_predict": 800}
            )
            agent_response = response["message"]["content"].strip()
            print("AGENT RESPONSE : ", agent_response)
            return agent_response

        except Exception as e:
            print(f"Error generating response: {e}")
            return "I apologize, I'm having trouble processing your request. Would you like me to transfer you to our scheduling desk?"

    def extract_info(self, patient_message, session):
        """Context-aware extraction. Reads session state to determine what to extract from the patient message."""
        state = session.get("state")
        print(f"EXTRACT_INFO called for state: {state}")

        prompts = {
            "AWAITING_SLOT_SELECTION": (
                f'The patient said: "{patient_message}"\n'
                f'Here are the available slots:\n{json.dumps(session.get("available_slots", []), indent=2)}\n\n'
                f'Is the patient clearly picking one of the slots above, OR are they asking for different options '
                f'(different date, different time, different doctor)?\n\n'
                f'If they are PICKING a slot, return ONLY raw JSON:\n'
                f'{{"doctor_name": "...", "doctor_id": "...", "date": "...", "time": "HH:MM"}}\n'
                f'The time must be in HH:MM format (pick the start of a 30-min block).\n\n'
                f'If they want DIFFERENT OPTIONS (different day, time, or doctor), return:\n'
                f'{{"change_preference": true}}\n\n'
                f'IMPORTANT — return change_preference for ANY of these:\n'
                f'- They mention a day/date not in the slots above (e.g. "How about Saturday?" when slots are on Friday)\n'
                f'- They say "none of these work", "different day", "do you have ... slots"\n'
                f'- They ask for a different time period (e.g. "I\'d prefer the afternoon" when only morning slots are listed)\n\n'
                f'If you cannot determine their intent at all, return {{"error": "unclear"}}.\n'
                f'No markdown, no code blocks, no extra text.'
            ),
            "AWAITING_RESCHEDULE_SLOT": (
                f'The patient said: "{patient_message}"\n'
                f'Here are the available slots:\n{json.dumps(session.get("available_slots", []), indent=2)}\n\n'
                f'Is the patient clearly picking one of the slots above, OR are they asking for different options '
                f'(different date, different time, different doctor)?\n\n'
                f'If they are PICKING a slot, return ONLY raw JSON:\n'
                f'{{"doctor_name": "...", "doctor_id": "...", "date": "...", "time": "HH:MM"}}\n'
                f'The time must be in HH:MM format (pick the start of a 30-min block).\n\n'
                f'If they want DIFFERENT OPTIONS (different day, time, or doctor), return:\n'
                f'{{"change_preference": true}}\n\n'
                f'If you cannot determine their intent at all, return {{"error": "unclear"}}.\n'
                f'No markdown, no code blocks, no extra text.'
            ),
            "AWAITING_PATIENT_INFO": (
                f'The patient said: "{patient_message}"\n'
                f'You are an expert medical data extractor. Extract the First Name, Last Name, and Date of Birth into JSON. Return ONLY raw JSON:\n'
                f'- "first_name": patient\'s first name or null\n'
                f'- "last_name": patient\'s last name or null\n'
                f'- "date_of_birth": date of birth in YYYY-MM-DD format or null\n\n'
                f'IMPORTANT: Always convert the date to YYYY-MM-DD format. DD/MM/YYYY means day first then month.\n\n'
                f'Examples:\n'
                f'User: John Doe 15th August 1990\n'
                f'{{"first_name": "John", "last_name": "Doe", "date_of_birth": "1990-08-15"}}\n\n'
                f'User: Ravi Kumar 01/12/1995\n'
                f'{{"first_name": "Ravi", "last_name": "Kumar", "date_of_birth": "1995-12-01"}}\n\n'
                f'User: My name is Anika Singh\n'
                f'{{"first_name": "Anika", "last_name": "Singh", "date_of_birth": null}}\n\n'
                f'User: Date of birth is 1990-06-20\n'
                f'{{"first_name": null, "last_name": null, "date_of_birth": "1990-06-20"}}\n\n'
                f'No markdown, no code blocks, no extra text.'
            ),
            "AWAITING_CANCEL_SELECTION": (
                f'The patient said: "{patient_message}"\n'
                f'Here are their upcoming appointments:\n{json.dumps(session.get("existing_appointments", []), indent=2)}\n\n'
                f'Which appointment is the patient referring to? Return ONLY raw JSON with these fields:\n'
                f'- "appointment_id": the appointment\'s id\n'
                f'- "doctor_name": the doctor\'s name\n'
                f'- "date": the appointment date\n'
                f'- "time": the appointment time\n\n'
                f'If you cannot determine their choice, return {{"error": "unclear"}}.\n'
                f'No markdown, no code blocks, no extra text.'
            ),
            "AWAITING_RESCHEDULE_SELECTION": (
                f'The patient said: "{patient_message}"\n'
                f'Here are their upcoming appointments:\n{json.dumps(session.get("existing_appointments", []), indent=2)}\n\n'
                f'Which appointment is the patient referring to? Return ONLY raw JSON with these fields:\n'
                f'- "appointment_id": the appointment\'s id\n'
                f'- "doctor_name": the doctor\'s name\n'
                f'- "date": the appointment date\n'
                f'- "time": the appointment time\n\n'
                f'If you cannot determine their choice, return {{"error": "unclear"}}.\n'
                f'No markdown, no code blocks, no extra text.'
            ),
            "AWAITING_CANCEL_CONFIRMATION": (
                f'The patient said: "{patient_message}"\n'
                f'Did the patient confirm (yes) or decline (no)?\n'
                f'Return ONLY raw JSON: {{"confirmed": true}} or {{"confirmed": false}}\n'
                f'No markdown, no code blocks, no extra text.'
            ),
            "AWAITING_RESCHEDULE_DETAILS": (
                f'Extract the new appointment preferences from this patient message: "{patient_message}"\n'
                f'Return ONLY raw JSON with these fields:\n'
                f'- "preferred_date": the DATE only (like "tomorrow", "Monday", "next Friday", "Feb 20") or "not mentioned"\n'
                f'- "time_preference": the TIME only (like "morning", "afternoon", "evening", "10 AM", "3 PM") or "not mentioned"\n\n'
                f'IMPORTANT: Split date and time into separate fields.\n'
                f'"Tuesday morning" -> preferred_date: "Tuesday", time_preference: "morning"\n'
                f'"tomorrow at 3 PM" -> preferred_date: "tomorrow", time_preference: "3 PM"\n\n'
                f'No markdown, no code blocks, no extra text.'
            ),
        }

        prompt = prompts.get(state)
        if prompt is None:
            print(f"No extraction needed for state: {state}")
            return None

        # Default fallbacks per state
        fallbacks = {
            "AWAITING_SLOT_SELECTION": None,
            "AWAITING_RESCHEDULE_SLOT": None,
            "AWAITING_PATIENT_INFO": {"first_name": None, "last_name": None, "date_of_birth": None},
            "AWAITING_CANCEL_SELECTION": None,
            "AWAITING_RESCHEDULE_SELECTION": None,
            "AWAITING_CANCEL_CONFIRMATION": False,
            "AWAITING_RESCHEDULE_DETAILS": {"preferred_date": "not mentioned", "time_preference": "not mentioned"},
        }

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.1, "num_predict": 200}
            )
            text = response["message"]["content"].strip()

            if text.startswith('```'):
                lines = text.split('\n')
                text = '\n'.join(lines[1:-1]) if len(lines) > 2 else text[3:]
                text = text.strip()
            if '{' in text and '}' in text:
                text = text[:text.rfind('}') + 1]

            result = json.loads(text)
            print(f"EXTRACT_INFO result: {result}")

            # For confirmation, return the boolean directly
            if state == "AWAITING_CANCEL_CONFIRMATION":
                return result.get("confirmed", False)

            # For selection/slot states, return None if unclear
            if "error" in result:
                return None

            # Correct time for slot selection — LLM (gemma2:2b) sometimes maps "1PM" → "14:00"
            if state in ("AWAITING_SLOT_SELECTION", "AWAITING_RESCHEDULE_SLOT") and result.get("time"):
                corrected = self._correct_slot_time(result["time"], patient_message)
                if corrected != result["time"]:
                    print(f"TIME CORRECTED: {result['time']} → {corrected}")
                    result["time"] = corrected

            return result

        except Exception as e:
            print(f"Error in extract_info for state {state}: {e}")
            return fallbacks.get(state)


if __name__ == "__main__":
    router = AppointmentAgent()
    print(router.get_appointment_details("I wanna see a doctor on Monday Morning"))
