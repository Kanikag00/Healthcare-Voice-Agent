import ollama
import json
import time
from pinecone import Pinecone
from dotenv import load_dotenv
import os

load_dotenv()

# Model -> (dimensions, pinecone index name)
MODEL_CONFIG = {
    "nomic-embed-text":            (768,  "hospital-benchmark"),
    "snowflake-arctic-embed:110m": (768,  "hospital-benchmark"),
    "mxbai-embed-large":           (1024, "hospital-1024"),
    "bge-m3":                      (1024, "hospital-1024"),
    "all-minilm":                  (384,  "hospital-384"),
}

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

# Test queries with expected FAQ match
test_queries = [
    {"query": "When can I visit the hospital?", "expected": "What are the visiting hours?"},
    {"query": "Where can I park my car?", "expected": "Is parking available at the hospital?"},
    {"query": "Do you accept insurance?", "expected": "What insurance plans do you accept?"},
    {"query": "How do I get my test results?", "expected": "How do I get my lab reports or test results?"},
    {"query": "Is there food available?", "expected": "Is there a cafeteria or canteen?"},
    {"query": "What rooms do you have?", "expected": "What are the room types and charges?"},
    {"query": "Can I do a video call with doctor?", "expected": "Do you offer teleconsultation or online appointments?"},
    {"query": "Where is the hospital?", "expected": "What is the hospital name and where is it located?"},
    {"query": "I need an ambulance", "expected": "Do you have ambulance services?"},
    {"query": "What should I carry for admission?", "expected": "What should I bring for a hospital admission?"},
]

def run_benchmark(model_name):
    if model_name not in MODEL_CONFIG:
        print(f"Unknown model '{model_name}'. Available: {list(MODEL_CONFIG.keys())}")
        return None

    _, index_name = MODEL_CONFIG[model_name]
    index = pc.Index(index_name)
    print(f"  Using index: {index_name}")

    results = {
        "model": model_name,
        "total_queries": len(test_queries),
        "correct_top1": 0,
        "correct_top3": 0,
        "avg_embedding_latency_ms": 0,
        "avg_search_latency_ms": 0,
        "avg_llm_latency_ms": 0,
        "avg_top1_score": 0,
        "queries": []
    }

    total_embed_time = 0
    total_search_time = 0
    total_llm_time = 0
    total_top1_score = 0

    for test in test_queries:
        query = test["query"]
        expected = test["expected"]

        # 1. Embedding latency
        embed_start = time.time()
        query_embedding = ollama.embed(model=model_name, input=f"search_query: {query}")
        embed_time = (time.time() - embed_start) * 1000  # ms

        # 2. Pinecone search latency
        search_start = time.time()
        search_results = index.query(
            vector=query_embedding["embeddings"][0],
            top_k=3,
            include_metadata=True
        )
        search_time = (time.time() - search_start) * 1000  # ms

        # 3. Check if expected FAQ is in top 1 / top 3
        top_matches = []
        in_top1 = False
        in_top3 = False
        for i, match in enumerate(search_results["matches"]):
            matched_q = match["metadata"]["question"]
            top_matches.append({"rank": i + 1, "score": match["score"], "question": matched_q})
            if matched_q == expected:
                if i == 0:
                    in_top1 = True
                in_top3 = True

        if in_top1:
            results["correct_top1"] += 1
        if in_top3:
            results["correct_top3"] += 1

        top1_score = search_results["matches"][0]["score"] if search_results["matches"] else 0

        # 4. LLM response latency
        context = "\n".join([
            f"Q: {m['metadata']['question']}\nA: {m['metadata']['answer']}"
            for m in search_results["matches"]
        ])
        prompt = f"""You are a helpful hospital front desk receptionist.
Answer the patient's question using ONLY the information provided below.
If the information doesn't cover the question, say you'll connect them to the human receptionist.

Hospital Information:
{context}

Patient Question: {query}"""

        llm_start = time.time()
        llm_response = ollama.chat(model="gemma2:2b", messages=[{"role": "user", "content": prompt}])
        llm_time = (time.time() - llm_start) * 1000  # ms

        total_embed_time += embed_time
        total_search_time += search_time
        total_llm_time += llm_time
        total_top1_score += top1_score

        query_result = {
            "query": query,
            "expected": expected,
            "in_top1": in_top1,
            "in_top3": in_top3,
            "top1_score": round(top1_score, 4),
            "embedding_latency_ms": round(embed_time, 2),
            "search_latency_ms": round(search_time, 2),
            "llm_latency_ms": round(llm_time, 2),
            "top_matches": top_matches,
            "llm_response": llm_response["message"]["content"]
        }
        results["queries"].append(query_result)

        # Print progress
        status = "HIT" if in_top1 else ("TOP3" if in_top3 else "MISS")
        print(f"  [{status}] {query} -> [{top1_score:.3f}] {top_matches[0]['question']}")

    n = len(test_queries)
    results["correct_top1"] = results["correct_top1"]
    results["correct_top3"] = results["correct_top3"]
    results["top1_accuracy"] = f"{results['correct_top1']}/{n} ({results['correct_top1']/n*100:.0f}%)"
    results["top3_accuracy"] = f"{results['correct_top3']}/{n} ({results['correct_top3']/n*100:.0f}%)"
    results["avg_embedding_latency_ms"] = round(total_embed_time / n, 2)
    results["avg_search_latency_ms"] = round(total_search_time / n, 2)
    results["avg_llm_latency_ms"] = round(total_llm_time / n, 2)
    results["avg_top1_score"] = round(total_top1_score / n, 4)

    return results


BENCHMARK_FILE = "/Users/kanika/Healthcare Voice Agent/Backend/Agents/FrontDesk_Agent/benchmark_results.json"

def load_all_results():
    if os.path.exists(BENCHMARK_FILE):
        with open(BENCHMARK_FILE, "r") as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    return {}

SUMMARY_FILE = "/Users/kanika/Healthcare Voice Agent/Backend/Agents/FrontDesk_Agent/benchmark_summary.txt"

def save_results(model_name, results):
    all_results = load_all_results()
    if model_name in all_results:
        print(f"  (overwriting existing results for '{model_name}')")
    all_results[model_name] = results
    with open(BENCHMARK_FILE, "w") as f:
        json.dump(all_results, f, indent=2)
    save_summary(all_results)

def save_summary(all_results):
    lines = []
    lines.append("=" * 90)
    lines.append("EMBEDDING MODEL BENCHMARK COMPARISON")
    lines.append("=" * 90)
    lines.append("")
    lines.append(f"{'Model':<25} {'Top-1':<10} {'Top-3':<10} {'Avg Score':<12} {'Embed(ms)':<12} {'Search(ms)':<12} {'LLM(ms)'}")
    lines.append("-" * 90)
    for model, r in all_results.items():
        lines.append(f"{model:<25} {r['top1_accuracy']:<10} {r['top3_accuracy']:<10} {r['avg_top1_score']:<12} {r['avg_embedding_latency_ms']:<12} {r['avg_search_latency_ms']:<12} {r['avg_llm_latency_ms']}")
    lines.append("=" * 90)

    # Per-model detailed results
    for model, r in all_results.items():
        lines.append("")
        lines.append(f"\n{'─' * 90}")
        lines.append(f"MODEL: {model}")
        lines.append(f"{'─' * 90}")
        lines.append(f"  Top-1 Accuracy: {r['top1_accuracy']}")
        lines.append(f"  Top-3 Accuracy: {r['top3_accuracy']}")
        lines.append(f"  Avg Top-1 Score: {r['avg_top1_score']}")
        lines.append(f"  Avg Embedding Latency: {r['avg_embedding_latency_ms']} ms")
        lines.append(f"  Avg Search Latency: {r['avg_search_latency_ms']} ms")
        lines.append(f"  Avg LLM Latency: {r['avg_llm_latency_ms']} ms")
        lines.append("")
        lines.append(f"  {'Query':<45} {'Status':<8} {'Score':<10} {'Top Match'}")
        lines.append(f"  {'-'*85}")
        for q in r["queries"]:
            status = "HIT" if q["in_top1"] else ("TOP3" if q["in_top3"] else "MISS")
            top_match = q["top_matches"][0]["question"] if q["top_matches"] else "N/A"
            lines.append(f"  {q['query']:<45} {status:<8} {q['top1_score']:<10} {top_match}")

    with open(SUMMARY_FILE, "w") as f:
        f.write("\n".join(lines))

def print_comparison():
    all_results = load_all_results()
    if not all_results:
        print("No benchmark results found.")
        return

    print("\n" + "=" * 80)
    print(f"{'Model':<25} {'Top-1':<10} {'Top-3':<10} {'Avg Score':<12} {'Embed(ms)':<12} {'Search(ms)':<12} {'LLM(ms)'}")
    print("-" * 80)
    for model, r in all_results.items():
        print(f"{model:<25} {r['top1_accuracy']:<10} {r['top3_accuracy']:<10} {r['avg_top1_score']:<12} {r['avg_embedding_latency_ms']:<12} {r['avg_search_latency_ms']:<12} {r['avg_llm_latency_ms']}")
    print("=" * 80)


if __name__ == "__main__":
    import sys

    # Usage: python benchmark.py <model_name>
    # Or:    python benchmark.py --compare  (to just print comparison)
    if len(sys.argv) > 1 and sys.argv[1] == "--compare":
        print_comparison()
        sys.exit(0)

    model = sys.argv[1] if len(sys.argv) > 1 else "nomic-embed-text"
    print(f"\nBenchmarking: {model}")
    print("=" * 60)

    results = run_benchmark(model)

    print("\n" + "=" * 60)
    print(f"RESULTS: {model}")
    print(f"  Top-1 Accuracy: {results['top1_accuracy']}")
    print(f"  Top-3 Accuracy: {results['top3_accuracy']}")
    print(f"  Avg Top-1 Score: {results['avg_top1_score']}")
    print(f"  Avg Embedding Latency: {results['avg_embedding_latency_ms']} ms")
    print(f"  Avg Search Latency: {results['avg_search_latency_ms']} ms")
    print(f"  Avg LLM Latency: {results['avg_llm_latency_ms']} ms")

    # Save to single benchmark file
    save_results(model, results)
    print(f"\nResults saved to benchmark_results.json")

    # Print comparison table if multiple models exist
    print_comparison()
