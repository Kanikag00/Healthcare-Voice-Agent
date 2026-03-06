import json
from .book import finalize_booking
from .utils import check_availability, format_appointments_for_display, format_appointments_for_prompt
from database import Database
from session_manager import Session_Manager

db = Database()

session_manager = Session_Manager()


def handle_reschedule(session_id, patient_message, generate_response, extract_info):
    """Handles all reschedule states: INITIAL, AWAITING_RESCHEDULE_SELECTION, AWAITING_RESCHEDULE_DETAILS, AWAITING_RESCHEDULE_SLOT"""

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
                "The patient wants to reschedule an appointment but they don't have any upcoming scheduled appointments. "
                "Let them know politely. Keep it to 1-2 sentences."
            )

        session_manager.update_session(
            session_id,
            existing_appointments=formatted
        )

        if len(formatted) == 1:
            # Only one appointment — auto-select it, ask for new date/time
            session_manager.update_session(
                session_id,
                state="AWAITING_RESCHEDULE_DETAILS",
                selected_appointment=formatted[0]
            )
            appt = formatted[0]
            return generate_response(
                f"The patient wants to reschedule their appointment with {appt['doctor_name']} ({appt['specialty']}) "
                f"on {appt['date']} at {appt['time']}. "
                f"Ask them what new date and time they'd prefer. Keep it warm and professional, 1-2 sentences."
            )
        elif len(formatted) <= 3:
            # Few appointments — list them and ask which one
            session_manager.update_session(
                session_id,
                state="AWAITING_RESCHEDULE_SELECTION"
            )
            appt_list = format_appointments_for_prompt(formatted)
            return generate_response(
                f"The patient wants to RESCHEDULE an appointment. They have these upcoming appointments:\n"
                f"{appt_list}\n\n"
                f"You MUST list every appointment above with the doctor name, specialty, date, and time. "
                f"Then ask which one they'd like to reschedule. "
                f"Keep it warm and professional, 2-3 sentences."
            )
        else:
            # Many appointments — ask patient to narrow down instead of listing all
            session_manager.update_session(
                session_id,
                state="AWAITING_RESCHEDULE_SELECTION"
            )
            return generate_response(
                "The patient wants to reschedule an appointment. They have several upcoming appointments. "
                "Ask them to tell you the doctor's name or the date of the appointment they'd like to reschedule. "
                "Keep it warm and professional, 1-2 sentences."
            )

    elif state == "AWAITING_RESCHEDULE_SELECTION":
        selected = extract_info(patient_message, session)

        if selected is None:
            return "I couldn't identify which appointment you mean. Could you please mention the doctor's name or the date?"

        session_manager.update_session(
            session_id,
            state="AWAITING_RESCHEDULE_DETAILS",
            selected_appointment=selected
        )
        return generate_response(
            f"The patient selected their appointment with {selected['doctor_name']} "
            f"on {selected['date']} at {selected['time']} to reschedule. "
            f"Ask them what new date and time they'd prefer. Keep it warm and professional, 1-2 sentences."
        )

    elif state == "AWAITING_RESCHEDULE_DETAILS":
        prefs = extract_info(patient_message, session)

        has_date = prefs.get("preferred_date") != "not mentioned"
        has_time = prefs.get("time_preference") != "not mentioned"

        if not has_date or not has_time:
            missing = []
            if not has_date:
                missing.append("their preferred date")
            if not has_time:
                missing.append("their preferred time (morning, afternoon, or evening)")
            return generate_response(
                f"The patient wants to reschedule but we still need: {', and '.join(missing)}. "
                f"Ask for these details warmly in 1-2 sentences."
            )

        # Look up availability for the same doctor
        selected = session.get("selected_appointment")
        doctor_name = selected.get("doctor_name")

        time_pref = prefs.get("time_preference")
        preferred_slots, all_day_slots = check_availability(
            specialty=None,
            date_str=prefs["preferred_date"],
            doctor_name=doctor_name,
            time_preference=time_pref
        )
        available_slots = preferred_slots if preferred_slots else all_day_slots

        if not available_slots:
            return generate_response(
                f"No available slots were found for {doctor_name} on {prefs['preferred_date']}. "
                f"Apologize and ask if they'd like to try a different date. Keep it to 1-2 sentences."
            )

        session_manager.update_session(
            session_id,
            state="AWAITING_RESCHEDULE_SLOT",
            available_slots=available_slots
        )
        return generate_response(
            f"The patient wants to reschedule with {doctor_name}. Here are the available slots:\n"
            f"{available_slots}\n"
            f"Present these slots clearly and ask which one they prefer. Keep it warm and professional, 2-3 sentences."
        )

    elif state == "AWAITING_RESCHEDULE_SLOT":
        selected_slot = extract_info(patient_message, session)

        # If LLM extracted a slot but missed doctor details, fill from available slots if only one doctor
        available = session.get("available_slots", [])
        if selected_slot and not selected_slot.get("doctor_id") and "change_preference" not in selected_slot and "error" not in selected_slot:
            unique_doctors = {s["doctor_id"]: s for s in available}
            if len(unique_doctors) == 1:
                only_doctor = list(unique_doctors.values())[0]
                selected_slot["doctor_name"] = only_doctor["doctor_name"]
                selected_slot["doctor_id"] = only_doctor["doctor_id"]
                if not selected_slot.get("date"):
                    selected_slot["date"] = only_doctor["date"]
                print(f"AUTO-FILLED single doctor details: {selected_slot}")

        if selected_slot is None:
            return "I couldn't identify which slot you'd like. Could you please mention the time you prefer?"

        # Patient wants different options — go back to collecting new date/time
        if selected_slot.get("change_preference"):
            session_manager.update_session(
                session_id,
                state="AWAITING_RESCHEDULE_DETAILS",
                available_slots=[]
            )
            return generate_response(
                "The patient wants to look at different options for rescheduling. "
                "Ask them what new date and time they'd prefer. Keep it warm and professional, 1-2 sentences."
            )

        # Cancel the old appointment
        old_appointment = session.get("selected_appointment")
        appt_id = old_appointment.get("id") or old_appointment.get("appointment_id")
        db.cancel_appointment(appt_id)

        # Book the new one
        phone_number = session.get("phone_number")
        patient = db.get_patient_by_phone(phone_number)
        patient_id = patient["id"] if patient else None
        patient_name = f"{patient['first_name']} {patient['last_name']}" if patient else ""

        return finalize_booking(session_id, patient_id, patient_name, selected_slot, generate_response)
