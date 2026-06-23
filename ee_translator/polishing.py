from pathlib import Path
import re
import subprocess
import tempfile
from typing import Sequence

from .paths import bundled_runtime_dir
from .terminology import Term


class PolishingUnavailable(RuntimeError):
    pass


class LocalLlamaPolisher:
    def __init__(self, model_path: str = "", context_size: int = 2048, threads: int = 4):
        self.model_path = model_path
        self.context_size = context_size
        self.threads = threads
        self._model = None

    @property
    def configured(self) -> bool:
        return bool(self.model_path and Path(self.model_path).is_file())

    def status(self) -> str:
        if not self.configured:
            return "尚未选择本地润色模型"
        if self._cli_path().is_file():
            return "本地专业润色已就绪"
        try:
            import llama_cpp  # noqa: F401
        except ImportError:
            return "缺少本地模型运行组件 llama-cpp-python"
        return "本地专业润色已配置"

    def _cli_path(self) -> Path:
        runtime = bundled_runtime_dir()
        for filename in ("llama-cli.exe", "llama-completion.exe"):
            candidate = runtime / filename
            if candidate.is_file():
                return candidate
        return runtime / "llama-cli.exe"

    def _load(self):
        if not self.configured:
            raise PolishingUnavailable("尚未选择 GGUF 本地润色模型")
        if self._model is None:
            try:
                from llama_cpp import Llama
            except ImportError as exc:
                raise PolishingUnavailable("未安装本地模型运行组件 llama-cpp-python") from exc
            self._model = Llama(
                model_path=self.model_path,
                n_ctx=self.context_size,
                n_threads=self.threads,
                n_gpu_layers=0,
                verbose=False,
            )
        return self._model

    def polish(self, original: str, draft: str, source: str, target: str, terms: Sequence[Term]) -> str:
        direction = "英文到中文" if (source, target) == ("en", "zh") else "中文到英文"
        glossary = []
        for term in terms:
            left, right = (term.english, term.chinese) if source == "en" else (term.chinese, term.english)
            if left.lower() in original.lower():
                glossary.append(f"{left} => {right}")
        glossary_text = "\n".join(glossary[:80]) or "无"
        prompt = f"""你是电气工程技术文件编辑。请对{direction}机器译文进行受控润色。
规则：
1. 只改善专业表达、行业习惯和语序，不添加、删除或推测信息。
2. 数字、单位、标准号、设备编号、变量和段落结构必须保持不变。
3. 强制采用术语表中的译法。
4. 只输出最终译文，不解释。

术语表：
{glossary_text}

原文：
{original}

机器初译：
{draft}

最终译文："""
        cli_path = self._cli_path()
        if cli_path.is_file():
            return self._polish_with_cli(cli_path, prompt)
        model = self._load()
        response = model(
            prompt,
            max_tokens=min(1024, self.context_size // 2),
            temperature=0.1,
            top_p=0.85,
            repeat_penalty=1.05,
            stop=["\n\n原文：", "\n\n机器初译："],
            echo=False,
        )
        text = response["choices"][0]["text"].strip()
        if not text:
            raise PolishingUnavailable("本地模型没有返回润色结果")
        return text

    def _polish_with_cli(self, cli_path: Path, prompt: str) -> str:
        chat_prompt = (
            "<|im_start|>system\nYou are a precise electrical engineering editor."
            "<|im_end|>\n<|im_start|>user\n" + prompt
            + "<|im_end|>\n<|im_start|>assistant\n"
        )
        if len(chat_prompt) > 12000:
            raise PolishingUnavailable("文本过长，请分段使用专业翻译")
        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        with tempfile.TemporaryDirectory(prefix="ee-translator-llm-") as directory:
            prompt_path = Path(directory) / "prompt.txt"
            prompt_path.write_text(chat_prompt, encoding="utf-8")
            command = [
                str(cli_path), "-m", self.model_path, "-f", str(prompt_path),
                "-c", str(self.context_size), "-n", "384", "-t", str(self.threads),
                "--temp", "0.1", "--top-p", "0.85", "--repeat-penalty", "1.05",
                "-no-cnv", "--no-display-prompt", "--no-warmup", "--simple-io", "--log-disable",
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    timeout=900,
                    creationflags=creation_flags,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PolishingUnavailable(f"本地润色模型运行失败：{exc}") from exc
        text = self._decode_output(completed.stdout).strip().removesuffix("<|im_end|>").strip()
        text = re.sub(r"\s*(?:\[end of text\]|<\|endoftext\|>|<\|im_end\|>)\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*(?:assistant|最终译文)\s*[:：]\s*", "", text, flags=re.IGNORECASE).strip()
        if completed.returncode != 0 or not text:
            detail = self._decode_output(completed.stderr).strip().splitlines()
            message = detail[-1] if detail else "模型没有返回内容"
            raise PolishingUnavailable(f"本地润色模型运行失败：{message}")
        return text

    @staticmethod
    def _decode_output(data: bytes) -> str:
        for encoding in ("utf-8", "gb18030"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")
