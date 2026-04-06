from database import Database
from state import AgentState
from langgraph.types import interrupt
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from utils import check_availability, format_slots_for_prompt

db = Database()

# -----------NODE 1-------------
def book_get_slots_node(state: AgentState, generate_response) -> AgentState:
    """Checks availability and interrupts to show slots to the patient."""

    print("Appointment Details in booking slot function ->  ", state["appointment_details"])

    result = get_booking_slots(state, generate_response)
    print("RESULT from booking slots -> ", result)

    # No slots found → ask patient to try a different date/time and it will be routed back to extract node
    if not result.get("available_slots"):
        print("INTERRUPTING TO ASK FOR NEW SLOT")
        patient_message = interrupt(result.get("response"))
        appt = {**state.get("appointment_details", {})}
        appt["preferred_date"] = "not mentioned"
        appt["time_preference"] = "not mentioned"
        appt["is_complete"] = False
        state = {**state, "patient_message": patient_message, "appointment_details": appt, "state": "AWAITING_DIFFERENT_DAY"}
        return state

    # Slots found → interrupt to present them; patient's reply goes to next node
    print("INTERRUPTING TO ASK FOR SLOT")
    response = result.get("response")
    patient_message = interrupt(response)
    return {
        **state,
        "available_slots": result.get("available_slots"),
        "slot_response": response,
        "patient_message": patient_message,
        "state": "AWAITING_SLOT_SELECTION",
    }

# -----------NODE 2-------------
def book_select_slot_node(state: AgentState, extract_info) -> AgentState:
    """Extracts which slot the patient picked, or detects a change-preference request."""

    selected_slot = extract_info(state)
    print("SELECTED SLOT > ", selected_slot)
    print("change_preference type - ", selected_slot.get("change_preference"))

    if selected_slot.get("change_preference") is True:
        new_date = selected_slot.get("date")
        new_time = selected_slot.get("time")
        print("YYYAA. ", new_date, "   ", new_time)
        appt = state.get("appointment_details")
        appt["preferred_date"] = new_date
        appt["time_preference"] = new_time

        print("CHANGE PREFERENCE IS TRUE: ")
        print("new appt details : ", appt)
        return {**state, "appointment_details": appt, "state":"AWAITING_NEW_SLOTS"}

    return {**state, "selected_slot": selected_slot,"state":"SLOT_SELECTED"}


# -----------NODE 3------------
def new_patient_info(state: AgentState, generate_response, extract_info) -> AgentState:
    """creates new patient record if not found."""

    
    patient_info_extracted = extract_info(state)
    missing, state = patient_info_validation(state, patient_info_extracted)

    if missing:
        ask = f"Could you please share the patient's {' and '.join(missing)}?"
        patient_response = interrupt(ask)
        return {**state, "patient_message": patient_response, "state": "AWAITING_PATIENT_INFO"}

    # All info collected → create patient
    phone_number = state.get("phone_number")
    new_patient = db.create_patient(
        phone_number=phone_number,
        first_name=state["patient_info"]["first_name"],
        last_name=state["patient_info"]["last_name"],
        dob=state["patient_info"]["date_of_birth"],
    )
    if not new_patient:
            return {**state, "response": "I had trouble creating your profile. Let me transfer you to our front desk.", "state": "FRONTDESK"}

    patient_info = {
        **state.get("patient_info", {}),
        "patient_name": f"{state['patient_info']['first_name']} {state['patient_info']['last_name']}",
        "patient_id": new_patient.data[0]["id"] if new_patient.data else None,
    }
    return {**state, "patient_info": patient_info, "state": "FINALIZE_BOOKING"}


# -----------NODE 4-------------
def book_finalize_node(state: AgentState, generate_response) -> AgentState:
    """Saves the appointment; on failure asks the patient to pick another slot."""

    selected_slot = state.get("selected_slot")
    raw_time = selected_slot["time"]
    time_hhmm = raw_time[:5]
    appointment = db.create_appointment(
        patient_id=state.get("patient_info").get("patient_id"),
        patient_name=state.get("patient_info").get("patient_name"),
        doctor_id=selected_slot["doctor_id"],
        doctor_name=selected_slot.get("doctor_name", ""),
        appointment_date=selected_slot["date"],
        appointment_time=f"{time_hhmm}:00",
        reason="Booked via voice agent",
    )

    if not appointment:
        agent_response = "I couldn't complete the booking. Let me transfer you to our front desk."
        return {**state, "state": "FRONTDESK", "response": agent_response}

    confirmation = generate_response(
        f"Confirm to the patient that their appointment is booked with {selected_slot['doctor_name']} "
        f"on {selected_slot['date']} at {selected_slot['time']}. Be warm and professional. 1-2 sentences."
    )
    return {**state, "state": "COMPLETED", "selected_slot": selected_slot, "response": confirmation}


def patient_info_validation(state: AgentState, patient_info_extracted):
    missing = []
    patient_info_state = dict(state.get("patient_info") or {})
    if patient_info_extracted.get("first_name") not in (None, "not mentioned"):
        if not patient_info_state.get("first_name"):
            patient_info_state["first_name"] = patient_info_extracted["first_name"]
    else:
        missing.append("first name")
    if patient_info_extracted.get("last_name") not in (None, "not mentioned"):
        if not patient_info_state.get("last_name"):
            patient_info_state["last_name"] = patient_info_extracted["last_name"]
    else:
        missing.append("last name")
    if patient_info_extracted.get("date_of_birth") not in (None, "not mentioned"):
        if not patient_info_state.get("date_of_birth"):
            patient_info_state["date_of_birth"] = patient_info_extracted["date_of_birth"]
    else:
        missing.append("date of birth")

    return missing, {**state, "patient_info": patient_info_state}


def get_booking_slots(state: AgentState, generate_response):
    """Checks availability and returns slots for patient to choose from."""
    appt = state.get("appointment_details")
    doctor = appt.get("doctor_name")
    department = appt.get("specialty")
    preferred_date = appt.get("preferred_date")
    time_preference = appt.get("time_preference")
    today_str = datetime.now().strftime("%A, %B %d, %Y")

    preferred_slots, all_day_slots = check_availability(
        specialty=department,
        date_str=preferred_date,
        doctor_name=doctor,
        time_preference=time_preference,
    )
    if preferred_slots:
        slot_list = format_slots_for_prompt(preferred_slots)
        prompt = (
            f"Today is {today_str}.\n"
            f"The patient wants an appointment in the {time_preference}. "
            f"Here are the options: {slot_list}. "
            f"Instructions: Briefly summarize these options in one or two warm sentences. "
            f"If a doctor has a block of time available, give the range (e.g., 'Dr. Singh is available from 6 to 9 PM'). "
            f"Don't list every individual slot. Ask which works best."
        )
        return {"response": generate_response(prompt), "available_slots": preferred_slots}
    elif all_day_slots:
        slot_list = format_slots_for_prompt(all_day_slots)
        prompt = (
            f"Today is {today_str}.\n"
            f"The patient wanted the {time_preference}, but we're fully booked then. We do have these other slots: {slot_list}. "
            f"Instructions: Start with a quick, natural apology. "
            f"Then, summarize the available alternatives concisely (group by doctor if possible). "
            f"Avoid a long list. Ask if any of these work instead."
        )
        return {"response": generate_response(prompt), "available_slots": all_day_slots}
    else:
        prompt = (
            "No available slots were found for the patient's requested doctor/specialty and date. "
            "Apologize and ask if they'd like to try a different date or a different doctor. "
            "Keep it to 1-2 sentences, warm and professional."
        )
        return {"response": generate_response(prompt), "available_slots": []}
