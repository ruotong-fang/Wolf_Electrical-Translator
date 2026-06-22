from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

from .polishing import LocalLlamaPolisher, PolishingUnavailable
from .terminology import Term


class TranslationUnavailable(RuntimeError):
    pass


class TranslationBackend(Protocol):
    def translate(self, text: str, source: str, target: str) -> str:
        ...

    def available_pairs(self) -> Sequence[Tuple[str, str]]:
        ...


class ArgosBackend:
    def __init__(self):
        self._runtimes = {}

    def _modules(self):
        try:
            import ctranslate2
            from argostranslate import package
        except ImportError as exc:
            raise TranslationUnavailable(
                "未安装本地翻译组件。请安装完整版应用。"
            ) from exc
        return ctranslate2, package

    def _installed_packages(self):
        _, package = self._modules()
        return [item for item in package.get_installed_packages() if item.type == "translate"]

    def available_pairs(self) -> Sequence[Tuple[str, str]]:
        return [(item.from_code, item.to_code) for item in self._installed_packages()]

    def translate(self, text: str, source: str, target: str) -> str:
        pair = (source, target)
        package = next(
            (item for item in self._installed_packages() if (item.from_code, item.to_code) == pair),
            None,
        )
        if package is None:
            raise TranslationUnavailable(f"缺少 {source} → {target} 离线模型")

        runtime = self._runtimes.get(pair)
        if runtime is None:
            ctranslate2, _ = self._modules()
            runtime = ctranslate2.Translator(
                str(package.package_path / "model"),
                device="cpu",
                inter_threads=1,
                intra_threads=2,
                compute_type="int8",
            )
            self._runtimes[pair] = runtime

        # The Stanza splitter bundled in Argos 1.9 models can hang under Python 3.13.
        # Split common sentence boundaries here and feed the model directly instead.
        chunks = [chunk for chunk in re.split(r"(?<=[.!?。！？；;])|(\n+)", text) if chunk]
        translated = []
        for chunk in chunks:
            if not chunk.strip():
                translated.append(chunk)
                continue
            leading = chunk[: len(chunk) - len(chunk.lstrip())]
            trailing = chunk[len(chunk.rstrip()) :]
            tokens = package.tokenizer.encode(chunk.strip())
            target_prefix = [[package.target_prefix]] if package.target_prefix else None
            result = runtime.translate_batch(
                [tokens],
                target_prefix=target_prefix,
                replace_unknowns=True,
                beam_size=2,
                num_hypotheses=1,
            )[0]
            translated.append(leading + package.tokenizer.decode(result.hypotheses[0]) + trailing)
        return "".join(translated)


@dataclass(frozen=True)
class TranslationResult:
    text: str
    warnings: Tuple[str, ...]
    draft: str = ""
    polished: bool = False
    from_memory: bool = False


class TranslationPipeline:
    # Protect engineering values before machine translation.
    PROTECTED_PATTERN = re.compile(
        r"\b(?:IEC|IEEE|EN|BS|DIN|NFPA)\s*[-:]?\s*\d[\w.-]*\b"
        r"|\b(?:IP|IK)\s*\d{2,3}\b"
        r"|\b\d+(?:\.\d+)?\s*(?:kV|V|mV|kA|A|mA|MW|kW|W|MVA|kVA|VA|Hz|mm²|mm2|mm|Ω|ohm)\b"
        r"|\b[A-Z]{2,}[A-Z0-9._/-]*\d[A-Z0-9._/-]*\b",
        re.IGNORECASE,
    )

    def __init__(self, backend: TranslationBackend, polisher: Optional[LocalLlamaPolisher] = None):
        self.backend = backend
        self.polisher = polisher

    @staticmethod
    def _marker(index: int) -> str:
        # Alphabetic markers survive both bundled models more reliably than digits.
        letters = ""
        value = index
        while True:
            value, remainder = divmod(value, 26)
            letters = chr(ord("A") + remainder) + letters
            if value == 0:
                break
            value -= 1
        # Neutral reference IDs survive both bundled models without gaining a translation.
        return f"REF991{letters}"

    @classmethod
    def protected_values(cls, text: str) -> Tuple[str, ...]:
        return tuple(match.group(0) for match in cls.PROTECTED_PATTERN.finditer(text))

    @classmethod
    def validate_result(cls, source_text: str, result_text: str, terms: Sequence[Term], source: str) -> Tuple[str, ...]:
        warnings = []
        result_folded = result_text.casefold()
        missing_values = [value for value in cls.protected_values(source_text) if value.casefold() not in result_folded]
        if missing_values:
            warnings.append("译文缺少工程参数：" + "、".join(missing_values))
        missing_terms = []
        for term in terms:
            source_term, target_term = ((term.english, term.chinese) if source == "en" else (term.chinese, term.english))
            if source_term.casefold() in source_text.casefold() and target_term.casefold() not in result_folded:
                missing_terms.append(target_term)
        if missing_terms:
            warnings.append("译文未采用指定术语：" + "、".join(dict.fromkeys(missing_terms)))
        return tuple(warnings)

    def translate(
        self,
        text: str,
        source: str,
        target: str,
        terms: Sequence[Term],
        professional: bool = False,
    ) -> TranslationResult:
        if not text.strip():
            return TranslationResult("", ())

        replacements: Dict[str, str] = {}

        def protect_match(match: re.Match) -> str:
            marker = self._marker(len(replacements))
            replacements[marker] = match.group(0)
            return marker

        protected = self.PROTECTED_PATTERN.sub(protect_match, text)
        term_pairs = [
            (term.english, term.chinese, term.priority)
            if source == "en"
            else (term.chinese, term.english, term.priority)
            for term in terms
        ]
        term_pairs.sort(key=lambda item: (len(item[0]), item[2]), reverse=True)

        for source_term, target_term, _priority in term_pairs:
            flags = re.IGNORECASE if source == "en" else 0
            escaped = re.escape(source_term)
            pattern_text = rf"(?<!\w){escaped}(?!\w)" if source == "en" else escaped
            pattern = re.compile(pattern_text, flags)
            if pattern.search(protected):
                marker = self._marker(len(replacements))
                protected = pattern.sub(marker, protected)
                replacements[marker] = target_term

        translated = self.backend.translate(protected, source, target)

        missing: List[str] = []
        for marker, value in reversed(replacements.items()):
            marker_pattern = r"\s*".join(map(re.escape, marker))
            flexible = re.compile(marker_pattern + r"\s*(?:型(?:电力)?机车)?", re.IGNORECASE)
            translated, count = flexible.subn(lambda _: value, translated)
            if count == 0:
                missing.append(value)

        warnings: Tuple[str, ...] = ()
        if missing:
            warnings = ("模型未保留部分术语或工程参数，请人工核对：" + "、".join(missing),)
        draft = translated
        warnings += self.validate_result(text, draft, terms, source)
        if not professional:
            return TranslationResult(draft, warnings, draft=draft)
        if self.polisher is None:
            return TranslationResult(draft, warnings + ("未配置本地润色模型，已保留快速翻译结果",), draft=draft)
        try:
            polished = self.polisher.polish(text, draft, source, target, terms)
        except PolishingUnavailable as exc:
            return TranslationResult(draft, warnings + (str(exc) + "，已保留快速翻译结果",), draft=draft)
        polish_warnings = self.validate_result(text, polished, terms, source)
        if polish_warnings:
            return TranslationResult(
                draft,
                warnings + ("润色结果未通过技术参数校验，已自动恢复快速翻译结果",) + polish_warnings,
                draft=draft,
            )
        return TranslationResult(polished, (), draft=draft, polished=True)


def install_argos_package(path: str) -> None:
    try:
        from argostranslate import package
    except ImportError as exc:
        raise TranslationUnavailable("当前应用未包含 Argos Translate 组件") from exc
    package.install_from_path(path)


def install_bundled_packages(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    installed = 0
    for package_path in sorted(directory.glob("*.argosmodel")):
        install_argos_package(str(package_path))
        installed += 1
    return installed
