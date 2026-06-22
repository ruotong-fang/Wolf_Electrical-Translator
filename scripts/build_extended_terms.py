import csv
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = ROOT / "ecdict-source.csv"
OUTPUT_FILE = ROOT / "extended_terms.py"
TARGET_COUNT = 1100

sys.path.insert(0, str(ROOT.parent))

ENGLISH_ROOTS = re.compile(
    r"(?:electric|electrical|electrom|voltage|current|power|circuit|switch|breaker|relay|transform|"
    r"motor|generator|alternator|cable|wiring|wire|conductor|insulat|ground|earth|lightning|surge|"
    r"protect|control|terminal|busbar|substation|distribution|transmission|frequency|phase|reactive|"
    r"harmonic|impedance|resistan|capacit|induct|battery|charger|inverter|rectifier|converter|"
    r"semiconductor|transistor|diode|thyristor|sensor|meter|instrument|lighting|lumina|photovoltaic|"
    r"solar|wind turbine|energy storage|grid|scada|plc|commission|dielectric|magnetic|winding|coil|"
    r"electrode|fuse|contactor|disconnect|short.circuit|overcurrent|overvoltage|undervoltage|arc)",
    re.IGNORECASE,
)

CHINESE_ROOTS = re.compile(
    r"电|电压|电流|功率|线路|回路|导体|绝缘|接地|开关|继电|变压|电机|发电|电缆|磁|阻抗|"
    r"电阻|电容|电感|频率|谐波|相位|母线|照明|光通量|防雷|浪涌|短路|过载|熔断|端子|"
    r"线圈|绕组|电极|半导体|晶体管|二极管|整流|逆变|变频|配电|输电|电网|电池|蓄电|"
    r"充电|放电|无功|有功|触电|漏电|介电|耐压|电弧|电磁|自动化|控制器|传感器|仪表|计量"
)

EXCLUDED = re.compile(
    r"(?:electric chair|electric eel|electric guitar|electric blanket|political power|military power|"
    r"flower power|brain wave|horsepower|power of attorney|power politics|magnetic personality)",
    re.IGNORECASE,
)

SUSPECT_WORD = re.compile(
    r"(?:dev-ice|kmeter|recyifier|ployphase|anti tr switch|b power supply)",
    re.IGNORECASE,
)

SUSPECT_TRANSLATION = re.compile(
    r"(?:说明器|不连接设备|电子马达|功率源|电驿|六向整流|共表频率|稳器|比压器|不着火继电器)"
)

DOMAIN_RULES = (
    ("新能源与储能", re.compile(r"photovoltaic|solar|wind turbine|battery|charger|energy storage", re.I)),
    ("继电保护", re.compile(r"relay|protection|overcurrent|earth fault|differential|trip", re.I)),
    ("开关与保护", re.compile(r"switch|breaker|fuse|contactor|disconnect|arc", re.I)),
    ("变压器与电机", re.compile(r"transformer|motor|generator|alternator|winding|coil", re.I)),
    ("电缆与接地", re.compile(r"cable|wire|wiring|conductor|ground|earth|insulat|terminal", re.I)),
    ("电力电子", re.compile(r"inverter|rectifier|converter|semiconductor|transistor|diode|thyristor", re.I)),
    ("电能质量", re.compile(r"harmonic|voltage sag|voltage swell|power factor|frequency", re.I)),
    ("测量与控制", re.compile(r"sensor|meter|instrument|control|scada|plc|automation", re.I)),
    ("照明", re.compile(r"lighting|lumina|lamp|illumin", re.I)),
    ("试验与调试", re.compile(r"test|commission|dielectric|withstand", re.I)),
)


def choose_translation(raw: str) -> str:
    if not raw:
        return ""
    candidates = []
    for line in raw.splitlines():
        if line.startswith("[网络]"):
            continue
        tagged = "[电]" in line or "[电子]" in line or "[物]" in line
        line = re.sub(r"\[[^]]+\]", "", line)
        line = re.sub(r"^(?:n|v|adj|adv|prep|abbr)\.\s*", "", line, flags=re.I)
        for part in re.split(r"[；;，,]", line):
            part = part.strip(" ：:。.()（）")
            if not part or not re.search(r"[\u4e00-\u9fff]", part):
                continue
            hits = len(CHINESE_ROOTS.findall(part))
            if not hits:
                continue
            score = hits * 10 + (8 if tagged else 0) + (5 if 2 <= len(part) <= 12 else 0) - max(0, len(part) - 22)
            candidates.append((score, part))
    if not candidates:
        return ""
    value = max(candidates, key=lambda item: item[0])[1]
    value = re.sub(r"^(?:一种|用于|关于)", "", value)
    return value if 1 < len(value) <= 28 else ""


def domain_for(word: str) -> str:
    for domain, pattern in DOMAIN_RULES:
        if pattern.search(word):
            return domain
    if re.search(r"power|voltage|current|grid|distribution|transmission|substation|circuit", word, re.I):
        return "电力系统"
    return "电气通用"


def main() -> None:
    existing = set()
    from ee_translator.electrical_terms import ELECTRICAL_TERMS
    from ee_translator.terminology import DEFAULT_TERMS

    for english, *_rest in (*DEFAULT_TERMS, *ELECTRICAL_TERMS):
        existing.add(english.casefold())

    selected = []
    seen = set(existing)
    with SOURCE_FILE.open("r", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            word = (row.get("word") or "").strip()
            folded = word.casefold()
            if not word or folded in seen or EXCLUDED.search(word) or not ENGLISH_ROOTS.search(word):
                continue
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 /()+.,'\-]{1,58}", word):
                continue
            if len(word.split()) > 7:
                continue
            chinese = choose_translation(row.get("translation") or "")
            if not chinese or SUSPECT_WORD.search(word) or SUSPECT_TRANSLATION.search(chinese):
                continue
            score = 0
            score += 30 if " " in word or "-" in word else 0
            score += 20 if "[电]" in (row.get("translation") or "") else 0
            score += min(20, len(ENGLISH_ROOTS.findall(word)) * 8)
            score += min(10, int(row.get("collins") or 0) * 2)
            score += 8 if 3 <= len(chinese) <= 12 else 0
            selected.append((score, word, chinese, domain_for(word)))
            seen.add(folded)

    selected.sort(key=lambda item: (-item[0], item[1].casefold()))
    selected = selected[:TARGET_COUNT]
    if len(selected) < TARGET_COUNT:
        raise RuntimeError(f"Only {len(selected)} electrical terms passed the quality filters")

    with OUTPUT_FILE.open("w", encoding="utf-8", newline="\n") as output:
        output.write(
            '"""Generated ECDICT electrical terminology embedded in the application.\n\n'
            'Do not edit manually; regenerate with scripts/build_extended_terms.py.\n"""\n\n'
        )
        output.write("EXTENDED_TERMS = (\n")
        for _score, english, chinese, domain in selected:
            values = (
                english, chinese, "", "专业术语", 70, domain,
                "ECDICT（MIT）电气领域筛选", "", "待审核",
            )
            output.write(f"    {values!r},\n")
        output.write(")\n")
    print(f"Generated {len(selected)} terms: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
