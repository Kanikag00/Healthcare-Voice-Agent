from typing import TypedDict, Optional, List

class AgentState(TypedDict):
    session_id : str
    phone_number: str
    patient_message: str
    state: str
    sub_action: Optional[str]
    appointment_details: Optional[dict]
    available_slots: List[dict]
    slot_response: Optional[str]
    selected_slot: Optional[dict]
    existing_appointments: List[dict]
    selected_appointment:Optional[dict]
    patient_info:Optional[dict]
    bills:  List[dict]
    lab_reports:  List[dict]
    response: str
    end_call: bool
    summary:str
    alternate_phone_number: str

