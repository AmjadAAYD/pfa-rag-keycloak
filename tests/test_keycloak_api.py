import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from http.server import HTTPServer
from pathlib import Path
from threading import Thread
from time import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from pfa_rag.api import Settings, create_app
from pfa_rag.corpus import parse_corpus
from pfa_rag.embeddings import OllamaEmbeddings
from pfa_rag.index import build_index, index_fingerprint, index_path
from test_retrieval_cli import CORPUS_PATH, FINANCE, IT, QUESTION, RESERVE, OllamaHandler


class KeycloakFixtureHandler(OllamaHandler):
    def do_GET(self):
        issuer = self.server.issuer
        realm = "/realms/pfa-rag"
        if self.path == realm + "/.well-known/openid-configuration":
            self.respond({"issuer": issuer, "jwks_uri": issuer + "/protocol/openid-connect/certs"})
        elif self.path == realm + "/protocol/openid-connect/certs":
            self.respond({"keys": [self.server.jwk]})
        elif self.path == "/api/tags":
            self.respond({"models": [
                {"name": "bge-m3:latest", "digest": self.server.digest},
                {"name": "qwen3.5:9b", "digest": "b" * 64},
            ]})
        else:
            super().do_GET()

    def do_POST(self):
        if self.path != "/api/chat":
            super().do_POST()
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        query = json.loads(request["messages"][-1]["content"])
        with closing(sqlite3.connect(self.server.audit_path)) as db:
            last_event = db.execute(
                "SELECT result, context_ids FROM access_events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        self.server.answer_calls.append((query, last_event))
        marker = "La réserve proposée" if "réserve" in query["question"] else "La priorité"
        selected = next((block["number"] for block in query["passages"]
                         if block["text"].startswith(marker)), None)
        passages = [9999] if self.server.bad_answer else ([selected] if selected else [])
        self.respond({"done": True, "message": {"content": json.dumps({"passages": passages})}})


class KeycloakApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        base = Path(temp.name)
        corpus = base / "corpus.jsonl"
        data = b"\n".join(
            line for line in CORPUS_PATH.read_bytes().splitlines()
            if json.loads(line)["id"] in {FINANCE, IT, RESERVE}
        ) + b"\n"
        corpus.write_bytes(data)

        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        server = HTTPServer(("127.0.0.1", 0), KeycloakFixtureHandler)
        server.jwk = {
            **jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key(), as_dict=True),
            "kid": "pfa-test", "use": "sig", "alg": "RS256",
        }
        url = f"http://127.0.0.1:{server.server_port}"
        cls.issuer = server.issuer = url + "/realms/pfa-rag"
        server.digest = "a" * 64
        server.invalid_response = False
        server.requests = []
        cls.server = server
        server.bad_answer = False
        server.answer_calls = []
        server.audit_path = base / "access.sqlite3"
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        cls.addClassCleanup(server.server_close)
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)

        index_root = base / "index"
        embedder = OllamaEmbeddings(url, "bge-m3")
        fingerprint = index_fingerprint(data, embedder)
        build_index(index_path(index_root, fingerprint), fingerprint, parse_corpus(data, corpus), embedder)
        cls.settings = Settings(
            issuer=cls.issuer, ollama_url=url, corpus=corpus, index_dir=index_root,
            audit_db=server.audit_path,
        )

    def setUp(self):
        self.client = self.enterContext(TestClient(create_app(self.settings)))

    def bearer(self, roles=("finance",), *, signer=None, **overrides):
        timestamp = int(time())
        claims = {
            "iss": self.issuer, "aud": ["account", "pfa-api"], "sub": "demo-sub",
            "preferred_username": "demo-user", "typ": "Bearer", "iat": timestamp,
            "exp": timestamp + 120, "resource_access": {"pfa-api": {"roles": list(roles)}},
        }
        claims.update(overrides)
        token = jwt.encode(claims, signer or self.key, algorithm="RS256", headers={"kid": "pfa-test"})
        return {"Authorization": f"Bearer {token}"}

    def test_verified_token_roles_drive_both_index_strategies(self):
        for strategy in ("pre_filter", "post_filter"):
            for role, expected in (("finance", FINANCE), ("informatique", IT), ("direction", RESERVE)):
                with self.subTest(strategy=strategy, role=role):
                    headers = self.bearer((role,))
                    response = self.client.post("/api/v1/retrievals", headers=headers,
                                                json={"question": QUESTION, "strategy": strategy})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["sources"][0]["document_id"], expected)
                    if role != "direction":
                        self.assertEqual(len(response.json()["sources"]), 1)

    def test_invalid_tokens_stop_before_embedding(self):
        requests_before = len(self.server.requests)
        for headers in (
            {},
            {"Authorization": "Bearer not-a-jwt"},
            self.bearer(aud="pfa-web"),
            self.bearer(iss="https://other.invalid/realms/pfa-rag"),
            self.bearer(exp=int(time()) - 60),
            self.bearer(typ="ID"),
        ):
            with self.subTest(token_present=bool(headers)):
                response = self.client.post("/api/v1/retrievals", headers=headers,
                                            json={"question": QUESTION})
                self.assertEqual(response.status_code, 401, response.text)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(len(self.server.requests), requests_before)

    def test_token_signed_with_a_different_key_cannot_claim_direction(self):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        response = self.client.get(
            f"/api/v1/documents/{RESERVE}", headers=self.bearer(("direction",), signer=other_key),
        )
        self.assertEqual(response.status_code, 401)

    def test_app_roles_come_from_the_expected_client_claim(self):
        wrong_client = self.bearer(resource_access={"pfa-web": {"roles": ["direction"]}})
        denied = self.client.get("/api/v1/me", headers=wrong_client)
        self.assertEqual(denied.status_code, 403)
        accepted = self.client.get("/api/v1/me", headers=self.bearer(("finance", "informatique", "unknown")))
        self.assertEqual(accepted.json()["roles"], ["finance", "informatique"])
        self.assertEqual(accepted.json()["username"], "demo-user")

    def test_request_rejects_body_role_overrides(self):
        response = self.client.post("/api/v1/retrievals", headers=self.bearer(),
                                    json={"question": QUESTION, "role": "direction"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["content-type"], "application/problem+json")

    def test_direct_source_reads_use_the_same_document_acl(self):
        missing = self.client.get("/api/v1/documents/unknown", headers=self.bearer())
        denied = self.client.get(f"/api/v1/documents/{RESERVE}", headers=self.bearer())
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(denied.content, missing.content)
        allowed = self.client.get(f"/api/v1/documents/{RESERVE}", headers=self.bearer(("direction",)))
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("1150 MAD", allowed.json()["text"])

    def test_readiness_and_openapi(self):
        ready = self.client.get("/readyz")
        self.assertEqual(ready.status_code, 200, ready.text)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/api/v1/retrievals", schema["paths"])
        self.assertIn("HTTPBearer", schema["components"]["securitySchemes"])


    def test_answers_send_only_allowed_evidence_and_audit_before_model_call(self):
        response = self.client.post(
            "/api/v1/answers", headers=self.bearer(), json={"question": QUESTION}
        )
        self.assertEqual(response.status_code, 200, response.text)
        answer = response.json()
        self.assertEqual(answer["status"], "answered")
        self.assertIn("10800 MAD", answer["answer"])
        self.assertEqual([item["document_id"] for item in answer["citations"]], [FINANCE])
        query, event = self.server.answer_calls[-1]
        self.assertEqual({block["document"] for block in query["passages"]}, {FINANCE})
        self.assertEqual(event[0], "processing")
        self.assertEqual(json.loads(event[1]), [FINANCE])
        with closing(sqlite3.connect(self.server.audit_path)) as db:
            stored = db.execute(
                "SELECT subject, strategy, result, citation_ids, total_ms FROM access_events WHERE request_id=?",
                (answer["request_id"],),
            ).fetchone()
        self.assertEqual(stored[:4], ("demo-sub", "pre_filter", "answered", json.dumps([FINANCE])))
        self.assertGreaterEqual(stored[4], 0)

    def test_finance_abstains_and_direction_can_cite_the_atlas_reserve(self):
        question = "Quel est le montant de la réserve budgétaire du projet Atlas ?"
        for strategy in ("pre_filter", "post_filter"):
            body = {"question": question, "strategy": strategy}
            denied = self.client.post("/api/v1/answers", headers=self.bearer(), json=body)
            self.assertEqual(denied.status_code, 200)
            self.assertEqual(denied.json()["status"], "insufficient_evidence")
            self.assertEqual(denied.json()["citations"], [])
            allowed = self.client.post(
                "/api/v1/answers", headers=self.bearer(("direction",)), json=body,
            )
            self.assertEqual(allowed.status_code, 200)
            self.assertIn("1150 MAD", allowed.json()["answer"])
            self.assertEqual(allowed.json()["citations"][0]["document_id"], RESERVE)

    def test_model_cannot_cite_a_passage_outside_its_context(self):
        self.server.bad_answer = True
        try:
            response = self.client.post(
                "/api/v1/answers", headers=self.bearer(), json={"question": QUESTION},
            )
        finally:
            self.server.bad_answer = False
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("9999", response.text)
        with closing(sqlite3.connect(self.server.audit_path)) as db:
            result, citations = db.execute(
                "SELECT result, citation_ids FROM access_events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        self.assertEqual((result, citations), ("invalid_generation", "[]"))
