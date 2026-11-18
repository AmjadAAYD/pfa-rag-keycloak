import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from pfa_rag.__main__ import main


CORPUS_PATH = Path(__file__).resolve().parents[1] / "data" / "corpus.jsonl"
QUESTION = "Quelle est la priorité de mon département pour le projet Atlas ?"
FINANCE = "finance-01-interne"
IT = "informatique-01-interne"
RESERVE = "finance-01-confidentiel"


class OllamaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/api/tags":
            self.send_error(404)
            return
        self.respond({"models": [{"name": "bge-m3:latest", "digest": self.server.digest}]})

    def do_POST(self):
        if self.path != "/api/embed":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        vectors = []
        for text in body["input"]:
            if text.startswith(("Atlas — Réserve budgétaire", QUESTION)):
                vectors.append([1.0, 0.0])
            elif text.startswith("Atlas — Plan budgétaire"):
                vectors.append([0.9, 0.1])
            else:
                vectors.append([0.8, 0.2])
        if self.server.invalid_response:
            vectors[-1] = [0.0, 0.0]
        self.respond({"embeddings": vectors})

    def respond(self, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


class RetrievalCommandTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.corpus = self.root / "corpus.jsonl"
        lines = [
            line for line in CORPUS_PATH.read_bytes().splitlines()
            if json.loads(line)["id"] in {FINANCE, IT, RESERVE}
        ]
        self.corpus.write_bytes(b"\n".join(lines) + b"\n")
        self.index_dir = self.root / "index"

        self.ollama = HTTPServer(("127.0.0.1", 0), OllamaHandler)
        self.ollama.digest = "a" * 64
        self.ollama.invalid_response = False
        self.ollama.requests = []
        thread = Thread(target=self.ollama.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        self.addCleanup(self.ollama.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.ollama.shutdown)

    def run_command(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            main([
                "--corpus", str(self.corpus), "--index-dir", str(self.index_dir),
                "--ollama-url", f"http://127.0.0.1:{self.ollama.server_port}", *args,
            ])
        return json.loads(output.getvalue())

    def assert_command_error(self, expected, *args):
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            self.run_command(*args)
        self.assertNotEqual(error.exception.code, 0)
        self.assertIn(expected, stderr.getvalue())

    def test_index_persists_and_search_compares_both_strategies(self):
        indexed = self.run_command("index")
        self.assertEqual(indexed["document_count"], 3)
        self.assertEqual(indexed["dimensions"], 2)
        self.assertEqual(indexed["model_digest"], "a" * 64)
        self.assertEqual(self.ollama.requests[0]["model"], "bge-m3:latest")
        self.assertTrue(self.ollama.requests[0]["input"][0].startswith("Atlas — Plan budgétaire\n"))

        self.run_command("index")
        self.assertEqual(len(self.ollama.requests), 1)
        result = self.run_command("search", "--role", "finance", "--candidate-limit", "2", QUESTION)
        for strategy in ("pre_filter", "post_filter"):
            self.assertEqual([hit["id"] for hit in result[strategy]["hits"]], [FINANCE])
        self.assertEqual(result["pre_filter"]["candidate_count"], 1)
        self.assertEqual(result["post_filter"]["candidate_count"], 2)
        self.assertEqual(result["post_filter"]["rejected_count"], 1)
        self.assertEqual(self.ollama.requests[-1]["input"], [QUESTION])
        self.assertNotIn(RESERVE, json.dumps(result))

    def test_search_requires_a_matching_corpus_and_model_digest(self):
        self.run_command("index")
        original = self.corpus.read_bytes()
        self.corpus.write_bytes(original.replace(b'"Atlas"', b'"Atlas" ', 1))
        self.assert_command_error("No matching index", "search", "--role", "finance", QUESTION)
        self.corpus.write_bytes(original)
        self.ollama.digest = "b" * 64
        self.assert_command_error("No matching index", "search", "--role", "finance", QUESTION)
        self.assertEqual(len(self.ollama.requests), 1)

    def test_invalid_vectors_are_rejected_before_an_index_is_published(self):
        self.ollama.invalid_response = True
        self.assert_command_error("nonzero", "index")
        self.assertEqual(list(self.index_dir.glob("*/manifest.json")), [])
        self.ollama.invalid_response = False
        self.assertEqual(self.run_command("index")["document_count"], 3)
