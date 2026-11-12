import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CorpusTests(unittest.TestCase):
    def test_corpus_covers_all_departments_and_levels_with_correct_rights(self):
        generator = ROOT / "generate_corpus.py"
        self.assertTrue(generator.is_file(), "Le générateur doit être disponible")
        output = subprocess.check_output([sys.executable, str(generator)])
        documents = [json.loads(line) for line in output.splitlines()]
        roles = {"rh", "finance", "informatique", "operations", "direction"}
        counts = Counter()
        for doc in documents:
            department = doc["department"]
            level = doc["confidentiality"]
            expected = {
                "commun": roles,
                "interne": {department, "direction"},
                "confidentiel": {"direction"},
            }
            self.assertEqual(set(doc["allowed_roles"]), expected[level], doc["id"])
            counts[department, level] += 1
        self.assertEqual(set(counts), {
            (department, level)
            for department in ("rh", "finance", "informatique", "operations")
            for level in ("commun", "interne", "confidentiel")
        })
        self.assertTrue(all(count == 25 for count in counts.values()))
        self.assertEqual(len({doc["id"] for doc in documents}), len(documents))
        self.assertEqual(len({doc["text"] for doc in documents}), len(documents))
        self.assertEqual(output, (ROOT / "data" / "corpus.jsonl").read_bytes())
