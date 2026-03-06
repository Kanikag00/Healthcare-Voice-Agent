from .utils import check_availability, format_slots_for_prompt, resolve_date, resolve_time_preference
from database import Database
import json
import parsedatetime
from datetime import datetime
from session_manager import Session_Manager


def _message_mentions_different_date(message, available_slots):
    """Returns True if the patient message contains a date/day that differs from all available slot dates."""
    if not available_slots:
        return False
    slot_dates = {s["date"] for s in available_slots}
    cal = parsedatetime.Calendar()
    time_struct, status = cal.parse(message)
    if status in (1, 3):  # 1=date, 3=datetime
        mentioned_date = datetime(*time_struct[:3]).date().isoformat()
        return mentioned_date not in slot_dates
    return False

db = Database()

session_manager = Session_Manager()

def handle_book(session_id, patient_message, generate_response, extract_info):
    """Handles all booking states: INITIAL (book), AWAITING_SLOT_SELECTION, AWAITING_PATIENT_INFO"""

    session = session_manager.get_session(session_id)
    state = session["state"]
    appt = session["appointment_details"]

    if state == "INITIAL":
        print("WE ARE HERE TO BOOK")
        has_doctor = appt.get("specialty") is not None or appt.get("doctor_name") is not None
        has_date = appt.get("preferred_date") is not None
        has_time = appt.get("time_preference") is not None

        if has_doctor and has_date and has_time:
            result = book_appointment_flow(appt, generate_response)
            print(" BACK IN BOOK HANDLER - ", result)

            if result.get("available_slots"):
                session_manager.update_session(
                    session_id,
                    state="AWAITING_SLOT_SELECTION",
                    available_slots=result["available_slots"]
                )

            return result.get("response")
        else:
            missing = []
            if not has_doctor:
                missing.append("what type of doctor or specialist they need")
            if not has_date:
                missing.append("their preferred date for the appointment")
            if not has_time:
                missing.append("their preferred time (morning, afternoon, or evening)")

            ask_prompt = (
                f"The patient wants to book an appointment. "
                f"We still need to know: {', and '.join(missing)}. "
                f"Ask the patient for these details in a warm, professional way. "
                f"Keep it to 1-2 sentences."
            )
            return generate_response(ask_prompt)

    elif state == "AWAITING_SLOT_SELECTION":
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
            return "I couldn't identify which slot you'd like. Could you please mention the doctor name or time you prefer?"

        # Code-level guard: if message mentions a different day than the available slots, override to change_preference
        if selected_slot and "change_preference" not in selected_slot and "error" not in selected_slot:
            if _message_mentions_different_date(patient_message, available):
                selected_slot = {"change_preference": True}

        # Patient wants different options — extract new date/time from their message and re-search
        if selected_slot.get("change_preference"):
            # Extract new preferences from the message (e.g. "How about sunday evening?")
            new_prefs = extract_info(patient_message, {"state": "AWAITING_RESCHEDULE_DETAILS"})
            new_date = new_prefs.get("preferred_date", "not mentioned") if new_prefs else "not mentioned"
            new_time = new_prefs.get("time_preference", "not mentioned") if new_prefs else "not mentioned"

            # Keep existing specialty, update date/time if mentioned
            appt = session["appointment_details"]
            if new_date != "not mentioned":
                appt["preferred_date"] = new_date
            if new_time != "not mentioned":
                appt["time_preference"] = new_time

            session_manager.update_session(
                session_id,
                state="INITIAL",
                available_slots=[],
                appointment_details=appt
            )

            # Now re-run booking flow with updated preferences
            if appt.get("preferred_date") and appt.get("time_preference") and (appt.get("specialty") or appt.get("doctor_name")):
                result = book_appointment_flow(appt, generate_response)
                if result.get("available_slots"):
                    session_manager.update_session(
                        session_id,
                        state="AWAITING_SLOT_SELECTION",
                        available_slots=result["available_slots"]
                    )
                else:
                    # No slots — clear date/time so next turn asks for fresh preferences
                    appt["preferred_date"] = None
                    appt["time_preference"] = None
                    session_manager.update_session(session_id, appointment_details=appt)
                return result.get("response")
            else:
                # Still missing some details, ask for them
                missing = []
                if not appt.get("specialty") and not appt.get("doctor_name"):
                    missing.append("what type of doctor or specialist they need")
                if not appt.get("preferred_date"):
                    missing.append("their preferred date")
                if not appt.get("time_preference"):
                    missing.append("their preferred time")
                return generate_response(
                    f"The patient wants to look at different appointment options. "
                    f"We still need: {', and '.join(missing)}. "
                    f"Ask for these details warmly in 1-2 sentences."
                )

        session_manager.update_session(session_id, selected_slot=selected_slot)

        phone_number = session.get("phone_number")
        patient = db.get_patient_by_phone(phone_number) if phone_number else None

        if not patient:
            session_manager.update_session(session_id, state="AWAITING_PATIENT_INFO")
            return generate_response(
                "The patient wants to book an appointment but we don't have their record yet. "
                "Ask for their first name, last name, and date of birth in a warm, professional way. "
                "Keep it to 1-2 sentences."
            )

        patient_name = f"{patient['first_name']} {patient['last_name']}"
        return finalize_booking(session_id, patient["id"], patient_name, selected_slot, generate_response)

    elif state == "AWAITING_PATIENT_INFO":
        patient_info = extract_info(patient_message, session)

        if not patient_info.get("first_name") or not patient_info.get("last_name") or not patient_info.get("date_of_birth"):
            return generate_response(
                f"We still need the patient's full name and date of birth. "
                f"We have so far: {json.dumps(patient_info)}. "
                f"Ask for the missing details warmly in 1-2 sentences."
            )

        phone_number = session.get("phone_number")
        new_patient = db.create_patient(
            phone_number=phone_number,
            first_name=patient_info["first_name"],
            last_name=patient_info["last_name"],
            dob=patient_info["date_of_birth"]
        )

        if not new_patient:
            return "I had trouble creating your profile. Let me transfer you to our front desk."

        patient_id = new_patient.data[0]["id"] if new_patient.data else None
        patient_name = f"{patient_info['first_name']} {patient_info['last_name']}"
        selected_slot = session.get("selected_slot")
        return finalize_booking(session_id, patient_id, patient_name, selected_slot, generate_response)

def book_appointment_flow(appt, generate_response):
    """
    Handles the booking flow when all required details are available.
    Checks availability and returns slots for patient to choose from.
    appt: appointment_details dict from session (uses None for unfilled fields)
    """
    print("IN BOOK APPOINTMENT")
    doctor = appt.get('doctor_name')
    department = appt.get('specialty')
    preferred_date = appt.get('preferred_date')
    time_preference = appt.get('time_preference')
    print("APPOINTENT DETAILS -> ", appt)

    # doctor_name can be None if patient only mentioned department
    preferred_slots, all_day_slots = check_availability(
        specialty=department,
        date_str=preferred_date,
        doctor_name=doctor,
        time_preference=time_preference
    )
    print("PREFERRED SLOTS: ", preferred_slots)
    print("ALL DAY SLOTS: ", all_day_slots)

    if preferred_slots:
        # Found slots matching the preferred time
        slot_list = format_slots_for_prompt(preferred_slots)
        prompt = (
            f"The patient wants to book an appointment in the {time_preference}. "
            f"Here are the available slots:\n{slot_list}\n\n"
            f"You MUST list every single slot above with the doctor name, date, and time range. "
            f"Then ask which one they prefer. Keep it warm and professional."
        )
        available_slots = preferred_slots
    elif all_day_slots:
        # No slots at preferred time, but other slots available that day
        slot_list = format_slots_for_prompt(all_day_slots)
        prompt = (
            f"The patient wanted an appointment in the {time_preference}, but no slots are available at that time. "
            f"However, there are other slots available for the day:\n{slot_list}\n\n"
            f"Apologize that the requested time isn't available. "
            f"Then you MUST list every single slot above with the doctor name, date, and time range. "
            f"Ask if any of them work. Keep it warm and professional."
        )
        available_slots = all_day_slots
    else:
        # No slots at all for the day
        prompt = (
            "No available slots were found for the patient's requested doctor/specialty and date. "
            "Apologize and ask if they'd like to try a different date or a different doctor. "
            "Keep it to 1-2 sentences, warm and professional."
        )
        available_slots = []

    agent_response = generate_response(prompt)
    return {"response": agent_response, "available_slots": available_slots}


def finalize_booking(session_id, patient_id, patient_name, selected_slot, generate_response):
    # Normalize time to HH:MM:00 — LLM may return "15:00", "15:00:00", or "17:00:00"
    raw_time = selected_slot["time"]
    time_hhmm = raw_time[:5]  # always take first 5 chars → "HH:MM"
    appointment = db.create_appointment(
        patient_id=patient_id,
        patient_name=patient_name,
        doctor_id=selected_slot["doctor_id"],
        doctor_name=selected_slot.get("doctor_name", ""),
        appointment_date=selected_slot["date"],
        appointment_time=f'{time_hhmm}:00',
        reason="Booked via voice agent"
    )

    if not appointment:
        return "I couldn't complete the booking. Would you like to try another slot?"

    session_manager.update_session(
        session_id,
        state="COMPLETED",
        selected_slot=selected_slot
    )

    confirmation = generate_response(
        f"Confirm to the patient that their appointment is booked with {selected_slot['doctor_name']} "
        f"on {selected_slot['date']} at {selected_slot['time']}. Be warm and professional. 1-2 sentences."
    )
    return confirmation
