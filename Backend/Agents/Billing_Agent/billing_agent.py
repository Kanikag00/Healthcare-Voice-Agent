import json
import ollama
import os
from dotenv import load_dotenv
from database import Database
from state import AgentState
from langgraph.types import interrupt

load_dotenv()

db = Database()
_MODEL = os.getenv("LLM_MODEL", "gemma2:2b")


# -----------NODE 1-------------
def billing_lookup_node(state: AgentState, generate_response) -> AgentState:
    """Looks up patient bills. If multiple bills and ambiguous, interrupts to ask which one."""

    phone_number = state.get("phone_number")
    patient, bills = db.get_bills_by_phone(phone_number)

    if not patient:
        response = generate_response(
            "The patient could not be found in our system. "
            "Apologize and ask them to contact our billing desk directly for assistance."
        )
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "state": "COMPLETED", "response": response}

    if not bills:
        response = generate_response(
            f"No billing records found for {patient['first_name']}. "
            "Let them know there are no outstanding bills on file and suggest they contact billing if they believe this is an error."
        )
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "state": "COMPLETED", "response": response}

    if len(bills) == 1:
        response = _format_bill(bills[0], patient, generate_response)
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "state": "COMPLETED", "response": response}

    # Multiple bills — try to pre-match from the initial patient message
    pre_selected = _identify_bill(state["patient_message"], bills)
    if pre_selected:
        response = _format_bill(pre_selected, patient, generate_response)
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "state": "COMPLETED", "response": response}

    # Could not match — ask which bill
    descriptions = ", ".join([f"{b['description']} ({b['bill_date']})" for b in bills])
    response = generate_response(
        f"{patient['first_name']} has {len(bills)} bills on file: {descriptions}. "
        "Ask which one they would like information about."
    )
    patient_message = interrupt(response)
    return {
        **state,
        "bills": bills,
        "patient_message": patient_message,
        "state": "AWAITING_BILL_SELECTION",
        "response": response,
    }


# -----------NODE 2-------------
def billing_select_node(state: AgentState, generate_response) -> AgentState:
    """Identifies which bill the patient is referring to and presents the details."""

    bills = state.get("bills", [])
    selected = _identify_bill(state["patient_message"], bills)

    if not selected:
        response = generate_response(
            "Could not identify which bill the patient is referring to. "
            "Politely ask them to mention the procedure name or date."
        )
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "response": response}

    response = _format_bill(selected, None, generate_response)
    return {**state, "state": "COMPLETED", "response": response}


# -----------HELPERS-------------
def _format_bill(bill, patient, generate_response):
    patient_name = patient["first_name"] if patient else "the patient"
    total = bill.get("total_amount", 0)
    paid = bill.get("paid_amount", 0)
    insurance_paid = bill.get("insurance_paid_amount") or 0
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

    return generate_response(context)


def _identify_bill(patient_message, bills):
    descriptions = [b["description"] for b in bills]
    prompt = f"""The patient said: "{patient_message}"
Available bills: {json.dumps(descriptions)}
Which bill is the patient asking about?
IMPORTANT: If the patient says "I'm not sure", "I don't know", or is unclear, return null.
Return ONLY raw JSON: {{"description": "exact name from the list, or null if unclear"}}
No markdown, no extra text."""
    try:
        response = ollama.chat(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.1, "num_predict": 50},
        )
        result = json.loads(response.message.content.strip())
        desc = result.get("description")
        if not desc:
            return None
        for bill in bills:
            if bill["description"].lower() == desc.lower():
                return bill
    except Exception as e:
        print(f"Error identifying bill: {e}")
    return None
