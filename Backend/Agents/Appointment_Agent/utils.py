import parsedatetime
from datetime import datetime, timedelta
from database import Database

db = Database()

def resolve_date(date_str):
    """
    Resolves a date string or day name into (YYYY-MM-DD, day_of_week).
    Handles: "2026-02-20", "Monday", "tomorrow", "next Wednesday"
    Returns: ("2026-02-20", "thursday") or None if unresolvable
    """
    cal = parsedatetime.Calendar()
    # parseDT returns a tuple: (datetime, status_code)
    # status_code 1 = Date, 2 = Time, 3 = DateTime
    time_struct, status = cal.parse(date_str)

    if status > 0:
        resolved_date = datetime(*time_struct[:7])
        return resolved_date
    else:
        print("Could not parse date.")
        return None


def subtract_booked_from_ranges(ranges, booked_times):
    """
    Subtracts 30-min booked slots from availability ranges.
    ranges: [["09:00", "12:00"], ["16:00", "20:00"]]
    booked_times: ["10:30:00", "17:30:00"]  (HH:MM:SS from DB)
    Returns: [["09:00", "10:30"], ["11:00", "12:00"], ["16:00", "17:30"], ["18:00", "20:00"]]
    """
    blocked = []
    for t in booked_times:
        start = datetime.strptime(t, "%H:%M:%S")
        end = start + timedelta(minutes=30)
        blocked.append((start, end))
    blocked.sort()

    available = []
    for r in ranges:
        range_start = datetime.strptime(r[0], "%H:%M")
        range_end = datetime.strptime(r[1], "%H:%M")

        current = range_start
        for block_start, block_end in blocked:
            if block_start >= range_end or block_end <= range_start:
                continue
            if current < block_start:
                available.append([current.strftime("%H:%M"), block_start.strftime("%H:%M")])
            current = max(current, block_end)

        if current < range_end:
            available.append([current.strftime("%H:%M"), range_end.strftime("%H:%M")])

    return available


TIME_PERIODS = {
    "morning": ("06:00", "12:00"),
    "afternoon": ("12:00", "17:00"),
    "evening": ("17:00", "21:00"),
}


def resolve_time_preference(time_pref):
    """
    Converts a time preference string into a (start, end) tuple of HH:MM strings.
    Handles: "morning", "afternoon", "evening", "10 AM", "3 PM", "14:00", etc.
    Returns: ("10:00", "10:30") for specific times, or ("06:00", "12:00") for periods.
    Returns None if unresolvable.
    """
    if not time_pref:
        return None

    lower = time_pref.strip().lower()
    if lower in TIME_PERIODS:
        return TIME_PERIODS[lower]

    # Try parsing as a specific time like "10 AM", "3 PM", "14:00"
    cal = parsedatetime.Calendar()
    time_struct, status = cal.parse(lower)
    if status == 2 or status == 3:  # parsed as time or datetime
        parsed = datetime(*time_struct[:6])
        start = parsed.strftime("%H:%M")
        end = (parsed + timedelta(hours=1)).strftime("%H:%M")
        return (start, end)

    return None


def filter_ranges_by_time(open_ranges, time_window):
    """
    Filters open_ranges to only include slots that overlap with the time_window.
    open_ranges: [["09:00", "10:30"], ["11:00", "12:00"]]
    time_window: ("10:00", "12:00")
    Returns: [["10:00", "10:30"], ["11:00", "12:00"]]
    """
    window_start = datetime.strptime(time_window[0], "%H:%M")
    window_end = datetime.strptime(time_window[1], "%H:%M")

    filtered = []
    for r in open_ranges:
        range_start = datetime.strptime(r[0], "%H:%M")
        range_end = datetime.strptime(r[1], "%H:%M")

        # Find the overlap
        overlap_start = max(range_start, window_start)
        overlap_end = min(range_end, window_end)

        if overlap_start < overlap_end:
            filtered.append([overlap_start.strftime("%H:%M"), overlap_end.strftime("%H:%M")])

    return filtered


def check_availability(specialty=None, date_str=None, doctor_name=None, time_preference=None):
    """
    Returns available time ranges for doctors matching the specialty.
    date_str can be "2026-02-20", "Monday", "tomorrow", etc.
    time_preference can be "morning", "afternoon", "evening", "10 AM", etc.
    Returns: (preferred_slots, all_day_slots) if time_preference is given,
             otherwise just all_day_slots.
    """
    resolved = resolve_date(date_str)
    if not resolved:
        return [], []

    requested_day = resolved.date().isoformat()
    requested_time = resolved.time()
    day_of_week = resolved.strftime('%A')

    if doctor_name:
        doctors = db.get_doctor_by_name(doctor_name)
    else:
        doctors = db.get_doctors_by_department(specialty)
        if not doctors:
            return [], []

    all_day_results = []
    for doctor in doctors:
        availability = doctor['availability']
        day_ranges = availability.get(day_of_week.lower(), [])
        if not day_ranges:
            continue

        booked = db.get_booked_appointments(doctor["id"], requested_day)
        open_ranges = subtract_booked_from_ranges(day_ranges, booked)

        if open_ranges:
            all_day_results.append({
                "doctor_name": doctor.get("name", ""),
                "doctor_id": doctor["id"],
                "date": requested_day,
                "available_ranges": open_ranges
            })

    # If no time preference, return all day slots
    time_window = resolve_time_preference(time_preference)
    if not time_window:
        return all_day_results, []

    # Filter by time preference
    preferred_results = []
    for entry in all_day_results:
        filtered = filter_ranges_by_time(entry["available_ranges"], time_window)
        if filtered:
            preferred_results.append({
                **entry,
                "available_ranges": filtered
            })

    return preferred_results, all_day_results

def format_appointments_for_display(appointments):
    """Format appointment list for LLM prompt."""
    formatted = []
    for appt in appointments:
        doctor_info = appt.get("doctors", {})
        # Convert "08:30:00" → "8:30 AM"
        raw_time = appt["appointment_time"]
        try:
            dt = datetime.strptime(raw_time[:5], "%H:%M")
            display_time = dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            display_time = raw_time
        formatted.append({
            "id": appt["id"],
            "doctor_name": doctor_info.get("name", "Unknown"),
            "specialty": doctor_info.get("specialty", "Unknown"),
            "date": appt["appointment_date"],
            "time": display_time
        })
    return formatted


def format_appointments_for_prompt(appointments):
    """Format appointment list into a readable numbered list for the LLM prompt."""
    lines = []
    for i, appt in enumerate(appointments, 1):
        lines.append(f"{i}. {appt['doctor_name']} ({appt['specialty']}) on {appt['date']} at {appt['time']}")
    return "\n".join(lines)


def format_slots_for_prompt(slots):
    """Format available slots into a readable numbered list for the LLM prompt."""
    lines = []
    counter = 1
    for entry in slots:
        doctor = entry.get("doctor_name", "Unknown")
        date = entry.get("date", "Unknown")
        try:
            date_display = datetime.strptime(date, "%Y-%m-%d").strftime("%A, %B %d")
        except Exception:
            date_display = date
        for time_range in entry.get("available_ranges", []):
            # doctor names already include "Dr." prefix — don't add it again
            lines.append(f"{counter}. {doctor} on {date_display} from {time_range[0]} to {time_range[1]}")
            counter += 1
    return "\n".join(lines)

def get_patient_info_node(state, generate_response):
    """Looks up patient by phone"""

    phone_number = state.get("phone_number")
    patient = db.get_patient_by_phone(phone_number) if phone_number else None
    if not patient:
        return {**state, "patient_info": None, "state": "AWAITING_PATIENT_INFO"}

    patient_name = f"{patient['first_name']} {patient['last_name']}"
    return {**state, "patient_info": {"patient_name": patient_name, "patient_id": patient["id"]}, "state":state.get("sub_action")+"_"+"PATIENT_FOUND"}


if __name__ == "__main__":
    print(subtract_booked_from_ranges([["09:00", "12:00"], ["16:00", "20:00"]], []))