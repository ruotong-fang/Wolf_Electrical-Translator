import csv
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import re
import sqlite3
from typing import Iterable, List, Optional

from .electrical_terms import ELECTRICAL_TERMS, SOURCE as PUBLIC_TERM_SOURCE
from .extended_terms import EXTENDED_TERMS


TERM_CATEGORIES = ("专业术语", "固定短语")

MEMORY_PARAMETER_PATTERN = re.compile(
    r"\b(?:IEC|IEEE|EN|BS|DIN|NFPA)\s*[-:]?\s*\d[\w.-]*\b"
    r"|\b\d+(?:\.\d+)?\s*(?:kV|V|mV|kA|A|mA|MW|kW|W|MVA|kVA|VA|Hz|mm²|mm2|mm|Ω|ohm)?\b",
    re.IGNORECASE,
)


def segment_text(text: str) -> List[str]:
    segments = []
    for block in re.split(r"\n+", text):
        block = block.strip()
        if not block:
            continue
        parts = re.findall(r".+?(?:[。！？.!?；;]+|$)", block)
        segments.extend(part.strip() for part in parts if part.strip())
    return segments or ([text.strip()] if text.strip() else [])


def normalize_memory_text(text: str) -> str:
    normalized = text.casefold().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[，,；;：:]", ",", normalized)
    normalized = re.sub(r"[。.!！?？]+$", "", normalized)
    return normalized


def parameter_signature(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold().replace(" ", "") for match in MEMORY_PARAMETER_PATTERN.finditer(text))


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


@dataclass(frozen=True)
class Term:
    id: Optional[int]
    english: str
    chinese: str
    note: str = ""
    category: str = "专业术语"
    priority: int = 100
    domain: str = "通用"
    source: str = "用户词库"
    aliases: str = ""
    status: str = "已审核"


@dataclass(frozen=True)
class TranslationMemory:
    id: Optional[int]
    source_text: str
    target_text: str
    source_language: str
    target_language: str
    reviewed: bool = True
    use_count: int = 0


DEFAULT_TERMS = (
    ("circuit breaker", "断路器", "专业术语"),
    ("busbar", "母排", "专业术语"),
    ("switchgear", "开关设备", "专业术语"),
    ("current transformer", "电流互感器", "专业术语"),
    ("voltage transformer", "电压互感器", "专业术语"),
    ("earthing", "接地", "专业术语"),
    ("grounding", "接地", "专业术语"),
    ("cable gland", "电缆密封套", "专业术语"),
    ("single-line diagram", "单线图", "专业术语"),
    ("rated voltage", "额定电压", "专业术语"),
    ("rated current", "额定电流", "专业术语"),
    ("short-circuit current", "短路电流", "专业术语"),
    ("distribution board", "配电板", "专业术语"),
    ("protective relay", "保护继电器", "专业术语"),
    ("shall be provided with", "应配备", "固定短语"),
    ("unless otherwise specified", "除非另有规定", "固定短语"),
    ("in accordance with", "符合", "固定短语"),
    ("under normal operating conditions", "在正常运行条件下", "固定短语"),
)


class TerminologyStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _columns(db: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    english TEXT NOT NULL COLLATE NOCASE,
                    chinese TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '专业术语',
                    priority INTEGER NOT NULL DEFAULT 100,
                    domain TEXT NOT NULL DEFAULT '通用',
                    source TEXT NOT NULL DEFAULT '用户词库',
                    aliases TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '已审核',
                    UNIQUE(english, chinese, domain)
                )
                """
            )
            columns = self._columns(db, "terms")
            required = {"category", "priority", "domain", "source", "aliases", "status"}
            if not required <= columns:
                db.execute("DROP TABLE IF EXISTS terms_v2")
                db.execute(
                    """
                    CREATE TABLE terms_v2 (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        english TEXT NOT NULL COLLATE NOCASE,
                        chinese TEXT NOT NULL,
                        note TEXT NOT NULL DEFAULT '',
                        category TEXT NOT NULL DEFAULT '专业术语',
                        priority INTEGER NOT NULL DEFAULT 100,
                        domain TEXT NOT NULL DEFAULT '通用',
                        source TEXT NOT NULL DEFAULT '原有词库',
                        aliases TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT '已审核',
                        UNIQUE(english, chinese, domain)
                    )
                    """
                )
                category_expr = "category" if "category" in columns else "'专业术语'"
                priority_expr = "priority" if "priority" in columns else "100"
                db.execute(
                    f"""INSERT OR IGNORE INTO terms_v2
                        (id, english, chinese, note, category, priority)
                        SELECT id, english, chinese, note, {category_expr}, {priority_expr} FROM terms"""
                )
                db.execute("DROP TABLE terms")
                db.execute("ALTER TABLE terms_v2 RENAME TO terms")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_text TEXT NOT NULL,
                    target_text TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    reviewed INTEGER NOT NULL DEFAULT 1,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_text, source_language, target_language)
                )
                """
            )
            missing_builtin = [
                term for term in DEFAULT_TERMS
                if not db.execute(
                    "SELECT 1 FROM terms WHERE english = ? AND chinese = ? LIMIT 1",
                    term[:2],
                ).fetchone()
            ]
            if missing_builtin:
                db.executemany(
                    """INSERT OR IGNORE INTO terms
                        (english, chinese, category, domain, source, priority)
                        VALUES (?, ?, ?, '通用', '内置基础词库', 120)""",
                    missing_builtin,
                )

            missing_public = [
                term for term in ELECTRICAL_TERMS
                if not db.execute(
                    "SELECT 1 FROM terms WHERE english = ? AND chinese = ? LIMIT 1",
                    term[:2],
                ).fetchone()
            ]
            if missing_public:
                db.executemany(
                    """INSERT OR IGNORE INTO terms
                        (english, chinese, category, domain, source, priority)
                        VALUES (?, ?, ?, ?, ?, 100)""",
                    ((*term, PUBLIC_TERM_SOURCE) for term in missing_public),
                )

            extended_count = db.execute(
                "SELECT COUNT(*) FROM terms WHERE source LIKE 'ECDICT%'"
            ).fetchone()[0]
            if extended_count < len(EXTENDED_TERMS):
                db.executemany(
                    """INSERT OR IGNORE INTO terms
                        (english, chinese, note, category, priority, domain, source, aliases, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    EXTENDED_TERMS,
                )

    def list_terms(self, category: str = "") -> List[Term]:
        query = "SELECT id, english, chinese, note, category, priority, domain, source, aliases, status FROM terms"
        params = ()
        if category:
            query += " WHERE category = ?"
            params = (category,)
        query += " ORDER BY priority DESC, LENGTH(english) DESC, english"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [Term(**dict(row)) for row in rows]

    def save(self, term: Term) -> int:
        english = term.english.strip()
        chinese = term.chinese.strip()
        category = term.category if term.category in TERM_CATEGORIES else "专业术语"
        if not english or not chinese:
            raise ValueError("中英文内容不能为空")
        with self._connect() as db:
            if term.id is None:
                cursor = db.execute(
                    """INSERT INTO terms
                        (english, chinese, note, category, priority, domain, source, aliases, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (english, chinese, term.note.strip(), category, int(term.priority), term.domain.strip() or "通用",
                     term.source.strip() or "用户词库", term.aliases.strip(), term.status.strip() or "已审核"),
                )
                return int(cursor.lastrowid)
            db.execute(
                """UPDATE terms SET english=?, chinese=?, note=?, category=?, priority=?,
                    domain=?, source=?, aliases=?, status=? WHERE id=?""",
                (english, chinese, term.note.strip(), category, int(term.priority), term.domain.strip() or "通用",
                 term.source.strip() or "用户词库", term.aliases.strip(), term.status.strip() or "已审核", term.id),
            )
            return term.id

    def delete(self, term_ids: Iterable[int]) -> None:
        self._delete_ids("terms", term_ids)

    def export_terms(self, path: str) -> int:
        terms = self.list_terms()
        with open(path, "w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(("英文", "中文", "类型", "领域", "优先级", "来源", "别名", "状态", "备注"))
            writer.writerows((t.english, t.chinese, t.category, t.domain, t.priority, t.source, t.aliases, t.status, t.note) for t in terms)
        return len(terms)

    def import_terms(self, path: str) -> int:
        count = 0
        with open(path, "r", encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                english = (row.get("英文") or row.get("english") or "").strip()
                chinese = (row.get("中文") or row.get("chinese") or "").strip()
                if not english or not chinese:
                    continue
                category = (row.get("类型") or row.get("category") or "专业术语").strip()
                priority = int(row.get("优先级") or row.get("priority") or 100)
                note = (row.get("备注") or row.get("note") or "").strip()
                domain = (row.get("领域") or row.get("domain") or "通用").strip()
                term_source = (row.get("来源") or row.get("source") or "用户导入").strip()
                aliases = (row.get("别名") or row.get("aliases") or "").strip()
                status = (row.get("状态") or row.get("status") or "待审核").strip()
                with self._connect() as db:
                    db.execute(
                        """
                        INSERT INTO terms (english, chinese, note, category, priority, domain, source, aliases, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(english, chinese, domain) DO UPDATE SET
                            note=excluded.note, category=excluded.category, priority=excluded.priority,
                            source=excluded.source, aliases=excluded.aliases, status=excluded.status
                        """,
                        (english, chinese, note, category, priority, domain, term_source, aliases, status),
                    )
                count += 1
        return count

    def save_memory(self, memory: TranslationMemory) -> int:
        source_text = memory.source_text.strip()
        target_text = memory.target_text.strip()
        if not source_text or not target_text:
            raise ValueError("原文和译文不能为空")
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO translation_memory
                    (source_text, target_text, source_language, target_language, reviewed, use_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_text, source_language, target_language) DO UPDATE SET
                    target_text=excluded.target_text, reviewed=excluded.reviewed,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (source_text, target_text, memory.source_language, memory.target_language,
                 int(memory.reviewed), memory.use_count),
            )
            row = db.execute(
                "SELECT id FROM translation_memory WHERE source_text=? AND source_language=? AND target_language=?",
                (source_text, memory.source_language, memory.target_language),
            ).fetchone()
            return int(row[0])

    def exact_memory(self, text: str, source: str, target: str) -> Optional[TranslationMemory]:
        with self._connect() as db:
            row = db.execute(
                """SELECT id, source_text, target_text, source_language, target_language,
                          reviewed, use_count FROM translation_memory
                   WHERE source_text=? AND source_language=? AND target_language=? AND reviewed=1""",
                (text.strip(), source, target),
            ).fetchone()
            if row:
                db.execute("UPDATE translation_memory SET use_count=use_count+1 WHERE id=?", (row["id"],))
        return self._memory_from_row(row) if row else None

    def similar_memories(self, text: str, source: str, target: str, limit: int = 5) -> List[tuple[float, TranslationMemory]]:
        probe = normalize_memory_text(text)
        if not probe:
            return []
        candidates = self.list_memories(source, target, limit=1000)
        scored = [(SequenceMatcher(None, probe, normalize_memory_text(item.source_text)).ratio(), item) for item in candidates]
        return sorted((item for item in scored if item[0] >= 0.65), reverse=True, key=lambda item: item[0])[:limit]

    def save_aligned_memory(self, source_text: str, target_text: str, source: str, target: str) -> int:
        source_segments = segment_text(source_text)
        target_segments = segment_text(target_text)
        pairs = list(zip(source_segments, target_segments)) if len(source_segments) == len(target_segments) else []
        if not pairs:
            source_blocks = [block.strip() for block in source_text.splitlines() if block.strip()]
            target_blocks = [block.strip() for block in target_text.splitlines() if block.strip()]
            if len(source_blocks) == len(target_blocks):
                pairs = list(zip(source_blocks, target_blocks))
        if not pairs:
            pairs = [(source_text.strip(), target_text.strip())]
        for source_unit, target_unit in pairs:
            self.save_memory(TranslationMemory(None, source_unit, target_unit, source, target))
        if len(pairs) > 1:
            self.save_memory(TranslationMemory(None, source_text, target_text, source, target))
        return len(pairs)

    def list_memories(self, source: str = "", target: str = "", limit: int = 2000) -> List[TranslationMemory]:
        query = """SELECT id, source_text, target_text, source_language, target_language,
                          reviewed, use_count FROM translation_memory"""
        params = []
        clauses = []
        if source:
            clauses.append("source_language=?")
            params.append(source)
        if target:
            clauses.append("target_language=?")
            params.append(target)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def delete_memories(self, memory_ids: Iterable[int]) -> None:
        self._delete_ids("translation_memory", memory_ids)

    def _delete_ids(self, table: str, item_ids: Iterable[int]) -> None:
        ids = list(item_ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as db:
            db.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", ids)

    @staticmethod
    def _memory_from_row(row: sqlite3.Row) -> TranslationMemory:
        values = dict(row)
        values["reviewed"] = bool(values["reviewed"])
        return TranslationMemory(**values)
