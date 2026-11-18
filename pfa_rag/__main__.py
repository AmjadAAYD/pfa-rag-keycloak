"""Local commands for indexing the corpus and comparing both retrieval strategies."""

import argparse
import json
from pathlib import Path

from .corpus import KNOWN_ROLES, parse_corpus
from .embeddings import OllamaEmbeddings
from .index import build_index, embed_query, index_fingerprint, index_path, open_index
from .retrieval import search


def positive_integer(value: str) -> int:
    integer = int(value)
    if integer < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return integer


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pfa_rag", description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus.jsonl"))
    parser.add_argument("--index-dir", type=Path, default=Path(".pfa-index"))
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="bge-m3")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("index", help="Embed the corpus and create a reusable local index")
    query = commands.add_parser("search", help="Compare pre-filtering and post-filtering")
    query.add_argument("--role", choices=sorted(KNOWN_ROLES), action="append", required=True)
    query.add_argument("--top-k", type=positive_integer, default=5)
    query.add_argument("--candidate-limit", type=positive_integer, default=20)
    query.add_argument("question")
    args = parser.parse_args(argv)
    if args.command == "search" and not args.question.strip():
        parser.error("question must not be empty")

    try:
        data = args.corpus.read_bytes()
        documents = parse_corpus(data, args.corpus)
        embedder = OllamaEmbeddings(args.ollama_url, args.model)
        fingerprint = index_fingerprint(data, embedder)
        location = index_path(args.index_dir, fingerprint)
        if args.command == "index":
            manifest = build_index(location, fingerprint, documents, embedder)
            output = {
                **fingerprint, "document_count": manifest["document_count"],
                "dimensions": manifest["dimensions"], "index_path": str(location),
            }
        else:
            with open_index(location, fingerprint, len(documents)) as (client, manifest):
                vector = embed_query(embedder, args.question.strip(), manifest)
                roles = set(args.role)
                output = {
                    "question": args.question.strip(), "roles": sorted(roles),
                    "top_k": args.top_k, "candidate_limit": args.candidate_limit,
                }
                for strategy in ("pre_filter", "post_filter"):
                    result = search(
                        client, documents, vector, roles, strategy=strategy,
                        top_k=args.top_k, candidate_limit=args.candidate_limit,
                    )
                    output[strategy] = {
                        "candidate_count": result.candidate_count,
                        "rejected_count": result.rejected_count,
                        "hits": [
                            {"id": hit.document.id, "title": hit.document.title, "score": hit.score}
                            for hit in result.hits
                        ],
                    }
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"pfa_rag: {error}\n")

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
