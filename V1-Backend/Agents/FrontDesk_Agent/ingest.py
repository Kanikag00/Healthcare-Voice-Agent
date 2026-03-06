import json
import ollama
from pinecone import Pinecone
from dotenv import load_dotenv
import os

load_dotenv()

EMBED_MODEL = "mxbai-embed-large"
PINECONE_INDEX = os.getenv("PINECONE_INDEX")

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(PINECONE_INDEX)

with open("hospital_info.json", "r") as f:
    faqs = json.load(f)

vectors = []
for i, faq in enumerate(faqs):
    text = f"search_document: {faq['question']} {faq['answer']}"
    embedding = ollama.embed(model=EMBED_MODEL, input=text)
    vectors.append({
        "id": f"faq-{i}",
        "values": embedding["embeddings"][0],
        "metadata": {
            "question": faq["question"],
            "answer": faq["answer"]
        }
    })
    print(f"  Embedded {i+1}/{len(faqs)}: {faq['question'][:60]}")

index.upsert(vectors=vectors)
print(f"\nUpserted {len(vectors)} vectors into '{PINECONE_INDEX}'")
print(index.describe_index_stats())
