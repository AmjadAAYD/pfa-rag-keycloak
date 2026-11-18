import json
import tempfile
import unittest
from pathlib import Path

from qdrant_client import QdrantClient

from pfa_rag.corpus import load_corpus
from pfa_rag.retrieval import COLLECTION_NAME, index_corpus, retrieve


CORPUS_PATH = Path(__file__).resolve().parents[1] / "data" / "corpus.jsonl"
FINANCE = "finance-01-interne"
IT = "informatique-01-interne"
RESERVE = "finance-01-confidentiel"
COMMON = "rh-01-commun"


class CorpusLoaderTests(unittest.TestCase):
    def test_loads_atlas_permissions_and_all_300_documents(self):
        documents = load_corpus(CORPUS_PATH)
        self.assertEqual(len(documents), 300)
        self.assertEqual(documents[FINANCE].allowed_roles, {"finance", "direction"})
        self.assertEqual(documents[RESERVE].allowed_roles, {"direction"})

    def test_rejects_invalid_or_duplicate_permissions_records(self):
        record = json.loads(CORPUS_PATH.read_text(encoding="utf-8").splitlines()[0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            for case, records in (
                ("unknown role", [{**record, "allowed_roles": ["unrecognized"]}]),
                ("missing roles", [{key: value for key, value in record.items()
                                    if key != "allowed_roles"}]),
                ("duplicate id", [record, record]),
            ):
                with self.subTest(case=case):
                    path.write_text("\n".join(map(json.dumps, records)), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_corpus(path)


class AtlasRetrievalTests(unittest.TestCase):
    def setUp(self):
        corpus = load_corpus(CORPUS_PATH)
        self.documents = {key: corpus[key] for key in (RESERVE, FINANCE, IT, COMMON)}
        self.client = QdrantClient(":memory:")
        self.addCleanup(self.client.close)
        # The reserved document is closest to the query, then Finance, IT and Common.
        index_corpus(self.client, self.documents, [[1, 0], [0.9, 0.1], [0.8, 0.2], [0, 1]])

    def search(self, roles, strategy, **options):
        return [
            hit.document.id for hit in retrieve(
                self.client, self.documents, [1.0, 0.0], roles, strategy=strategy, **options
            )
        ]

    def test_both_strategies_return_the_documents_each_role_can_read(self):
        for strategy in ("pre_filter", "post_filter"):
            for role, expected in (
                ("finance", [FINANCE, COMMON]),
                ("informatique", [IT, COMMON]),
                ("direction", [RESERVE, FINANCE, IT, COMMON]),
            ):
                with self.subTest(strategy=strategy, role=role):
                    self.assertEqual(self.search({role}, strategy), expected)

    def test_post_filter_can_lose_recall_at_a_fixed_candidate_limit(self):
        self.assertEqual(self.search({"finance"}, "pre_filter", top_k=1, candidate_limit=1), [FINANCE])
        self.assertEqual(self.search({"finance"}, "post_filter", top_k=1, candidate_limit=1), [])
        self.assertEqual(self.search({"finance"}, "post_filter", top_k=1, candidate_limit=2), [FINANCE])

    def test_roles_combine_by_union_and_unknown_roles_do_not_grant_access(self):
        for strategy in ("pre_filter", "post_filter"):
            with self.subTest(strategy=strategy):
                self.assertEqual(
                    self.search({"finance", "informatique"}, strategy), [FINANCE, IT, COMMON]
                )
                self.assertEqual(self.search({"unrecognized"}, strategy), [])

    def test_source_permissions_override_stale_qdrant_payload(self):
        self.client.set_payload(
            collection_name=COLLECTION_NAME,
            payload={"allowed_roles": ["finance"]},
            points=[point.id for point in self.client.scroll(COLLECTION_NAME, limit=4)[0]
                    if point.payload["document_id"] == RESERVE],
        )
        self.assertEqual(self.search({"finance"}, "pre_filter", top_k=1), [])
        self.assertEqual(self.search({"finance"}, "post_filter"), [FINANCE, COMMON])


if __name__ == "__main__":
    unittest.main()
