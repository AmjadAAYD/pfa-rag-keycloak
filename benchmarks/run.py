"""Run exact retrieval and answer selection on the labeled synthetic questions."""

import argparse
import json
import math
import platform
import random
import subprocess
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from urllib.request import urlopen

from qdrant_client import QdrantClient, models

from pfa_rag.corpus import KNOWN_ROLES, parse_corpus
from pfa_rag.embeddings import OllamaEmbeddings
from pfa_rag.generation import GENERATION_OPTIONS, InvalidGeneration, OllamaAnswers, answer_text
from pfa_rag.index import index_fingerprint, index_path
from pfa_rag.retrieval import index_corpus, search


SEED = 17
BUDGETS = (5, 10, 20, 50, 300)
METHODS = ("pre_filter", "post_filter", "unfiltered")


def json_lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def append_record(handle, data):
    handle.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
    handle.flush()


def service_version(url):
    with urlopen(url, timeout=5) as response:
        return json.load(response)["version"]


def load_cases(path, documents):
    cases = json_lines(path)
    ids = set()
    for case in cases:
        target = case["target_id"]
        role = case["role"]
        if case["case_id"] in ids or role not in KNOWN_ROLES:
            raise ValueError(f"Invalid case ID or role: {case['case_id']}")
        ids.add(case["case_id"])
        if target and case["target_text"] not in documents[target].text:
            raise ValueError(f"Gold passage is absent: {case['case_id']}")
        answerable = bool(target and documents[target].can_read({role}))
        if answerable != (case["expected"] == "answered"):
            raise ValueError(f"Gold passage and ACL disagree: {case['case_id']}")
    if not cases:
        raise ValueError("The question set is empty")
    return cases


def prepare_collection(client, collection, documents, embedder, expected_digest):
    if not client.collection_exists(collection):
        vectors = embedder.embed([f"{doc.title}\n{doc.text}" for doc in documents.values()])
        if embedder.model_digest() != expected_digest:
            raise ValueError("Embedding model changed during indexing")
        index_corpus(client, documents, vectors, collection=collection)
    client.create_payload_index(
        collection_name=collection, field_name="allowed_roles",
        field_schema=models.PayloadSchemaType.KEYWORD, wait=True,
    )
    if client.count(collection, exact=True).count != len(documents):
        raise ValueError(f"The Qdrant collection {collection} has an unexpected point count")


def authorized_search(client, collection, documents, case, vector, strategy, budget=20):
    start = perf_counter()
    result = search(client, documents, vector, {case["role"]}, strategy=strategy,
                    candidate_limit=budget, collection=collection)
    return {
        "ids": [hit.document.id for hit in result.hits],
        "scores": [hit.score for hit in result.hits],
        "retrieval_ms": round(1000 * (perf_counter() - start), 3),
        "candidate_count": result.candidate_count,
        "rejected_count": result.rejected_count,
    }


def unfiltered_search(client, collection, vector):
    start = perf_counter()
    points = client.query_points(
        collection_name=collection, query=vector,
        search_params=models.SearchParams(exact=True), limit=5, with_payload=["document_id"],
    ).points
    return {
        "ids": [point.payload["document_id"] for point in points],
        "scores": [point.score for point in points],
        "retrieval_ms": round(1000 * (perf_counter() - start), 3),
        "candidate_count": len(points), "rejected_count": 0,
    }


def retrieval_phase(output, cases, client, collection, documents, embedder):
    previous = {row["case_id"]: row for row in json_lines(output)}
    if len(previous) == len(cases):
        return previous
    embedder.embed([cases[0]["question"]])
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            case_id = case["case_id"]
            if case_id in previous:
                continue
            start = perf_counter()
            vector, = embedder.embed([case["question"]])
            embedding_ms = round(1000 * (perf_counter() - start), 3)
            pre = authorized_search(client, collection, documents, case, vector, "pre_filter")
            sweep = {
                str(budget): authorized_search(
                    client, collection, documents, case, vector, "post_filter", budget,
                )
                for budget in BUDGETS
            }
            full = sweep[str(BUDGETS[-1])]
            if len(pre["scores"]) != len(full["scores"]) or any(
                not math.isclose(a, b, abs_tol=1e-5)
                for a, b in zip(pre["scores"], full["scores"], strict=True)
            ):
                raise ValueError(f"Full-candidate exact search differs for {case_id}")
            row = {
                "case_id": case_id, "embedding_ms": embedding_ms,
                "pre_filter": pre,
                "unfiltered": unfiltered_search(client, collection, vector),
                "post_filter": sweep["20"],
                "sweep": sweep,
            }
            append_record(handle, row)
            previous[case_id] = row
            if len(previous) % 100 == 0 or len(previous) == len(cases):
                print(f"Retrieval {len(previous)}/{len(cases)}", flush=True)
    return previous


def measure_answer(case, method, retrieval, documents, generator):
    selected_context = retrieval[method]
    context = [documents[doc_id] for doc_id in selected_context["ids"]]
    roles = frozenset({case["role"]})
    start = perf_counter()
    error = None
    try:
        selected = generator.select(case["question"], roles, context)
    except InvalidGeneration:
        selected, error = [], "invalid_generation"
    except (OSError, RuntimeError, ValueError):
        selected, error = [], "generation_unavailable"
    generation_ms = round(1000 * (perf_counter() - start), 3)
    passages = [{"document_id": value.document.id, "text": value.text} for value in selected]
    status = error or ("answered" if passages else "insufficient_evidence")
    target_match = any(
        item["document_id"] == case["target_id"] and item["text"] == case["target_text"]
        for item in passages
    )
    answerable = case["expected"] == "answered"
    return {
        "case_id": case["case_id"], "role": case["role"], "category": case["category"],
        "method": method, "status": status, "context_ids": selected_context["ids"],
        "answer": None if error else answer_text(selected), "passages": passages,
        "recall_at_5": int(case["target_id"] in selected_context["ids"]) if answerable else None,
        "target_match": target_match,
        "correct": target_match if answerable else status == "insufficient_evidence",
        "context_leak": any(not doc.can_read(roles) for doc in context),
        "citation_leak": any(not item.document.can_read(roles) for item in selected),
        "restricted_fact": bool(not answerable and case["target_id"] and target_match),
        "supported_passages": sum(item.text in item.document.text for item in selected),
        "embedding_ms": retrieval["embedding_ms"], "retrieval_ms": selected_context["retrieval_ms"],
        "generation_ms": generation_ms,
        "pipeline_ms": round(retrieval["embedding_ms"] + selected_context["retrieval_ms"] + generation_ms, 3),
    }


def generation_phase(output, cases, prepared, documents, generator):
    previous = {(row["case_id"], row["method"]) for row in json_lines(output)}
    final_count = len(cases) * len(METHODS)
    if len(previous) == final_count:
        return
    randomizer = random.Random(SEED)
    order = list(cases)
    randomizer.shuffle(order)
    warmup = next(case for case in order if prepared[case["case_id"]]["pre_filter"]["ids"])
    generator.select(
        warmup["question"], frozenset({warmup["role"]}),
        [documents[doc_id] for doc_id in prepared[warmup["case_id"]]["pre_filter"]["ids"]],
    )
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        for case in order:
            methods = randomizer.sample(METHODS, len(METHODS))
            for method in methods:
                key = (case["case_id"], method)
                if key in previous:
                    continue
                row = measure_answer(case, method, prepared[case["case_id"]], documents, generator)
                if method != "unfiltered" and (row["context_leak"] or row["citation_leak"]):
                    raise AssertionError(f"Forbidden document in protected arm: {key}")
                append_record(handle, row)
                previous.add(key)
                if len(previous) % 30 == 0 or len(previous) == final_count:
                    print(f"Answers {len(previous)}/{final_count}", flush=True)


def source_digest():
    files = [Path(__file__), *sorted(Path("pfa_rag").glob("*.py"))]
    digest = sha256()
    for path in files:
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def write_manifest(path, environment):
    if path.exists():
        original = json.loads(path.read_text(encoding="utf-8"))
        if original["configuration"] != environment:
            raise ValueError("Run configuration changed. Choose a new output directory.")
        return
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    manifest = {
        "started_at_utc": datetime.now(UTC).isoformat(), "revision": revision,
        "configuration": environment,
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("benchmarks/questions.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus.jsonl"))
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    args = parser.parse_args()
    data = args.corpus.read_bytes()
    documents = parse_corpus(data, args.corpus)
    cases = load_cases(args.cases, documents)
    print("Cases", dict(Counter(case["role"] for case in cases)), flush=True)
    embedder = OllamaEmbeddings(args.ollama_url, "bge-m3")
    generator = OllamaAnswers(args.ollama_url, "qwen3.5:9b")
    fingerprint = index_fingerprint(data, embedder)
    collection = "pfa_benchmark_" + index_path(Path("."), fingerprint).name[:24]
    generation_digest = generator.model_digest()
    args.output.mkdir(parents=True, exist_ok=True)
    environment = {
        "cases_sha256": sha256(args.cases.read_bytes()).hexdigest(),
        "cases": len(cases), "source_digest": source_digest(), **fingerprint,
        "generation_model": generator.model, "generation_digest": generation_digest,
        "generation_options": GENERATION_OPTIONS, "thinking": False,
        "qdrant_version": service_version(args.qdrant_url + "/"), "qdrant_mode": "docker_exact_cosine",
        "ollama_version": service_version(args.ollama_url + "/api/version"),
        "compute": platform.machine(), "os": platform.system(), "python": platform.python_version(),
        "random_seed": SEED, "candidate_budgets": list(BUDGETS), "methods": list(METHODS),
    }
    try:
        environment["gpu"] = subprocess.check_output([
            "nvidia-smi", "--query-gpu=name", "--format=csv,noheader"
        ], text=True, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        environment["gpu"] = None
    write_manifest(args.output / "manifest.json", environment)
    with closing(QdrantClient(url=args.qdrant_url, timeout=15)) as client:
        prepare_collection(client, collection, documents, embedder, fingerprint["model_digest"])
        prepared = retrieval_phase(args.output / "retrieval.jsonl", cases, client, collection, documents, embedder)
    if embedder.model_digest() != fingerprint["model_digest"]:
        raise ValueError("Embedding model changed during the run")
    generation_phase(args.output / "answers.jsonl", cases, prepared, documents, generator)
    if generator.model_digest() != generation_digest:
        raise ValueError("Answer model changed during the run")


if __name__ == "__main__":
    main()
