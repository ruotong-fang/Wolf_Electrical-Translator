import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from ee_translator.documents import extract_document, text_candidates
from ee_translator.engine import TranslationPipeline
from ee_translator.polishing import LocalLlamaPolisher
from ee_translator.terminology import (
    Term,
    TerminologyStore,
    TranslationMemory,
    normalize_memory_text,
    parameter_signature,
    segment_text,
)


class EchoBackend:
    def translate(self, text, source, target):
        return text

    def available_pairs(self):
        return (("en", "zh"), ("zh", "en"))


class MarkerArtifactBackend(EchoBackend):
    def translate(self, text, source, target):
        return text.replace("REF991A", "REF991A型机车")


class JoinedEnglishMarkerBackend(EchoBackend):
    def translate(self, text, source, target):
        return "REF991Cfor REF991Bis REF991A."


class UnsafePolisher:
    def polish(self, original, draft, source, target, terms):
        return "润色结果删除了所有工程参数"


class CoreTests(unittest.TestCase):
    def test_old_database_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    "CREATE TABLE terms (id INTEGER PRIMARY KEY, english TEXT UNIQUE, chinese TEXT, note TEXT DEFAULT '')"
                )
                db.execute("INSERT INTO terms (english, chinese) VALUES ('busbar', '母排')")
            store = TerminologyStore(path)
            term = next(item for item in store.list_terms() if item.english == "busbar")
            self.assertEqual(term.category, "专业术语")
            self.assertEqual(term.priority, 100)
            self.assertEqual(term.domain, "通用")

    def test_public_electrical_terms_are_seeded(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TerminologyStore(Path(directory) / "terms.db")
            terms = store.list_terms()
            self.assertGreaterEqual(len(terms), 1200)
            self.assertTrue(any(term.english == "vacuum circuit breaker" for term in terms))
            public_terms = [term for term in terms if "ECDICT" in term.source]
            self.assertGreaterEqual(len(public_terms), 1000)
            self.assertTrue(all(term.priority < 100 and term.status == "待审核" for term in public_terms))

    def test_translation_memory_exact_match(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TerminologyStore(Path(directory) / "memory.db")
            store.save_memory(TranslationMemory(None, "rated voltage", "额定电压", "en", "zh"))
            memory = store.exact_memory("rated voltage", "en", "zh")
            self.assertIsNotNone(memory)
            self.assertEqual(memory.target_text, "额定电压")

    def test_translation_memory_is_saved_by_sentence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TerminologyStore(Path(directory) / "memory.db")
            count = store.save_aligned_memory(
                "Rated voltage is 10 kV. Rated current is 630 A.",
                "额定电压为10 kV。额定电流为630 A。",
                "en",
                "zh",
            )
            self.assertEqual(count, 2)
            self.assertIsNotNone(store.exact_memory("Rated current is 630 A.", "en", "zh"))

    def test_memory_normalization_and_parameters(self):
        self.assertEqual(normalize_memory_text(" Rated voltage is 10 kV. "), "rated voltage is 10 kv")
        self.assertNotEqual(parameter_signature("10 kV"), parameter_signature("35 kV"))
        self.assertEqual(len(segment_text("One. Two.\nThree.")), 3)

    def test_utf16_and_gb18030_text_files(self):
        with tempfile.TemporaryDirectory() as directory:
            utf16_path = Path(directory) / "utf16.txt"
            gb_path = Path(directory) / "gb.txt"
            utf16_path.write_bytes("额定电压 10 kV".encode("utf-16"))
            gb_path.write_bytes("断路器额定电流".encode("gb18030"))
            self.assertEqual(extract_document(str(utf16_path)).text, "额定电压 10 kV")
            self.assertEqual(text_candidates(gb_path)[0].text, "断路器额定电流")

    def test_unsafe_polish_falls_back_to_draft(self):
        pipeline = TranslationPipeline(EchoBackend(), UnsafePolisher())
        result = pipeline.translate("Rated voltage is 10 kV.", "en", "zh", [], professional=True)
        self.assertEqual(result.text, result.draft)
        self.assertFalse(result.polished)
        self.assertTrue(any("自动恢复" in warning for warning in result.warnings))

    def test_longest_term_is_protected(self):
        pipeline = TranslationPipeline(EchoBackend())
        terms = [
            Term(None, "current", "电流"),
            Term(None, "short-circuit current", "短路电流", category="固定短语", priority=200),
        ]
        result = pipeline.translate("short-circuit current", "en", "zh", terms)
        self.assertEqual(result.text, "短路电流")

    def test_known_argos_marker_artifact_is_removed(self):
        pipeline = TranslationPipeline(MarkerArtifactBackend())
        result = pipeline.translate("IEC 60947-2", "en", "zh", [])
        self.assertEqual(result.text, "IEC 60947-2")

    def test_english_terms_restore_word_boundaries(self):
        pipeline = TranslationPipeline(JoinedEnglishMarkerBackend())
        terms = [
            Term(None, "vacuum circuit breaker", "真空断路器"),
            Term(None, "rated voltage", "额定电压"),
        ]
        result = pipeline.translate("真空断路器的额定电压为11 kV。", "zh", "en", terms)
        self.assertEqual(result.text, "rated voltage for vacuum circuit breaker is 11 kV.")

    def test_parameters_next_to_chinese_are_protected_without_chinese_suffix(self):
        values = TranslationPipeline.protected_values("额定电压为11 kV，符合IEC 62271标准。")
        self.assertEqual(values, ("11 kV", "IEC 62271"))

    def test_llama_cli_reads_prompt_from_utf8_file(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            prompt_path = Path(command[command.index("-f") + 1])
            captured["prompt"] = prompt_path.read_text(encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "润色译文".encode("utf-8"), b"")

        polisher = LocalLlamaPolisher("model.gguf")
        with mock.patch("ee_translator.polishing.subprocess.run", side_effect=fake_run):
            result = polisher._polish_with_cli(Path("llama-cli.exe"), "中文 prompt")
        self.assertEqual(result, "润色译文")
        self.assertIn("-f", captured["command"])
        self.assertNotIn("-p", captured["command"])
        self.assertIn("中文 prompt", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
