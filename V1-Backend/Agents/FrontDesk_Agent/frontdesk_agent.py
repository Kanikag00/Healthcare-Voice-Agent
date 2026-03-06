import ollama
from pinecone import Pinecone
from dotenv import load_dotenv
import os

load_dotenv()

EMBED_MODEL = "mxbai-embed-large"
PINECONE_INDEX = os.getenv("PINECONE_INDEX")
RELEVANCE_THRESHOLD = 0.6


class FrontDeskAgent:
    def __init__(self):
        self.model = os.getenv("LLM_MODEL", "gemma2:2b")
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        self.index = pc.Index(PINECONE_INDEX)

    def handle_request(self, session_id, patient_message):
        print(f"FRONT DESK AGENT CALLED with: {patient_message}")

        query_embedding = ollama.embed(model=EMBED_MODEL, input=f"search_query: {patient_message}")

        results = self.index.query(
            vector=query_embedding["embeddings"][0],
            top_k=3,
            include_metadata=True
        )

        if not results["matches"] or results["matches"][0]["score"] < RELEVANCE_THRESHOLD:
            return "I'm not sure about that. Let me connect you to our receptionist who can help you better."

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

        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}]
        )

        return response["message"]["content"]
