import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppPreferences:
    model_path: str = ""
    context_size: int = 8192
    model_threads: int = 4

    @classmethod
    def load(cls, path: Path) -> "AppPreferences":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return cls()
        known = {key: data[key] for key in asdict(cls()).keys() if key in data}
        return cls(**known)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
