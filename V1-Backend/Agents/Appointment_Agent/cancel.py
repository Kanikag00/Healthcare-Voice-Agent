import json
from database import Database
from session_manager import Session_Manager
from .utils import format_appointments_for_display, format_appointments_for_prompt

db = Database()

session_manager = Session_Manager()


def handle_cancel(session_id, patient_message, generate_response, extract_info):
    """Handles all cancel states: INITIAL (cancel), AWAITING_CANCEL_SELECTION, AWAITING_CANCEL_CONFIRMATION"""

    session = session_manager.get_session(session_id)
    state = session["state"]

    if state == "INITIAL":
        phone_number = session.get("phone_number")
        patient = db.get_patient_by_phone(phone_number) if phone_number else None

        if not patient:
            session_manager.update_session(session_id, state="COMPLETED")
            return generate_response(
                "We don't have a patient record for this phone number. "
                "Let the patient know politely and ask if there's anything else we can help with. "
                "Keep it to 1-2 sentences."
            )

        appointments = db.get_patient_appointments(patient["id"])
        formatted = format_appointments_for_display(appointments)

        if not formatted:
            session_manager.update_session(session_id, state="COMPLETED")
            return generate_response(
                "The patient wants to cancel an appointment but they don't have any upcoming scheduled appointments. "
                "Let them know politely. Keep it to 1-2 sentences."
            )

        session_manager.update_session(
            session_id,
            existing_appointments=formatted
        )

        if len(formatted) == 1:
            # Only one appointment — skip selection, go straight to confirmation
            session_manager.update_session(
                session_id,
                state="AWAITING_CANCEL_CONFIRMATION",
                selected_appointment=formatted[0]
            )
            appt = formatted[0]
            return generate_response(
                f"The patient wants to cancel their appointment. They have one upcoming appointment: "
                f"with {appt['doctor_name']} ({appt['specialty']}) on {appt['date']} at {appt['time']}. "
                f"Confirm this is the one they want to cancel. Ask 'Are you sure you want to cancel this appointment?' "
                f"Keep it warm and professional, 2-3 sentences."
            )
        elif len(formatted) <= 3:
            # Few appointments — list them and ask which one
            session_manager.update_session(
                session_id,
                state="AWAITING_CANCEL_SELECTION"
            )
            appt_list = format_appointments_for_prompt(formatted)
            return generate_response(
                f"The patient wants to CANCEL an appointment. They have these upcoming appointments:\n"
                f"{appt_list}\n\n"
                f"You MUST list every appointment above with the doctor name, specialty, date, and time. "
                f"Then ask which one they'd like to cancel. "
                f"Keep it warm and professional, 2-3 sentences."
            )
        else:
            # Many appointments — ask patient to narrow down instead of listing all
            session_manager.update_session(
                session_id,
                state="AWAITING_CANCEL_SELECTION"
            )
            return generate_response(
                "The patient wants to cancel an appointment. They have several upcoming appointments. "
                "Ask them to tell you the doctor's name or the date of the appointment they'd like to cancel. "
                "Keep it warm and professional, 1-2 sentences."
            )

    elif state == "AWAITING_CANCEL_SELECTION":
        selected = extract_info(patient_message, session)

        if selected is None:
            return "I couldn't identify which appointment you mean. Could you please mention the doctor's name or the date?"

        session_manager.update_session(
            session_id,
            state="AWAITING_CANCEL_CONFIRMATION",
            selected_appointment=selected
        )
        return generate_response(
            f"The patient selected their appointment with {selected['doctor_name']} "
            f"on {selected['date']} at {selected['time']}. "
            f"Confirm the details and ask 'Are you sure you want to cancel this appointment?' "
            f"Keep it warm and professional, 1-2 sentences."
        )

    elif state == "AWAITING_CANCEL_CONFIRMATION":
        confirmed = extract_info(patient_message, session)
        selected = session.get("selected_appointment")

        if confirmed:
            appt_id = selected.get("id") or selected.get("appointment_id")
            result = db.cancel_appointment(appt_id)
            session_manager.update_session(session_id, state="COMPLETED")

            if result:
                return generate_response(
                    f"The patient's appointment with {selected['doctor_name']} on {selected['date']} "
                    f"at {selected['time']} has been successfully cancelled. "
                    f"Confirm the cancellation and ask if there's anything else they need. "
                    f"Keep it warm and professional, 1-2 sentences."
                )
            else:
                return "I had trouble cancelling the appointment. Let me transfer you to our front desk for assistance."
        else:
            session_manager.update_session(session_id, state="COMPLETED")
            return generate_response(
                "The patient decided not to cancel their appointment. "
                "Acknowledge their decision and let them know their appointment is still active. "
                "Ask if there's anything else they need. Keep it to 1-2 sentences."
            )
