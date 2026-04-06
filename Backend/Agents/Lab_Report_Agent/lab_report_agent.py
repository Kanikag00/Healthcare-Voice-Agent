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
def lab_lookup_node(state: AgentState, generate_response) -> AgentState:
    """Looks up lab reports by phone. Handles single/multiple/missing reports."""

    phone_number = state.get("phone_number")
    patient, reports = db.get_lab_reports_by_phone(phone_number)

    if not patient:
        response = generate_response(
            "The patient could not be found using their current phone number. "
            "Ask them politely to provide the phone number they registered with."
        )
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "state": "AWAITING_PHONE_NUMBER", "response": response}

    return _respond_with_reports(state, patient, reports, generate_response)


# -----------NODE 2-------------
def lab_alt_phone_node(state: AgentState, generate_response) -> AgentState:
    """Tries an alternate phone number provided by the patient."""

    phone_number = _extract_phone_number(state["patient_message"])

    if phone_number:
        patient, reports = db.get_lab_reports_by_phone(phone_number)
        if patient and reports:
            return _respond_with_reports(state, patient, reports, generate_response)

    # Still no reports found
    response = generate_response(
        "No lab reports were found with this number either. "
        "Inform the patient: if their test was done within the last 24 hours, results may not be uploaded yet and they should check back tomorrow. "
        "Then ask: would they like to speak to the front desk, or are they all set, or do they need help with something else?"
    )
    patient_message = interrupt(response)
    return {**state, "patient_message": patient_message, "state": "AWAITING_NO_REPORT_CHOICE", "response": response}


# -----------NODE 3-------------
def lab_select_test_node(state: AgentState, generate_response) -> AgentState:
    """Identifies which test the patient is asking about."""

    reports = state.get("lab_reports", [])
    selected = _identify_report(state["patient_message"], reports)

    if not selected:
        response = generate_response(
            "Could not identify which test the patient is referring to. "
            "Politely ask them to say the test name again."
        )
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "response": response}

    response = _format_status(selected, None, generate_response)
    return {**state, "state": "COMPLETED", "response": response}


# -----------NODE 4-------------
def lab_no_report_choice_node(state: AgentState, generate_response) -> AgentState:
    """Handles patient's choice after no reports were found (frontdesk / done / something else)."""

    choice = _classify_no_report_choice(state["patient_message"])

    if choice == "frontdesk":
        return {**state, "state": "FRONTDESK", "response": "TRANSFER_TO_FRONTDESK"}

    if choice == "done":
        response = generate_response("Patient said they are done. Wish them well briefly.")
        return {**state, "state": "COMPLETED", "response": response}

    # something_else — interrupt to capture the new request, then re-route
    response = generate_response(
        "Patient wants help with something else. Acknowledge briefly in 1 sentence and ask what they need."
    )
    patient_message = interrupt(response)
    return {**state, "patient_message": patient_message, "state": "ROUTING", "response": response}


# -----------HELPERS-------------
def _respond_with_reports(state, patient, reports, generate_response):
    if not reports:
        response = generate_response(
            f"No lab reports found for {patient['first_name']} with this number. "
            "Ask them if they may have registered with a different phone number."
        )
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "state": "AWAITING_PHONE_NUMBER", "response": response}

    if len(reports) == 1:
        response = _format_status(reports[0], patient, generate_response)
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "state": "COMPLETED", "response": response}

    # Multiple reports — try to pre-match from initial message
    pre_selected = _identify_report(state["patient_message"], reports)
    if pre_selected:
        response = _format_status(pre_selected, patient, generate_response)
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "state": "COMPLETED", "response": response}

    # Could not match — ask which test
    test_names = ", ".join([r["test_name"] for r in reports])
    response = generate_response(
        f"{patient['first_name']} has {len(reports)} lab reports: {test_names}. "
        "Ask them which test they would like to check."
    )
    patient_message = interrupt(response)
    return {
        **state,
        "lab_reports": reports,
        "patient_message": patient_message,
        "state": "AWAITING_TEST_SELECTION",
        "response": response,
    }


def _format_status(report, patient, generate_response):
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

    return generate_response(context)


def _extract_phone_number(patient_message):
    prompt = f"""Extract the phone number from this message: "{patient_message}"
Return ONLY raw JSON: {{"phone_number": "the number as-is, or null if no number found"}}
No markdown, no extra text."""
    try:
        response = ollama.chat(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.1, "num_predict": 50},
        )
        result = json.loads(response.message.content.strip())
        return result.get("phone_number")
    except Exception as e:
        print(f"Error extracting phone number: {e}")
    return None


def _identify_report(patient_message, reports):
    test_names = [r["test_name"] for r in reports]
    prompt = f"""The patient said: "{patient_message}"
Available tests: {json.dumps(test_names)}
Which test is the patient asking about?
IMPORTANT: If the patient says "I'm not sure", "I don't know", "I have no idea", or any unclear response, return null — do NOT guess.
Return ONLY raw JSON: {{"test_name": "exact name from the list, or null if unclear"}}
No markdown, no extra text."""
    try:
        response = ollama.chat(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.1, "num_predict": 50},
        )
        result = json.loads(response.message.content.strip())
        test_name = result.get("test_name")
        if not test_name:
            return None
        for report in reports:
            if report["test_name"].lower() == test_name.lower():
                return report
    except Exception as e:
        print(f"Error identifying report: {e}")
    return None


def _classify_no_report_choice(patient_message):
    prompt = f"""Classify the patient's response into one of three categories.

Patient said: "{patient_message}"

Categories:
- frontdesk: patient wants to speak to a receptionist or be transferred (e.g. "connect me", "transfer me", "speak to someone", "front desk")
- done: patient is finished and satisfied (e.g. "goodbye", "nothing else", "all set", "thanks bye", "that's okay", "I'm done")
- something_else: patient needs help with a different topic such as booking an appointment, checking a bill, visiting hours, or any other question

Examples:
  "Can you help me book an appointment?" -> {{"choice": "something_else"}}
  "What are your visiting hours?" -> {{"choice": "something_else"}}
  "Connect me to someone" -> {{"choice": "frontdesk"}}
  "Nothing else, goodbye" -> {{"choice": "done"}}

Return ONLY raw JSON: {{"choice": "frontdesk"}} or {{"choice": "done"}} or {{"choice": "something_else"}}
No markdown, no extra text."""
    try:
        response = ollama.chat(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0.1, "num_predict": 50},
        )
        result = json.loads(response.message.content.strip())
        return result.get("choice", "something_else")
    except Exception as e:
        print(f"Error classifying choice: {e}")
    return "something_else"
