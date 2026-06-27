import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from ee_translator.documents import extract_document, text_candidates
from ee_translator.engine import TranslationPipeline
from ee_translator.polishing import LocalLlamaPolisher, PolishingUnavailable
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

    def test_llama_cli_uses_model_chat_template_and_utf8_prompt_file(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            prompt_path = Path(command[command.index("-f") + 1])
            captured["prompt"] = prompt_path.read_text(encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "润色译文".encode("utf-8"), b"")

        polisher = LocalLlamaPolisher("model.gguf")
        with mock.patch("ee_translator.polishing.subprocess.run", side_effect=fake_run):
            result = polisher._polish_with_cli(Path("llama-completion.exe"), "中文 prompt")
        self.assertEqual(result, "润色译文")
        self.assertIn("-f", captured["command"])
        self.assertNotIn("-p", captured["command"])
        self.assertIn("--jinja", captured["command"])
        self.assertIn("--single-turn", captured["command"])
        self.assertIn("-sysf", captured["command"])
        self.assertNotIn("-no-cnv", captured["command"])
        self.assertIn("中文 prompt", captured["prompt"])
        self.assertNotIn("<|im_start|>", captured["prompt"])

    def test_llama_cli_falls_back_to_explicit_chatml_after_empty_output(self):
        calls = []

        def fake_run(command, **kwargs):
            prompt_path = Path(command[command.index("-f") + 1])
            calls.append((command, prompt_path.read_text(encoding="utf-8")))
            if len(calls) == 1:
                return subprocess.CompletedProcess(command, 0, b"", b"")
            return subprocess.CompletedProcess(command, 0, "润色译文".encode("utf-8"), b"")

        polisher = LocalLlamaPolisher("model.gguf")
        with mock.patch("ee_translator.polishing.subprocess.run", side_effect=fake_run):
            result = polisher._polish_with_cli(Path("llama-completion.exe"), "中文 prompt")
        self.assertEqual(result, "润色译文")
        self.assertIn("--jinja", calls[0][0])
        self.assertNotIn("<|im_start|>", calls[0][1])
        self.assertIn("-no-cnv", calls[1][0])
        self.assertIn("<|im_start|>assistant", calls[1][1])

    def test_professional_translation_examples_in_both_directions(self):
        examples = (
            (
                "差动保护装置持续比较保护区两端的电流。",
                "The differential protection device continuously compares currents at both ends of the protected area.",
                "The differential protection relay continuously compares the currents at both ends of the protected zone.",
                "zh", "en",
            ),
            (
                "The circuit breaker shall interrupt the rated short-circuit current within 60 ms.",
                "断路器应在60毫秒内中断额定短路电流。",
                "断路器应在60 ms内开断额定短路电流。",
                "en", "zh",
            ),
        )
        for original, draft, polished, source, target in examples:
            with self.subTest(source=source, target=target):
                backend = mock.Mock()
                backend.translate.return_value = draft
                polisher = mock.Mock()
                polisher.polish.return_value = polished
                result = TranslationPipeline(backend, polisher).translate(
                    original, source, target, [], professional=True
                )
                self.assertEqual(result.draft, draft)
                self.assertEqual(result.text, polished)
                self.assertTrue(result.polished)

    def test_llama_cli_runtime_log_is_not_polish_result(self):
        runtime_log = (
            "--no-conversation is not supported by 'llama-cli'\n"
            "please use llama-completion instead\n\n"
            "Loading model...\n"
            "available commands:\n"
        )

        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, runtime_log.encode("utf-8"), b"")

        polisher = LocalLlamaPolisher("model.gguf")
        with mock.patch("ee_translator.polishing.subprocess.run", side_effect=fake_run):
            with self.assertRaises(PolishingUnavailable):
                polisher._polish_with_cli(Path("llama-cli.exe"), "中文 prompt")

    def test_python_fallback_uses_chat_completion(self):
        model = mock.Mock()
        model.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "专业润色译文"}}]
        }
        polisher = LocalLlamaPolisher("model.gguf")
        with mock.patch.object(polisher, "_cli_path", return_value=Path("missing.exe")), \
             mock.patch.object(polisher, "_load", return_value=model), \
             mock.patch("ee_translator.polishing.bundled_runtime_dir", return_value=Path("missing-runtime")):
            result = polisher.polish("原文", "初译", "zh", "en", [])
        self.assertEqual(result, "专业润色译文")
        messages = model.create_chat_completion.call_args.kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")


if __name__ == "__main__":
    unittest.main()
