from langgraph.graph import StateGraph, START, END
from langchain_ollama import ChatOllama
from langgraph.types import interrupt
import sys, os
_BACKEND = os.path.dirname(__file__)
sys.path.insert(0, _BACKEND)
# book.py uses `from utils import ...` which requires the Appointment_Agent dir on path
sys.path.insert(0, os.path.join(_BACKEND, "Agents", "Appointment_Agent"))

from state import AgentState
from Agents.Appointment_Agent.appointment_graph import graph as _appt_graph_builder
from Agents.Billing_Agent.billing_agent import billing_lookup_node, billing_select_node
from Agents.Lab_Report_Agent.lab_report_agent import (
    lab_lookup_node,
    lab_alt_phone_node,
    lab_select_test_node,
    lab_no_report_choice_node,
)
from Agents.FrontDesk_Agent.frontdesk_agent import frontdesk_node

EMERGENCY_KEYWORDS = [
    "chest pain", "heart attack", "cardiac arrest", "can't breathe", "cannot breathe",
    "difficulty breathing", "breathless", "choking", "unconscious", "not breathing",
    "severe bleeding", "heavy bleeding", "stroke", "paralysis", "seizure", "convulsion",
    "overdose", "poisoning", "anaphylaxis", "allergic reaction", "severe pain",
    "head injury", "broken bone", "fracture", "accident", "fell down", "fainted",
    "collapsed", "high fever", "unresponsive", "emergency",
]

llm = ChatOllama(model="llama3.1:8b", temperature=0.3, seed=42)


def generate_response(prompt: str) -> str:
    response = llm.invoke([
        ("system", (
            "You are a hospital receptionist answering an incoming patient phone call. "
            "Respond directly and concisely — 1-2 sentences only. "
            "Do not introduce yourself or the hospital. "
            "Never use placeholders like [Hospital Name] or [Patient's Name]. "
            "Answer only what is needed. Do not add unnecessary information."
        )),
        ("human", prompt),
    ])
    return response.content


def get_current_state(state: AgentState) -> str:
    return state["state"]


# ========== ROUTER ==========

def router_node(state: AgentState) -> AgentState:
    """Classifies patient intent. Emergency keywords take priority over LLM."""

    message = state["patient_message"]

    if any(kw in message.lower() for kw in EMERGENCY_KEYWORDS):
        return {**state, "state": "EMERGENCY"}

    response = llm.invoke([
        ("system", """You are a hospital call router. Classify the patient request into exactly one of these categories:
appointment | billing | lab | frontdesk | call_end | emergency

- appointment  →  anything about booking, cancelling, or rescheduling a doctor visit
- billing      →  payment, bills, invoice, insurance questions
- lab          →  lab results, test reports, test status
- frontdesk    →  general questions, visiting hours, directions, other FAQs
- call_end     →  patient says goodbye, thanks, that's all, wants to hang up
- emergency    →  urgent medical situation

Examples:
  "I want to book a cardiology appointment" → appointment
  "Please cancel my appointment" → appointment
  "Can I reschedule with Dr. Sharma?" → appointment
  "What are my test results?" → lab
  "I need to pay my bill" → billing
  "Goodbye, that's all" → call_end

Return ONLY the single lowercase category word. No punctuation, no extra text."""),
        ("human", message),
    ])

    intent = response.content.strip().lower()
    if intent not in ("appointment", "billing", "lab", "frontdesk", "call_end", "emergency"):
        intent = "frontdesk"

    print(f"ROUTER → {intent}")
    return {**state, "state": intent.upper()}


# ========== EMERGENCY / CALL END ==========

def emergency_node(state: AgentState) -> AgentState:
    return {
        **state,
        "state": "COMPLETED",
        "response": "Transferring you to our emergency ward now. Please stay on the line.",
        "end_call": True,
    }


def call_end_node(state: AgentState) -> AgentState:
    response = generate_response(
        "The patient is ending the call. Say a warm, brief goodbye. 1 sentence."
    )
    return {**state, "state": "COMPLETED", "response": response, "end_call": True}


# ========== BILLING ==========

def billing_lookup(state: AgentState) -> AgentState:
    print("IN billing_lookup node")
    return billing_lookup_node(state, generate_response)


def billing_select(state: AgentState) -> AgentState:
    print("IN billing_select node")
    return billing_select_node(state, generate_response)


# ========== LAB ==========

def lab_lookup(state: AgentState) -> AgentState:
    print("IN lab_lookup node")
    return lab_lookup_node(state, generate_response)


def lab_alt_phone(state: AgentState) -> AgentState:
    print("IN lab_alt_phone node")
    return lab_alt_phone_node(state, generate_response)


def lab_select_test(state: AgentState) -> AgentState:
    print("IN lab_select_test node")
    return lab_select_test_node(state, generate_response)


def lab_no_report_choice(state: AgentState) -> AgentState:
    print("IN lab_no_report_choice node")
    return lab_no_report_choice_node(state, generate_response)


# ========== FRONT DESK ==========

def frontdesk(state: AgentState) -> AgentState:
    print("IN frontdesk node")
    return frontdesk_node(state, generate_response)


# ========== GRAPH ==========

# Appointment subgraph — compiled without checkpointer; parent manages state.
appointment_subgraph = _appt_graph_builder.compile()

graph = StateGraph(AgentState)

# ---- Nodes ----
graph.add_node("router", router_node)
graph.add_node("appointment", appointment_subgraph)
graph.add_node("billing_lookup", billing_lookup)
graph.add_node("billing_select", billing_select)
graph.add_node("lab_lookup", lab_lookup)
graph.add_node("lab_alt_phone", lab_alt_phone)
graph.add_node("lab_select_test", lab_select_test)
graph.add_node("lab_no_report_choice", lab_no_report_choice)
graph.add_node("frontdesk", frontdesk)
graph.add_node("emergency", emergency_node)
graph.add_node("call_end", call_end_node)

# ---- Edges ----
graph.add_edge(START, "router")

graph.add_conditional_edges("router", get_current_state, {
    "APPOINTMENT": "appointment",
    "BILLING":     "billing_lookup",
    "LAB":         "lab_lookup",
    "FRONTDESK":   "frontdesk",
    "CALL_END":    "call_end",
    "EMERGENCY":   "emergency",
})

# Appointment subgraph: on FRONTDESK state, redirect to frontdesk node; otherwise done.
graph.add_conditional_edges(
    "appointment",
    lambda state: "frontdesk" if state.get("state") == "FRONTDESK" else END,
)

# Billing flow
graph.add_conditional_edges("billing_lookup", get_current_state, {
    "AWAITING_BILL_SELECTION": "billing_select",
    "COMPLETED":               END,
    "FRONTDESK":               "frontdesk",
})
graph.add_conditional_edges("billing_select", get_current_state, {
    "AWAITING_BILL_SELECTION": "billing_select",  # loop if bill not identified
    "COMPLETED":               END,
})

# Lab flow
graph.add_conditional_edges("lab_lookup", get_current_state, {
    "AWAITING_PHONE_NUMBER":    "lab_alt_phone",
    "AWAITING_TEST_SELECTION":  "lab_select_test",
    "AWAITING_NO_REPORT_CHOICE": "lab_no_report_choice",
    "COMPLETED":                END,
})
graph.add_conditional_edges("lab_alt_phone", get_current_state, {
    "AWAITING_PHONE_NUMBER":     "lab_alt_phone",      # patient gives another number
    "AWAITING_TEST_SELECTION":   "lab_select_test",
    "AWAITING_NO_REPORT_CHOICE": "lab_no_report_choice",
    "COMPLETED":                 END,
})
graph.add_conditional_edges("lab_select_test", get_current_state, {
    "AWAITING_TEST_SELECTION": "lab_select_test",  # loop if test not identified
    "COMPLETED":               END,
})
graph.add_conditional_edges("lab_no_report_choice", get_current_state, {
    "FRONTDESK": "frontdesk",
    "COMPLETED": END,
    "ROUTING":   "router",   # something_else: re-run router with patient's new request
})

# Terminal nodes
graph.add_edge("frontdesk", END)
graph.add_edge("emergency", END)
graph.add_edge("call_end", END)


if __name__ == "__main__":
    import argparse, uuid
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    parser = argparse.ArgumentParser(description="Healthcare Voice Agent — interactive test")
    parser.add_argument("--phone", default="9873892000", help="Caller phone number")
    parser.add_argument("--thread", default=None,        help="Thread ID (default: random)")
    parser.add_argument("--debug", action="store_true",  help="Show internal state after each turn")
    args = parser.parse_args()

    thread_id = args.thread or f"test-{uuid.uuid4().hex[:8]}"
    memory    = MemorySaver()
    compiled  = graph.compile(checkpointer=memory)
    config    = {"configurable": {"thread_id": thread_id}}

    def get_agent_msg(result):
        snapshot = compiled.get_state(config)
        if snapshot.tasks and snapshot.tasks[0].interrupts:
            return snapshot.tasks[0].interrupts[0].value
        return result.get("response", "")

    def print_debug():
        snap = compiled.get_state(config)
        v    = snap.values
        print(f"\n  ┌─ DEBUG ──────────────────────────────────────")
        print(f"  │ state       : {v.get('state')}")
        print(f"  │ sub_action  : {v.get('sub_action')}")
        print(f"  │ patient_info: {v.get('patient_info')}")
        print(f"  │ appt_details: {v.get('appointment_details')}")
        print(f"  │ selected_apt: {v.get('selected_appointment')}")
        print(f"  │ selected_slt: {v.get('selected_slot')}")
        print(f"  │ end_call    : {v.get('end_call')}")
        print(f"  └──────────────────────────────────────────────\n")

    # ── Header ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Healthcare Voice Agent — Interactive Test")
    print(f"  Phone : {args.phone}")
    print(f"  Thread: {thread_id}   (--thread {thread_id} to replay)")
    print(f"  Debug : {'ON' if args.debug else 'OFF'}   (--debug to toggle)")
    print("  Type 'quit' to exit | 'debug' to toggle debug mid-session")
    print("=" * 60 + "\n")

    debug = args.debug

    first_msg = input("You: ").strip()
    if not first_msg or first_msg.lower() in ("quit", "exit", "q"):
        sys.exit(0)

    result = compiled.invoke(
        {"patient_message": first_msg, "phone_number": args.phone},
        config,
    )
    agent_msg = get_agent_msg(result)
    print(f"\nAgent: {agent_msg}\n")
    if debug:
        print_debug()
    if result.get("end_call"):
        print("(Call ended)\n")
        sys.exit(0)

    while True:
        try:
            msg = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n(Interrupted)")
            break

        if msg.lower() in ("quit", "exit", "q"):
            break
        if msg.lower() == "debug":
            debug = not debug
            print(f"  (debug {'ON' if debug else 'OFF'})\n")
            continue
        if msg.lower() == "state":
            print_debug()
            continue
        if not msg:
            continue

        snapshot = compiled.get_state(config)
        pending_interrupt = bool(snapshot.tasks and snapshot.tasks[0].interrupts)
        if pending_interrupt:
            result = compiled.invoke(Command(resume=msg), config)
        else:
            result = compiled.invoke({"patient_message": msg, "phone_number": args.phone}, config)
        agent_msg = get_agent_msg(result)
        if agent_msg:
            print(f"\nAgent: {agent_msg}\n")
        if debug:
            print_debug()
        if result.get("end_call"):
            print("(Call ended)\n")
            break
