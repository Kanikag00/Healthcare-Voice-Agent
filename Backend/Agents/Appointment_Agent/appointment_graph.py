from langgraph.graph import StateGraph, START, END
from langchain_ollama import ChatOllama
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from state import AgentState
from Agents.Appointment_Agent.prompts import prompts_builder
from Agents.Appointment_Agent.book import (
    book_get_slots_node,
    book_select_slot_node,
    new_patient_info,
    book_finalize_node,
)
from Agents.Appointment_Agent.modify_appointment import (
    modify_lookup_node,
    modify_select_node,
    cancel_confirm_node,
    reschedule_details_node,
    reschedule_slot_node,
    get_alternate_number,
)
from Agents.Appointment_Agent.utils import get_patient_info_node
from langgraph.types import interrupt

llm = ChatOllama(
    model="llama3.1:8b",
    temperature=0.4,
    seed=42
)


def classify_appt_type(state: AgentState) -> AgentState:
    """ The function is to identify the type of appointment - book/reschedule/cancel using LLM"""
    message = [
        (
            "system",
            """You are an assistant at healthcare that classifies the help patient needs with their appointment
                - book, reschedule or cancel. Return ONLY one of these three words with no punctuation, quotes, or extra text.
            """
        ),
        ("human", state["patient_message"]),
    ]
    response = llm.invoke(message)
    print("RESPONSE : ", response.content.strip().lower())
    return {**state, "sub_action": response.content.strip().lower()}


def get_appt_type(state: AgentState) -> str:
    return state["sub_action"]


def generate_response(prompt: str) -> str:
    response = llm.invoke([
        ("system", "You are a warm, professional hospital voice assistant."),
        ("human", prompt)
    ])
    return response.content


def extract_info(state: AgentState) -> dict:
    print("EXTRACTING INFORMATION : state = ", state.get("state"))
    print("prompt = ", prompts_builder(state))
    response = llm.invoke([
        ("system", "You are an assistant at healthcare to extract information from patient's message."),
        ("human", prompts_builder(state))
    ])
    try:
        print("EXTRACTED INFO -> ", response.content)
        print("YAYYYYY: ", json.loads(response.content))
        return json.loads(response.content)
    except json.JSONDecodeError:
        return {}


def extract_appointment_details_node(state: AgentState) -> AgentState:
    response = llm.invoke([
        ("system", """You are an assistant at healthcare. Extract appointment details from the patient message.
            Return ONLY raw JSON with these 4 fields with no markdowns:
            - "doctor_name": a specific person's name like "Dr. Reddy" or "Dr. Faizan". If the patient says a role like "cardiologist" or "dentist", set this to "not mentioned".
            - "specialty": department or role (cardiology, dermatology, pediatrics, neurology, orthopedics, general medicine, cardiologist, etc.) or "not mentioned"
            - "preferred_date": the date or any day of week or reference of day (like "tomorrow", "Monday", "next Friday", "Feb 20") or "not mentioned"
            - "time_preference": the exact time or parts of the day (like "morning", "afternoon", "evening", "10 AM", "3 PM") or "not mentioned" """
         ),
        ("human", state["patient_message"])
    ])

    try:
        print("EXTRACTED INFO -> ", response.content)
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        appt_details = json.loads(raw.strip())

        appointment = state.get("appointment_details") or {}
        raw_name = appt_details.get("doctor_name", "not mentioned")
        if raw_name not in (None, "not mentioned") and raw_name.lower() in state["patient_message"].lower():
            appointment["doctor_name"] = raw_name
        if appt_details["specialty"] not in (None, "not mentioned"):
            appointment["specialty"] = appt_details["specialty"]
        if appt_details["preferred_date"] not in (None, "not mentioned"):
            appointment["preferred_date"] = appt_details["preferred_date"]
        if appt_details["time_preference"] not in (None, "not mentioned"):
            appointment["time_preference"] = appt_details["time_preference"]

        print("APPT DETAILS:   ", appointment)
        return {**state, "appointment_details": appointment}

    except json.JSONDecodeError:
        return state


def validate_appt_details_node(state: AgentState) -> AgentState:
    print("IN VALIDATING NODE")
    missing = []
    appt_details = state.get("appointment_details") or {}
    if appt_details.get("doctor_name") in (None, "not mentioned") and appt_details.get("specialty") in (None, "not mentioned"):
        missing.append("doctor's name or specialty")
    if appt_details.get("preferred_date") in (None, "not mentioned"):
        missing.append("preferred date")
    if appt_details.get("time_preference") in (None, "not mentioned"):
        missing.append("preferred time")

    if missing:
        question = f"Could you please share the {' and '.join(missing)}?"
        patient_response = interrupt(question)
        appt_details["is_complete"] = False
        return {**state, "patient_message": patient_response, "appointment_details": appt_details}

    appt_details["is_complete"] = True
    return {**state, "appointment_details": appt_details}


def get_current_state(state: AgentState) -> str:
    return state["state"]


# ---- Book wrappers ----
def book_get_slots(state: AgentState) -> AgentState:
    print("IN BOOK_GET_SLOTS NODE")
    return book_get_slots_node(state, generate_response)


def book_select_slot(state: AgentState) -> AgentState:
    print("IN book_select_slot node")
    return book_select_slot_node(state, extract_info)


def book_finalize(state: AgentState) -> AgentState:
    print("IN book_finalize node")
    return book_finalize_node(state, generate_response)


def new_patient_node(state: AgentState) -> AgentState:
    print("IN new_patient_node node")
    return new_patient_info(state, generate_response, extract_info)


# ---- Shared patient lookup ----
def get_patient_info(state: AgentState) -> AgentState:
    print("In get_patient_info node")
    state = get_patient_info_node(state, generate_response)
    if state.get("sub_action") == "book" and state.get("patient_info") is None:
        agent_response = generate_response(
            "The patient wants to book an appointment but we don't have their record yet. "
            "Ask for their first name, last name, and date of birth in a warm, professional way. "
            "Keep it to 1-2 sentences."
        )
        patient_response = interrupt(agent_response)
        return {**state, "patient_message": patient_response}

    if state.get("sub_action") in ("reschedule", "cancel") and state.get("patient_info") is None:
        agent_response = generate_response(
            "We don't have a patient record for this phone number. "
            "Would you like to try another number? "
            "Keep it to 1-2 sentences."
        )
        patient_message = interrupt(agent_response)
        return {**state, "patient_message": patient_message, "state": "AWAITING_ALTERNATE_NUMBER"}

    return state


# ---- Cancel / Reschedule wrappers ----
def modify_lookup(state: AgentState) -> AgentState:
    print("IN modify_lookup node")
    return modify_lookup_node(state, generate_response)


def modify_select(state: AgentState) -> AgentState:
    print("IN modify_select node")
    return modify_select_node(state, extract_info, generate_response)


def cancel_confirm(state: AgentState) -> AgentState:
    print("IN cancel_confirm node")
    return cancel_confirm_node(state, extract_info, generate_response)


def reschedule_details(state: AgentState) -> AgentState:
    print("IN reschedule_details node")
    return reschedule_details_node(state, extract_info, generate_response)


def reschedule_slot(state: AgentState) -> AgentState:
    print("IN reschedule_slot node")
    return reschedule_slot_node(state, generate_response)


def alternate_number(state: AgentState) -> AgentState:
    print("IN ALTERNATE NUMBER NODE")
    return get_alternate_number(state, generate_response, extract_info)


# ========== GRAPH ==========
graph = StateGraph(AgentState)

# ---- Nodes ----
graph.add_node(classify_appt_type)
graph.add_node("extract", extract_appointment_details_node)
graph.add_node("validate", validate_appt_details_node)
graph.add_node("get_available_slots", book_get_slots)
graph.add_node("select_slot", book_select_slot)
graph.add_node("patient_info", get_patient_info)
graph.add_node("new_patient", new_patient_node)
graph.add_node("finalize_booking", book_finalize)
graph.add_node("patient_appointments", modify_lookup)
graph.add_node("modify_select", modify_select)
graph.add_node("cancel_confirm", cancel_confirm)
graph.add_node("reschedule_details", reschedule_details)
graph.add_node("reschedule_slot", reschedule_slot)
graph.add_node("alternate_number", alternate_number)

# ---- Edges ----
graph.add_edge(START, "classify_appt_type")

graph.add_conditional_edges("classify_appt_type", get_appt_type, {
    "book": "extract",
    "reschedule": "patient_info",
    "cancel": "patient_info",
})

graph.add_edge("extract", "validate")

graph.add_conditional_edges(
    "validate",
    lambda state: "extract" if not state["appointment_details"]["is_complete"] else "get_available_slots",
)

graph.add_conditional_edges(
    "get_available_slots",
    get_current_state,
    {
        "AWAITING_DIFFERENT_DAY": "extract",
        "AWAITING_SLOT_SELECTION": "select_slot",
    }
)

def route_after_slot_selected(state: AgentState) -> str:
    if state["state"] == "AWAITING_NEW_SLOTS":
        return "AWAITING_NEW_SLOTS"
    if state["state"] == "SLOT_SELECTED":
        return "reschedule_slot" if state.get("sub_action") == "reschedule" else "patient_info"
    return state["state"]

graph.add_conditional_edges(
    "select_slot",
    route_after_slot_selected,
    {
        "AWAITING_NEW_SLOTS": "get_available_slots",
        "patient_info": "patient_info",
        "reschedule_slot": "reschedule_slot",
    }
)

graph.add_conditional_edges(
    "patient_info",
    get_current_state,
    {
        "AWAITING_PATIENT_INFO": "new_patient",
        "book_PATIENT_FOUND": "finalize_booking",
        "AWAITING_ALTERNATE_NUMBER": "alternate_number",
        "reschedule_PATIENT_FOUND": "patient_appointments",
        "cancel_PATIENT_FOUND": "patient_appointments",
        "FRONTDESK": END,
    }
)

graph.add_conditional_edges(
    "new_patient",
    get_current_state,
    {
        "AWAITING_PATIENT_INFO": "new_patient",
        "FRONTDESK": END,
        "FINALIZE_BOOKING": "finalize_booking",
    }
)

graph.add_edge("finalize_booking", END)

graph.add_conditional_edges(
    "patient_appointments",
    get_current_state,
    {
        "AWAITING_CANCEL_CONFIRMATION": "cancel_confirm",
        "AWAITING_CANCEL_SELECTION": "modify_select",
        "AWAITING_RESCHEDULE_DETAILS": "reschedule_details",
        "AWAITING_RESCHEDULE_SELECTION": "modify_select",
        "FRONTDESK": END,
    }
)

graph.add_conditional_edges(
    "modify_select",
    get_current_state,
    {
        "AWAITING_CANCEL_SELECTION": "modify_select",       # loop when extract failed
        "AWAITING_RESCHEDULE_SELECTION": "modify_select",  # loop when extract failed
        "AWAITING_CANCEL_CONFIRMATION": "cancel_confirm",
        "AWAITING_RESCHEDULE_DETAILS": "reschedule_details",
    }
)

graph.add_edge("cancel_confirm", END)

graph.add_conditional_edges(
    "reschedule_details",
    get_current_state,
    {
        "AWAITING_RESCHEDULE_DATETIME": "reschedule_details",  # loop when date/time missing
        "AWAITING_RESCHEDULE_SLOTS": "get_available_slots",    # hand off to shared slot flow
    }
)

graph.add_conditional_edges(
    "reschedule_slot",
    get_current_state,
    {
        "FRONTDESK": END,
        "COMPLETED": END,
    }
)

graph.add_conditional_edges(
    "alternate_number",
    get_current_state,
    {
        "PATIENT_FOUND": "patient_appointments",
        "FRONTDESK": END,
    }
)


# graph = graph.compile()
# png_data = graph.get_graph().draw_mermaid_png()
# file_path = "graph_output.png"
# with open(file_path, "wb") as f:
#     f.write(png_data)

if __name__ == "__main__":
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    memory = MemorySaver()
    test_graph = graph.compile(checkpointer=memory)

    config = {"configurable": {"thread_id": "test-20"}}

    def get_agent_msg(result, config):
        snapshot = test_graph.get_state(config)
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            return snapshot.tasks[0].interrupts[0].value
        return result.get("response", "")

    print("=== Appointment Agent Test ===")
    first_msg = input("You: ")
    result = test_graph.invoke({"patient_message": first_msg, "phone_number": "987389200"}, config)
    print(f"Agent: {get_agent_msg(result, config)}\n")

    while True:
        msg = input("You: ").strip()
        if msg.lower() in ["quit", "exit", "q"]:
            break
        result = test_graph.invoke(Command(resume=msg), config)
        agent_msg = get_agent_msg(result, config)
        if agent_msg:
            print(f"Agent: {agent_msg}\n")
        else:
            print("(Conversation ended)\n")
            break
