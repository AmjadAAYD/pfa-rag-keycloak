"""Verify benchmark inputs, manifest digests, and recorded evaluation outputs."""

import csv
import io
import json
import sys
import unittest
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.build_cases import ROLES, calibration, evaluation  # noqa: E402
from benchmarks.run import json_lines  # noqa: E402
from benchmarks.summarize import summarize_answers, summarize_sweep  # noqa: E402
from pfa_rag.corpus import load_corpus  # noqa: E402


def _csv_text(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


class BenchmarkArtifactTests(unittest.TestCase):
    """Ensure published benchmark manifests, cases, and tables match repository sources."""

    def test_manifest_digests_match_repository_files(self):
        manifest = json.loads((ROOT / "benchmarks" / "results" / "manifest.json").read_text(encoding="utf-8"))
        configuration = manifest["configuration"]

        source_files = [ROOT / "benchmarks" / "run.py", *sorted((ROOT / "pfa_rag").glob("*.py"))]
        digest = sha256()
        for path in source_files:
            digest.update(path.name.encode("utf-8") + b"\0")
            digest.update(path.read_bytes().replace(b"\r\n", b"\n"))

        self.assertEqual(digest.hexdigest(), configuration["source_digest"])
        self.assertEqual(
            sha256((ROOT / "data" / "corpus.jsonl").read_bytes()).hexdigest(),
            configuration["corpus_sha256"],
        )
        self.assertEqual(
            sha256((ROOT / "benchmarks" / "questions.jsonl").read_bytes()).hexdigest(),
            configuration["cases_sha256"],
        )

    def test_question_sets_are_reproducible(self):
        corpus = load_corpus(ROOT / "data" / "corpus.jsonl")
        for filename, builder, expected_count in (
            ("calibration.jsonl", calibration, 4),
            ("questions.jsonl", evaluation, 100),
        ):
            rows = []
            for role in ROLES:
                generated = builder(corpus, role)
                self.assertEqual(len(generated), expected_count)
                self.assertEqual(len({row["question"] for row in generated}), expected_count)
                rows.extend(
                    {"case_id": f"{role}-{index:03}", **row}
                    for index, row in enumerate(generated, start=1)
                )
            expected_bytes = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
            with self.subTest(file=filename):
                self.assertEqual(expected_bytes, (ROOT / "benchmarks" / filename).read_bytes())

    def test_recorded_csv_tables_match_jsonl_and_have_zero_protected_leaks(self):
        cases = {row["case_id"]: row for row in json_lines(ROOT / "benchmarks" / "questions.jsonl")}
        answers = json_lines(ROOT / "benchmarks" / "results" / "answers.jsonl")
        retrievals = json_lines(ROOT / "benchmarks" / "results" / "retrieval.jsonl")

        self.assertEqual(
            _csv_text(summarize_answers(answers, cases)),
            (ROOT / "benchmarks" / "results" / "summary.csv").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            _csv_text(summarize_sweep(retrievals, cases)),
            (ROOT / "benchmarks" / "results" / "candidate_sweep.csv").read_text(encoding="utf-8"),
        )
        for row in answers:
            if row["method"] in {"pre_filter", "post_filter"}:
                self.assertIs(row["context_leak"], False, row["case_id"])
                self.assertIs(row["citation_leak"], False, row["case_id"])
                self.assertIs(row["restricted_fact"], False, row["case_id"])


if __name__ == "__main__":
    unittest.main()
