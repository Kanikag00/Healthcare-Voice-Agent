import ollama
import json
import os
from dotenv import load_dotenv
from database import Database
from session_manager import Session_Manager

load_dotenv()


class LabReportAgent:
    def __init__(self):
        self.model = os.getenv("LLM_MODEL", "gemma2:2b")
        self.db = Database()
        self.session_manager = Session_Manager()

    def handle_request(self, session_id, patient_message):
        print(f"LAB REPORT AGENT CALLED with: {patient_message}")

        session = self.session_manager.get_session(session_id)
        state = session.get("state", "INITIAL")

        if state == "INITIAL":
            return self._handle_initial(session_id, session, patient_message)
        elif state == "AWAITING_PHONE_NUMBER":
            return self._handle_alternate_phone(session_id, patient_message)
        elif state == "AWAITING_TEST_SELECTION":
            return self._handle_test_selection(session_id, session, patient_message)
        elif state == "AWAITING_NO_REPORT_CHOICE":
            return self._handle_no_report_choice(session_id, patient_message)

        return self._generate_response("Something went wrong. Please contact our lab desk directly.")

    def _handle_initial(self, session_id, session, patient_message):
        phone_number = session.get("phone_number")
        patient, reports = self.db.get_lab_reports_by_phone(phone_number)

        if not patient:
            self.session_manager.update_session(session_id, state="AWAITING_PHONE_NUMBER")
            return self._generate_response(
                "The patient could not be found using their current phone number. "
                "Ask them politely to provide the phone number they registered with."
            )

        return self._respond_with_reports(session_id, patient, reports, patient_message)

    def _handle_alternate_phone(self, session_id, patient_message):
        phone_number = self._extract_phone_number(patient_message)

        if phone_number:
            patient, reports = self.db.get_lab_reports_by_phone(phone_number)
            if patient and reports:
                return self._respond_with_reports(session_id, patient, reports)

        # Still no reports found — inform and give options
        self.session_manager.update_session(session_id, state="AWAITING_NO_REPORT_CHOICE")
        return self._generate_response(
            "No lab reports were found with this number either. "
            "Inform the patient: if their test was done within the last 24 hours, results may not be uploaded yet and they should check back tomorrow. "
            "Then ask: would they like to speak to the front desk, or are they all set, or do they need help with something else?"
        )

    def _handle_no_report_choice(self, session_id, patient_message):
        choice = self._classify_no_report_choice(patient_message)
        self.session_manager.update_session(session_id, state="COMPLETED")

        if choice == "frontdesk":
            return "TRANSFER_TO_FRONTDESK"
        elif choice == "done":
            return self._generate_response("Patient said they are done. Wish them well briefly.")
        else:
            return self._generate_response("Patient needs help with something else. Acknowledge warmly and ask how you can assist them.")

    def _classify_no_report_choice(self, patient_message):
        prompt = f"""The patient said: "{patient_message}"
They were asked if they want to speak to the front desk, are done/finished, or need help with something else.

Return ONLY raw JSON with one of these exact values:
- "frontdesk": patient wants to be transferred or speak to a receptionist
- "done": patient is satisfied and finished (goodbye, nothing else, all set, thanks)
- "something_else": patient needs help with a different topic (booking, billing, hours, any other question)

Examples:
"Connect me to someone" -> {{"choice": "frontdesk"}}
"Nothing else, goodbye" -> {{"choice": "done"}}
"I'm all set, thanks" -> {{"choice": "done"}}
"Can you help me book an appointment?" -> {{"choice": "something_else"}}
"What are your visiting hours?" -> {{"choice": "something_else"}}

No markdown, no extra text."""
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0.1, "num_predict": 50}
            )
            result = json.loads(response["message"]["content"].strip())
            return result.get("choice", "something_else")
        except Exception as e:
            print(f"Error classifying choice: {e}")
            return "something_else"

    def _respond_with_reports(self, session_id, patient, reports, patient_message=None):
        if not reports:
            self.session_manager.update_session(session_id, state="AWAITING_PHONE_NUMBER")
            return self._generate_response(
                f"No lab reports found for {patient['first_name']} with this number. "
                "Ask them if they may have registered with a different phone number."
            )

        if len(reports) == 1:
            self.session_manager.update_session(session_id, state="COMPLETED")
            return self._format_status(reports[0], patient)

        # Multiple reports — try to pre-match from initial message before asking
        if patient_message:
            pre_selected = self._identify_report(patient_message, reports)
            if pre_selected:
                self.session_manager.update_session(session_id, state="COMPLETED")
                return self._format_status(pre_selected, patient)

        # Could not match from message — ask which test
        test_names = ", ".join([r["test_name"] for r in reports])
        self.session_manager.update_session(
            session_id,
            state="AWAITING_TEST_SELECTION",
            lab_reports=reports
        )
        return self._generate_response(
            f"{patient['first_name']} has {len(reports)} lab reports: {test_names}. "
            "Ask them which test they would like to check."
        )

    def _handle_test_selection(self, session_id, session, patient_message):
        reports = session.get("lab_reports", [])
        selected = self._identify_report(patient_message, reports)

        self.session_manager.update_session(session_id, state="COMPLETED")

        if not selected:
            return self._generate_response(
                "Could not identify which test the patient is referring to. "
                "Politely ask them to say the test name again."
            )

        return self._format_status(selected)

    def _format_status(self, report, patient=None):
        name = report["test_name"]
        status = report["status"]
        expected = report.get("expected_ready_date") or "not yet confirmed"
        result = report.get("result_summary") or "not available yet"
        patient_name = patient["first_name"] if patient else "the patient"

        context = f"""You are a hospital receptionist on a phone call.
Give {patient_name} a warm, concise update about their lab report. Keep it under 3 sentences.

Report details:
- Test: {name}
- Status: {status}
- Expected ready date: {expected}
- Result summary: {result}

Status meanings:
- pending: sample not yet collected, ask them to visit the lab
- sample_collected: sample received, being sent to lab
- processing: being analyzed, mention expected ready date
- ready: report available, mention result summary if present, ask them to collect from lab"""

        return self._generate_response(context)

    def _generate_response(self, context):
        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a warm, professional hospital receptionist on a voice call. Keep responses brief and conversational."},
                    {"role": "user", "content": context}
                ],
                options={"temperature": 0.3, "num_predict": 200}
            )
            return response["message"]["content"].strip()
        except Exception as e:
            print(f"Error generating response: {e}")
            return "I'm having trouble retrieving that information. Please contact our lab desk directly."

    def _extract_phone_number(self, patient_message):
        prompt = f"""Extract the phone number from this message: "{patient_message}"
Return ONLY raw JSON: {{"phone_number": "the number as-is, or null if no number found"}}
No markdown, no extra text."""
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0.1, "num_predict": 50}
            )
            result = json.loads(response["message"]["content"].strip())
            return result.get("phone_number")
        except Exception as e:
            print(f"Error extracting phone number: {e}")
            return None

    def _identify_report(self, patient_message, reports):
        test_names = [r["test_name"] for r in reports]
        prompt = f"""The patient said: "{patient_message}"
Available tests: {json.dumps(test_names)}
Which test is the patient asking about? Return ONLY raw JSON: {{"test_name": "exact name from the list, or null if unclear"}}
No markdown, no extra text."""
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0.1, "num_predict": 50}
            )
            result = json.loads(response["message"]["content"].strip())
            test_name = result.get("test_name")
            if not test_name:
                return None
            for report in reports:
                if report["test_name"].lower() == test_name.lower():
                    return report
        except Exception as e:
            print(f"Error identifying report: {e}")
        return None
