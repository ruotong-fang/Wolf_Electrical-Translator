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
    SYSTEM_PROMPT = "You are a precise electrical engineering translation editor."

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
        if (bundled_runtime_dir() / "llama-cli.exe").is_file():
            return "内置 llama.cpp 运行器不兼容：缺少 llama-completion.exe"
        try:
            import llama_cpp  # noqa: F401
        except ImportError:
            return "缺少本地模型运行组件 llama-cpp-python"
        return "本地专业润色已配置"

    def _cli_path(self) -> Path:
        return bundled_runtime_dir() / "llama-completion.exe"

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
        if (bundled_runtime_dir() / "llama-cli.exe").is_file():
            raise PolishingUnavailable("当前内置 llama.cpp 运行器不兼容：缺少 llama-completion.exe，请重新安装新版安装包")
        model = self._load()
        response = model.create_chat_completion(
            messages=(
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ),
            max_tokens=min(1024, self.context_size // 2),
            temperature=0.1,
            top_p=0.85,
            repeat_penalty=1.05,
        )
        text = response["choices"][0]["message"]["content"].strip()
        if not text:
            raise PolishingUnavailable("本地模型没有返回润色结果")
        return text

    def _polish_with_cli(self, cli_path: Path, prompt: str) -> str:
        chat_prompt = (
            f"<|im_start|>system\n{self.SYSTEM_PROMPT}"
            "<|im_end|>\n<|im_start|>user\n" + prompt
            + "<|im_end|>\n<|im_start|>assistant\n"
        )
        if len(chat_prompt) > 12000:
            raise PolishingUnavailable("文本过长，请分段使用专业翻译")
        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        with tempfile.TemporaryDirectory(prefix="ee-translator-llm-") as directory:
            system_path = Path(directory) / "system-prompt.txt"
            system_path.write_text(self.SYSTEM_PROMPT, encoding="utf-8")
            attempts = (
                # Let llama.cpp apply tokenizer.chat_template from the Qwen GGUF.
                ("jinja", prompt, "jinja"),
                # Compatibility fallback for runtimes without Jinja support.
                ("chatml", chat_prompt, "chatml"),
            )
            diagnostics = []
            for name, prompt_text, mode in attempts:
                prompt_path = Path(directory) / f"{name}-prompt.txt"
                prompt_path.write_text(prompt_text, encoding="utf-8")
                command = self._completion_command(cli_path, prompt_path, system_path, mode)
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
                text = self._clean_cli_output(completed.stdout)
                if completed.returncode == 0 and text:
                    return text
                diagnostics.append(self._diagnostic_line(name, completed))
        raise PolishingUnavailable("本地润色模型没有返回译文：" + "；".join(diagnostics))

    def _completion_command(
        self,
        cli_path: Path,
        prompt_path: Path,
        system_path: Path,
        mode: str,
    ) -> list[str]:
        command = [
            str(cli_path), "-m", self.model_path, "-f", str(prompt_path),
            "-c", str(self.context_size), "-n", "384", "-t", str(self.threads),
            "--temp", "0.1", "--top-p", "0.85", "--repeat-penalty", "1.05",
            "--no-display-prompt", "--no-warmup", "--simple-io", "--log-disable",
        ]
        if mode == "jinja":
            command.extend(("--jinja", "--single-turn", "-sysf", str(system_path)))
        elif mode == "chatml":
            command.append("-no-cnv")
        else:
            raise ValueError(f"未知 llama.cpp 调用模式：{mode}")
        return command

    def _clean_cli_output(self, data: bytes) -> str:
        text = self._decode_output(data).strip().removesuffix("<|im_end|>").strip()
        text = re.sub(r"\s*(?:\[end of text\]|<\|endoftext\|>|<\|im_end\|>)\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*(?:assistant|最终译文)\s*[:：]\s*", "", text, flags=re.IGNORECASE).strip()
        return "" if self._looks_like_runtime_log(text) else text

    def _diagnostic_line(self, name: str, completed: subprocess.CompletedProcess) -> str:
        stderr = self._decode_output(completed.stderr).strip()
        stdout = self._decode_output(completed.stdout).strip()
        detail = self._last_meaningful_line(stderr) or self._last_meaningful_line(stdout) or "无输出"
        return f"{name} 调用返回码 {completed.returncode}，{detail}"

    @staticmethod
    def _last_meaningful_line(text: str) -> str:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line:
                return line[:180]
        return ""

    @staticmethod
    def _looks_like_runtime_log(text: str) -> bool:
        lower = text.lower()
        log_markers = (
            "loading model",
            "available commands",
            "please use llama-completion instead",
            "build  :",
            "model  :",
            "modalities :",
        )
        return any(marker in lower for marker in log_markers)

    @staticmethod
    def _decode_output(data: bytes) -> str:
        for encoding in ("utf-8", "gb18030"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")
