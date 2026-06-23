from pathlib import Path

from ee_translator.engine import ArgosBackend, TranslationPipeline, install_bundled_packages
from ee_translator.terminology import Term


install_bundled_packages(Path("models"))
backend = ArgosBackend()
pairs = set(backend.available_pairs())
assert {("en", "zh"), ("zh", "en")} <= pairs, f"Missing translation directions:{pairs}"

pipeline = TranslationPipeline(backend)
terms = [
    Term(None, "vacuum circuit breaker", "真空断路器"),
    Term(None, "rated voltage", "额定电压"),
    Term(None, "standard", "标准"),
]
samples = (
    ("The vacuum circuit breaker rated voltage is 11 kV according to IEC 62271.", "en", "zh", "真空断路器"),
    ("真空断路器的额定电压为11 kV，符合IEC 62271标准。", "zh", "en", "vacuum circuit breaker"),
)
for text, source, target, expected in samples:
    result = pipeline.translate(text, source, target, terms)
    assert expected in result.text, result.text
    assert "11 kV" in result.text, result.text
    assert "IEC 62271" in result.text, result.text
    assert not result.warnings, result.warnings
    print(f"{source}->{target}: translation ok")

print("Offline model validation passed.")
