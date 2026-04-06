import ollama
from pinecone import Pinecone
from dotenv import load_dotenv
import os
from state import AgentState

load_dotenv()

EMBED_MODEL = "mxbai-embed-large"
PINECONE_INDEX = os.getenv("PINECONE_INDEX")
RELEVANCE_THRESHOLD = 0.6

_pc = None
_index = None


def _get_index():
    global _pc, _index
    if _index is None:
        _pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        _index = _pc.Index(PINECONE_INDEX)
    return _index


# -----------NODE 1-------------
def frontdesk_node(state: AgentState, generate_response) -> AgentState:
    """Answers patient FAQ using RAG (Pinecone + embeddings). Falls back to human transfer."""

    patient_message = state["patient_message"]
    index = _get_index()

    query_embedding = ollama.embed(model=EMBED_MODEL, input=f"search_query: {patient_message}")

    results = index.query(
        vector=query_embedding["embeddings"][0],
        top_k=3,
        include_metadata=True,
    )

    if not results["matches"] or results["matches"][0]["score"] < RELEVANCE_THRESHOLD:
        response = "I'm not sure about that. Let me connect you to our receptionist who can help you better."
        return {**state, "state": "COMPLETED", "response": response}

    context = "\n".join([
        f"Q: {m['metadata']['question']}\nA: {m['metadata']['answer']}"
        for m in results["matches"]
    ])

    prompt = f"""You are a helpful hospital front desk receptionist.
Answer the patient's question using ONLY the information provided below.
If the information doesn't cover the question, say you'll connect them to the human receptionist.

Hospital Information:
{context}

Patient Question: {patient_message}"""

    response = generate_response(prompt)
    return {**state, "state": "COMPLETED", "response": response}
