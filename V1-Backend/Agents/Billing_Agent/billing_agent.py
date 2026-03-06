import ollama
import json
import os
from dotenv import load_dotenv
from database import Database
from session_manager import Session_Manager

load_dotenv()


class BillingAgent:
    def __init__(self):
        self.model = os.getenv("LLM_MODEL", "gemma2:2b")
        self.db = Database()
        self.session_manager = Session_Manager()

    def handle_request(self, session_id, patient_message):
        print(f"BILLING AGENT CALLED with: {patient_message}")

        session = self.session_manager.get_session(session_id)
        state = session.get("state", "INITIAL")

        if state == "INITIAL":
            return self._handle_initial(session_id, session, patient_message)
        elif state == "AWAITING_BILL_SELECTION":
            return self._handle_bill_selection(session_id, session, patient_message)

        return self._generate_response("Something went wrong. Please contact our billing desk directly.")

    def _handle_initial(self, session_id, session, patient_message):
        phone_number = session.get("phone_number")
        patient, bills = self.db.get_bills_by_phone(phone_number)

        if not patient:
            self.session_manager.update_session(session_id, state="COMPLETED")
            return self._generate_response(
                "The patient could not be found in our system. "
                "Apologize and ask them to contact our billing desk directly for assistance."
            )

        if not bills:
            self.session_manager.update_session(session_id, state="COMPLETED")
            return self._generate_response(
                f"No billing records found for {patient['first_name']}. "
                "Let them know there are no outstanding bills on file and suggest they contact billing if they believe this is an error."
            )

        if len(bills) == 1:
            self.session_manager.update_session(session_id, state="COMPLETED")
            return self._format_bill(bills[0], patient)

        # Multiple bills — try to pre-match from initial message
        if patient_message:
            pre_selected = self._identify_bill(patient_message, bills)
            if pre_selected:
                self.session_manager.update_session(session_id, state="COMPLETED")
                return self._format_bill(pre_selected, patient)

        # Could not match — ask which bill
        descriptions = ", ".join([f"{b['description']} ({b['bill_date']})" for b in bills])
        self.session_manager.update_session(
            session_id,
            state="AWAITING_BILL_SELECTION",
            bills=bills
        )
        return self._generate_response(
            f"{patient['first_name']} has {len(bills)} bills on file: {descriptions}. "
            "Ask which one they would like information about."
        )

    def _handle_bill_selection(self, session_id, session, patient_message):
        bills = session.get("bills", [])
        selected = self._identify_bill(patient_message, bills)

        self.session_manager.update_session(session_id, state="COMPLETED")

        if not selected:
            return self._generate_response(
                "Could not identify which bill the patient is referring to. "
                "Politely ask them to mention the procedure name or date."
            )

        return self._format_bill(selected)

    def _format_bill(self, bill, patient=None):
        patient_name = patient["first_name"] if patient else "the patient"
        total = bill.get("total_amount", 0)
        paid = bill.get("paid_amount", 0)
        insurance_paid = bill.get("insurance_paid_amount", 0) or 0
        coverage_pct = bill.get("insurance_coverage_percent")
        status = bill.get("status")
        description = bill.get("description")
        due_date = bill.get("due_date") or "not set"
        claim_id = bill.get("insurance_claim_id")

        outstanding = total - paid - insurance_paid

        context = f"""You are a hospital receptionist on a phone call giving {patient_name} a billing update.
Keep it warm, clear, and under 4 sentences. Use Indian Rupees (₹).

Bill details:
- Procedure: {description}
- Total bill: ₹{total:,.0f}
- Status: {status}
- Insurance claim ID: {claim_id or "none"}
- Insurance coverage: {coverage_pct}% (₹{insurance_paid:,.0f} paid by insurance)
- Patient paid: ₹{paid:,.0f}
- Outstanding balance: ₹{outstanding:,.0f}
- Due date: {due_date}

Status meanings:
- unpaid: nothing paid yet, mention due date
- partially_paid: patient has paid some, mention outstanding balance
- paid: fully settled, confirm and thank them
- insurance_pending: insurance claim filed, waiting for approval, ask patient to wait

If outstanding is 0 or status is paid, confirm it is fully settled."""

        return self._generate_response(context)

    def _identify_bill(self, patient_message, bills):
        descriptions = [b["description"] for b in bills]
        prompt = f"""The patient said: "{patient_message}"
Available bills: {json.dumps(descriptions)}
Which bill is the patient asking about? Return ONLY raw JSON: {{"description": "exact name from the list, or null if unclear"}}
No markdown, no extra text."""
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0.1, "num_predict": 50}
            )
            result = json.loads(response["message"]["content"].strip())
            desc = result.get("description")
            if not desc:
                return None
            for bill in bills:
                if bill["description"].lower() == desc.lower():
                    return bill
        except Exception as e:
            print(f"Error identifying bill: {e}")
        return None

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
            return "I'm having trouble retrieving that information. Please contact our billing desk directly."
