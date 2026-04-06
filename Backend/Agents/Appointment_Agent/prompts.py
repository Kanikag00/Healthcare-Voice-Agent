import json
from state import AgentState
from datetime import datetime
now = datetime.now()
today_str = now.strftime("%A, %B %d, %Y")

def prompts_builder(state:AgentState):
    
    patient_message = state.get('patient_message')
    prompts = {
        "AWAITING_SLOT_SELECTION":(
            f"Today is {today_str}.\n"
            f'Patient message: "{patient_message}"\n'
            f"Available Slots JSON: {json.dumps(state.get('available_slots', []), indent=2)}\n\n"
            "TASK: Determine if the patient is SELECTING one of the available slots above, or requesting a DIFFERENT date/time/doctor.\n\n"
            "CASE A — Patient is CONFIRMING a slot from the list above "
            "(e.g. 'yes', 'sure', 'Dr. Reddy', 'the morning one', 'book that one', 'that works', 'the first option'):\n"
            "   - Match to the correct slot using doctor name or time.\n"
            "   - Fill doctor_name, doctor_id, date, and time exactly from that matching slot.\n"
            "   - Set change_preference: false.\n\n"
            "CASE B — Patient wants something DIFFERENT than what is shown. Use CASE B when ANY of these apply:\n"
            "   1. Patient says 'No', 'Nope', 'No thanks', 'None of these work', or starts with a clear rejection.\n"
            "   2. Patient asks for a different DAY (e.g. 'How about Saturday?' when slots are on a different day).\n"
            "   3. Patient asks 'Can I try a different day?', 'Do you have other options?', 'What about [other day]?' or similar.\n"
            "   4. Patient mentions a different DOCTOR not in the list.\n"
            "   → Set change_preference: true, doctor_name: null, doctor_id: null.\n"
            "   → Set date to what the patient requested (YYYY-MM-DD or 'not specified').\n"
            "   → Set time to the period word the patient used ('morning', 'afternoon', 'evening') or a clock time like '10:00', or 'not specified'.\n"
            "   → NEVER convert period words to clock times (do NOT map morning→09:00, evening→17:00, etc.).\n\n"
            "DECISION RULE: Ask yourself — 'Is the patient agreeing to one of the listed slots?' If NO, it is CASE B.\n\n"
            "Examples:\n"
            '  "No. Check for Saturday Morning" → {"doctor_name": null, "doctor_id": null, "date": "2026-03-21", "time": "morning", "change_preference": true}\n'
            '  "How about Sunday evening?" → {"doctor_name": null, "doctor_id": null, "date": "2026-03-22", "time": "evening", "change_preference": true}\n'
            '  "Tomorrow afternoon please" → {"doctor_name": null, "doctor_id": null, "date": "2026-03-17", "time": "afternoon", "change_preference": true}\n'
            '  "Can I try a different day?" → {"doctor_name": null, "doctor_id": null, "date": "not specified", "time": "not specified", "change_preference": true}\n'
            '  "None of these work, do you have Monday slots?" → {"doctor_name": null, "doctor_id": null, "date": "not specified", "time": "not specified", "change_preference": true}\n'
            '  "Yes, book that one" → fill from matching slot, change_preference: false\n'
            '  "Dr. Sharma is fine" → fill from Dr. Sharma slot, change_preference: false\n\n'
            "Return ONLY raw JSON with all 5 fields:\n"
            '{"doctor_name": string or null, "doctor_id": string or null, "date": "YYYY-MM-DD or not specified", "time": "morning/afternoon/evening or HH:MM or not specified", "change_preference": boolean}\n'
            "No explanation, no markdown, no code blocks."
        ),
        "AWAITING_RESCHEDULE_SLOT": (
            f'The patient said: "{patient_message}"\n'
            f'Here are the available slots:\n{json.dumps(state.get("available_slots", []), indent=2)}\n\n'
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
            f'You are an expert medical data extractor. Extract the First Name, Last Name, and Date of Birth into JSON. Return ONLY raw JSON with below 3 fields:\n'
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
            f'Here are their upcoming appointments:\n{json.dumps(state.get("existing_appointments", []), indent=2)}\n\n'
            f'Which appointment is the patient referring to? Return ONLY raw JSON with these fields:\n'
            f'- "appointment_id": the appointment\'s id\n'
            f'- "doctor_name": the doctor\'s name\n'
            f'- "date": the appointment date\n'
            f'- "time": the appointment time\n\n'
            f'IMPORTANT: If the patient says "I\'m not sure", "any of them", "doesn\'t matter", or is unclear, return {{"error": "unclear"}}.\n'
            f'If you cannot determine their choice, return {{"error": "unclear"}}.\n'
            f'No markdown, no code blocks, no extra text.'
        ),
        "AWAITING_RESCHEDULE_SELECTION": (
            f'The patient said: "{patient_message}"\n'
            f'Here are their upcoming appointments:\n{json.dumps(state.get("existing_appointments", []), indent=2)}\n\n'
            f'Which appointment is the patient referring to? Return ONLY raw JSON with these fields:\n'
            f'- "appointment_id": the appointment\'s id\n'
            f'- "doctor_name": the doctor\'s name\n'
            f'- "date": the appointment date\n'
            f'- "time": the appointment time\n\n'
            f'IMPORTANT: If the patient says "I\'m not sure", "any of them", "doesn\'t matter", or is unclear, return {{"error": "unclear"}}.\n'
            f'If you cannot determine their choice, return {{"error": "unclear"}}.\n'
            f'No markdown, no code blocks, no extra text.'
        ),
        "AWAITING_CANCEL_CONFIRMATION": (
            f'The patient said: "{patient_message}"\n'
            f'Did the patient confirm the cancellation (yes) or decide NOT to cancel (no)?\n'
            f'IMPORTANT: Words like "no", "don\'t", "keep it", "not cancel", "changed my mind", "let\'s not" all mean confirmed: false.\n'
            f'Examples:\n'
            f'  "Yes please cancel it" → {{"confirmed": true}}\n'
            f'  "Sure, go ahead" → {{"confirmed": true}}\n'
            f'  "No don\'t cancel it" → {{"confirmed": false}}\n'
            f'  "Actually no, keep it" → {{"confirmed": false}}\n'
            f'  "Hmm, let\'s not" → {{"confirmed": false}}\n'
            f'Return ONLY raw JSON: {{"confirmed": true}} or {{"confirmed": false}}\n'
            f'No markdown, no code blocks, no extra text.'
        ),
        # AWAITING_RESCHEDULE_DATETIME is used when looping back after missing date or time.
        # It uses the same extraction prompt as the initial AWAITING_RESCHEDULE_DETAILS state.
        "AWAITING_RESCHEDULE_DATETIME": (
            f'Extract the new appointment preferences from this patient message: "{patient_message}"\n'
            f'Return ONLY raw JSON with exactly these 2 fields:\n'
            f'- "preferred_date": a CALENDAR DAY or DATE (e.g. "tomorrow", "Monday", "next Friday", "March 5") or "not mentioned". '
            f'NEVER put time-of-day words (morning/afternoon/evening) here.\n'
            f'- "time_preference": a TIME OF DAY or clock time (e.g. "morning", "afternoon", "evening", "10 AM") or "not mentioned"\n\n'
            f'Examples:\n'
            f'"Tuesday morning" -> {{"preferred_date": "Tuesday", "time_preference": "morning"}}\n'
            f'"Next Thursday" -> {{"preferred_date": "Thursday", "time_preference": "not mentioned"}}\n'
            f'"afternoon would work" -> {{"preferred_date": "not mentioned", "time_preference": "afternoon"}}\n\n'
            f'No markdown, no code blocks, no extra text.'
        ),
        "AWAITING_RESCHEDULE_DETAILS": (
            f'Extract the new appointment preferences from this patient message: "{patient_message}"\n'
            f'Return ONLY raw JSON with exactly these 2 fields:\n'
            f'- "preferred_date": a CALENDAR DAY or DATE (e.g. "tomorrow", "Monday", "next Friday", "March 5") or "not mentioned". '
            f'NEVER put time-of-day words (morning/afternoon/evening) here.\n'
            f'- "time_preference": a TIME OF DAY or clock time (e.g. "morning", "afternoon", "evening", "10 AM") or "not mentioned"\n\n'
            f'Examples:\n'
            f'"Tuesday morning" -> {{"preferred_date": "Tuesday", "time_preference": "morning"}}\n'
            f'"tomorrow at 3 PM" -> {{"preferred_date": "tomorrow", "time_preference": "3 PM"}}\n'
            f'"afternoon would work" -> {{"preferred_date": "not mentioned", "time_preference": "afternoon"}}\n'
            f'"How about Sunday?" -> {{"preferred_date": "Sunday", "time_preference": "not mentioned"}}\n'
            f'"I just need to reschedule" -> {{"preferred_date": "not mentioned", "time_preference": "not mentioned"}}\n\n'
            f'No markdown, no code blocks, no extra text.'
        ),
        "AWAITING_ALTERNATE_NUMBER": (
            f'Extract the phone number from this message: "{patient_message}"\n'
            f'Return ONLY raw JSON: {{"phone_number": "the number as-is, or null if no number found"}}\n'
            f'No markdown, no extra text.'
        )
    }
    return prompts[state.get("state")]