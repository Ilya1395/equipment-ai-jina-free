import re
from typing import Optional

MOJIBAKE_MARKERS = ("Ð", "Ñ", "Р", "С")


def fix_mojibake(text: Optional[str]) -> str:
    """Repair common UTF-8-as-Latin1/CP1252 mojibake in Russian text.

    Example: 'ÐÐ°ÑÐ¾Ñ' -> 'Насос'.
    Leaves normal text unchanged.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return ""

    candidates = [text]
    for enc in ("latin1", "cp1252"):
        try:
            candidates.append(text.encode(enc, errors="ignore").decode("utf-8", errors="ignore"))
        except Exception:
            pass

    def score(s: str) -> int:
        cyr = len(re.findall(r"[А-Яа-яЁё]", s))
        bad = sum(s.count(m) for m in ("Ð", "Ñ", "�"))
        return cyr * 3 - bad * 5 + len(s.strip()) // 200

    return max(candidates, key=score)


def clean_text(text: Optional[str]) -> str:
    text = fix_mojibake(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
