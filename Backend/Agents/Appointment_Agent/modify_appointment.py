import os
from database import Database
from state import AgentState
from langgraph.types import interrupt
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from utils import (
    format_appointments_for_display,
    format_appointments_for_prompt,
)

db = Database()


# -----------NODE 1 (cancel + reschedule)-------------
def modify_lookup_node(state: AgentState, generate_response) -> AgentState:
    """Looks up patient appointments and presents them for cancel or reschedule."""

    action = state.get("sub_action")  # cancel | reschedule
    appointments = db.get_patient_appointments(state.get("patient_info").get("patient_id"))
    formatted = format_appointments_for_display(appointments)

    if not formatted:
        response = generate_response(
            f"The patient wants to {action} an appointment but they don't have any upcoming scheduled appointments. "
            "Tell them you will transfer them to the front desk. "
            "Let them know politely. Keep it to 1-2 sentences."
        )
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "state": "FRONTDESK", "response": response}

    if len(formatted) == 1:
        appt = formatted[0]
        if action == "cancel":
            prompt = (
                f"The patient wants to cancel their appointment. They have one upcoming appointment: "
                f"with {appt['doctor_name']} ({appt['specialty']}) on {appt['date']} at {appt['time']}. "
                f"Confirm this is the one they want to cancel. Ask 'Are you sure you want to cancel this appointment?' "
                f"Keep it warm and professional, 2-3 sentences."
            )
            next_state = "AWAITING_CANCEL_CONFIRMATION"
        else:
            prompt = (
                f"The patient wants to reschedule their appointment with {appt['doctor_name']} ({appt['specialty']}) "
                f"on {appt['date']} at {appt['time']}. "
                f"Ask them what new date and time they'd prefer. Keep it warm and professional, 1-2 sentences."
            )
            next_state = "AWAITING_RESCHEDULE_DETAILS"

        response = generate_response(prompt)
        patient_message = interrupt(response)
        return {
            **state,
            "existing_appointments": formatted,
            "selected_appointment": formatted[0],
            "patient_message": patient_message,
            "state": next_state,
            "response": response,
        }

    if len(formatted) <= 3:
        appt_list = format_appointments_for_prompt(formatted)
        response = generate_response(
            f"The patient wants to {action.upper()} an appointment. They have these upcoming appointments:\n"
            f"{appt_list}\n\n"
            f"You MUST list every appointment above with the doctor name, specialty, date, and time. "
            f"Then ask which one they'd like to {action}. "
            f"Keep it warm and professional, 2-3 sentences."
        )
    else:
        response = generate_response(
            f"The patient wants to {action} an appointment. They have several upcoming appointments. "
            f"Ask them to tell you the doctor's name or the date of the appointment they'd like to {action}. "
            "Keep it warm and professional, 1-2 sentences."
        )

    next_state = "AWAITING_CANCEL_SELECTION" if action == "cancel" else "AWAITING_RESCHEDULE_SELECTION"
    patient_message = interrupt(response)
    return {
        **state,
        "existing_appointments": formatted,
        "patient_message": patient_message,
        "state": next_state,
        "response": response,
    }


# -----------NODE 2 (cancel + reschedule)-------------
def modify_select_node(state: AgentState, extract_info, generate_response) -> AgentState:
    """Extracts which appointment the patient picked, then routes to confirm (cancel) or new date (reschedule)."""

    action = state.get("sub_action")
    selected = extract_info(state)

    if selected is None:
        response = "I couldn't identify which appointment you mean. Could you please mention the doctor's name or the date?"
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "response": response}

    if action == "cancel":
        prompt = (
            f"The patient selected their appointment with {selected['doctor_name']} "
            f"on {selected['date']} at {selected['time']}. "
            f"Confirm the details and ask 'Are you sure you want to cancel this appointment?' "
            f"Keep it warm and professional, 1-2 sentences."
        )
        next_state = "AWAITING_CANCEL_CONFIRMATION"
    else:
        prompt = (
            f"The patient selected their appointment with {selected['doctor_name']} "
            f"on {selected['date']} at {selected['time']} to reschedule. "
            f"Ask them what new date and time they'd prefer. Keep it warm and professional, 1-2 sentences."
        )
        next_state = "AWAITING_RESCHEDULE_DETAILS"

    response = generate_response(prompt)
    patient_message = interrupt(response)
    return {
        **state,
        "selected_appointment": selected,
        "patient_message": patient_message,
        "state": next_state,
        "response": response,
    }


# -----------NODE 3 (cancel-only)-------------
def cancel_confirm_node(state: AgentState, extract_info, generate_response) -> AgentState:
    """Extracts yes/no confirmation and cancels the appointment if confirmed."""

    confirmed = extract_info(state)
    selected = state.get("selected_appointment")

    if confirmed and confirmed.get("confirmed"):
        appt_id = selected.get("id")
        result = db.cancel_appointment(appt_id)
        if result:
            response = generate_response(
                f"The patient's appointment with {selected['doctor_name']} on {selected['date']} "
                f"at {selected['time']} has been successfully cancelled. "
                f"Confirm the cancellation and ask if there's anything else they need. "
                f"Keep it warm and professional, 1-2 sentences."
            )
        else:
            response = "I had trouble cancelling the appointment. Let me transfer you to our front desk for assistance."
    else:
        response = generate_response(
            "The patient decided not to cancel their appointment. "
            "Acknowledge their decision and let them know their appointment is still active. "
            "Ask if there's anything else they need. Keep it to 1-2 sentences."
        )

    return {**state, "state": "COMPLETED", "response": response}


# -----------NODE 4 (reschedule-only)-------------
def reschedule_details_node(state: AgentState, extract_info, generate_response) -> AgentState:
    """Extracts new date/time preferences, then hands off to the shared slot-search flow."""

    prefs = extract_info(state)
    appointment = state.get("appointment_details") or {}

    if prefs.get("preferred_date") not in (None, "not mentioned"):
        appointment["preferred_date"] = prefs.get("preferred_date")
    if prefs.get("time_preference") not in (None, "not mentioned"):
        appointment["time_preference"] = prefs.get("time_preference")

    if not appointment.get("preferred_date") or not appointment.get("time_preference"):
        missing = []
        if not appointment.get("preferred_date"):
            missing.append("their preferred date")
        if not appointment.get("time_preference"):
            missing.append("their preferred time (morning, afternoon, or evening)")
        response = generate_response(
            f"The patient wants to reschedule but we still need: {', and '.join(missing)}. "
            f"Ask for these details warmly in 1-2 sentences."
        )
        patient_message = interrupt(response)
        return {**state, "patient_message": patient_message, "response": response,"state":"AWAITING_RESCHEDULE_DATETIME"}

    # Doctor and specialty are fixed (same one from the existing appointment).
    selected = state.get("selected_appointment", {})
    appointment_details = {
        **(state.get("appointment_details") or {}),
        "doctor_name": selected.get("doctor_name"),
        "specialty": selected.get("specialty"),
        "preferred_date": prefs["preferred_date"],
        "time_preference": prefs.get("time_preference"),
    }
    return {**state, "appointment_details": appointment_details, "state": "AWAITING_RESCHEDULE_SLOTS"}


# -----------NODE 5 (reschedule-only)-------------
def reschedule_slot_node(state: AgentState, generate_response) -> AgentState:
    """Cancels the old appointment and books the new one using the slot already selected by the shared flow."""

    selected_slot = state.get("selected_slot")  # set by book_select_slot_node

    # Cancel old appointment
    old_appointment = state.get("selected_appointment")
    appt_id = old_appointment.get("id") or old_appointment.get("appointment_id")
    db.cancel_appointment(appt_id)

    # Book new appointment using patient_info already in state
    patient_info = state.get("patient_info")
    patient_id = patient_info.get("patient_id")
    patient_name = patient_info.get("patient_name", "")

    raw_time = selected_slot["time"]
    time_hhmm = raw_time[:5]
    appointment = db.create_appointment(
        patient_id=patient_id,
        patient_name=patient_name,
        doctor_id=selected_slot["doctor_id"],
        doctor_name=selected_slot.get("doctor_name", ""),
        appointment_date=selected_slot["date"],
        appointment_time=f"{time_hhmm}:00",
        reason="Rescheduled via voice agent",
    )

    if not appointment:
        response = "I couldn't complete the reschedule. Let me transfer you to our front desk."
        return {**state, "state": "FRONTDESK", "response": response}

    response = generate_response(
        f"The patient's appointment has been successfully rescheduled with {selected_slot['doctor_name']} "
        f"on {selected_slot['date']} at {selected_slot['time']}. "
        f"Confirm warmly and ask if there's anything else they need. 1-2 sentences."
    )
    return {**state, "state": "COMPLETED", "selected_slot": selected_slot, "response": response}


# -----------NODE 6 (shared utility)-------------
def get_alternate_number(state: AgentState, generate_response, extract_info) -> AgentState:
    result = extract_info(state)
    phone_number = result.get("phone_number")

    if phone_number:
        patient = db.get_patient_by_phone(phone_number)
        if not patient:
            response = generate_response(
                "No patient records were found with this number either. "
                "Let me connect you to the frontdesk."
            )
            return {**state, "response": response, "patient_info": None, "state": "FRONTDESK"}

        patient_name = f"{patient['first_name']} {patient['last_name']}"
        return {
            **state,
            "patient_info": {"patient_name": patient_name, "patient_id": patient["id"]},
            "state": "PATIENT_FOUND",
            "alternate_phone_number": phone_number,
        }

    response = generate_response(
        "Apologies. We couldn't understand the phone number given. "
        "Let me connect you to the frontdesk."
    )
    return {**state, "state": "FRONTDESK", "response": response}
