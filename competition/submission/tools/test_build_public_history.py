import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_public_history import build, excluded, redact


class PublicHistoryTests(unittest.TestCase):
    def test_private_files(self):
        for name in ["model-budget.sqlite3", "budget.sqlite3-journal", ".env", ".env.local", "signatures/person.png", "sujie-originality-statement.pdf", "作品原创性声明.docx", "key.pem"]:
            self.assertTrue(excluded(name), name)
        self.assertFalse(excluded("source-verification.json"))

    def test_synthetic_paths_and_non_user_home(self):
        text = "/home/analyst/test /workspace/case/home/.ssh/key /home/runner/work"
        self.assertEqual(redact(text, []), (text, 0))

    def test_redaction_preserves_json(self):
        text = json.dumps({"path": "C:\\Users\\private-user\\doc.txt", "unix": "/Users/private-user/test", "person": "Private Person"})
        public, count = redact(text, ["Private Person"])
        self.assertEqual(count, 3)
        self.assertNotIn("private-user", public)
        self.assertNotIn("Private Person", public)
        self.assertIn("PUBLIC_USER", json.loads(public)["path"])

    def test_archive_integrity_original_bytes_and_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "input"
            root.mkdir()
            original = b'{"status": "FAILED", "experimental_hash": "unchanged"}\r\n'
            (root / "run.json").write_bytes(original)
            (root / "model-budget.sqlite3").write_bytes(b"private")
            a, b = Path(tmp) / "a.zip", Path(tmp) / "b.zip"
            manifest = build(root, a)
            build(root, b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with zipfile.ZipFile(a) as archive:
                self.assertEqual(archive.read("run.json"), original)
                self.assertNotIn("model-budget.sqlite3", archive.namelist())
            row = manifest["files"][0]
            self.assertEqual(row["original_sha256"], row["published_sha256"])
            self.assertEqual(manifest["excluded_counts"], {"private-state-or-identity": 1})
            with self.assertRaises(FileExistsError):
                build(root, a)

    def test_original_experiment_hash_not_forged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "input"
            root.mkdir()
            (root / "run.json").write_text('{"path":"/Users/private-user/file", "sha256":"original-experiment-hash"}', encoding="utf-8")
            output = Path(tmp) / "out.zip"
            row = build(root, output)["files"][0]
            self.assertNotEqual(row["original_sha256"], row["published_sha256"])
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(json.loads(archive.read("run.json"))["sha256"], "original-experiment-hash")

    def test_unreviewed_binary_and_output_inside_input_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "input"
            root.mkdir()
            with self.assertRaises(ValueError):
                build(root, root / "out.zip")
            (root / "unknown.zip").write_bytes(b"unreviewed")
            with self.assertRaises(ValueError):
                build(root, Path(tmp) / "out.zip")

    def test_secret_candidate_rejected_without_echo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "input"
            root.mkdir()
            value = "sk-" + "A" * 30
            (root / "run.json").write_text(json.dumps({"key": value}), encoding="utf-8")
            with self.assertRaises(ValueError) as error:
                build(root, Path(tmp) / "out.zip")
            self.assertNotIn(value, str(error.exception))


if __name__ == "__main__":
    unittest.main()
