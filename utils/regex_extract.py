import re
from typing import Dict, List

from .normalize import normalize_characteristic, normalize_unit

CHARACTERISTICS = [
    "производительность", "подача", "расход", "напор", "мощность", "мощность двигателя",
    "номинальная мощность", "масса", "вес", "напряжение", "частота", "ток", "диаметр",
    "длина", "ширина", "высота", "давление", "температура", "обороты", "частота вращения",
    "степень защиты", "класс защиты", "материал", "габариты", "размеры",
]

UNITS = r"кВт|Вт|кг|г|т|м3/ч|м³/ч|м3/мин|м³/мин|л/с|л/мин|м|мм|см|В|кВ|А|Гц|об/мин|rpm|бар|МПа|Па|°C|%"
NUM = r"[<>≤≥~≈±]?\s*\d+[\d\s.,/\-]*"


def extract_by_regex(text: str, max_items: int = 80) -> List[Dict[str, str]]:
    results = []
    if not text:
        return results
    normalized_text = re.sub(r"\s+", " ", text)

    for char in CHARACTERISTICS:
        patterns = [
            rf"({re.escape(char)})\s*[:\-–—]?\s*({NUM})\s*({UNITS})",
            rf"({re.escape(char)})\s+[^.;:,]{{0,40}}?({NUM})\s*({UNITS})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, normalized_text, flags=re.IGNORECASE):
                characteristic = normalize_characteristic(match.group(1))
                value = match.group(2).replace(" ", "").replace(",", ".").strip()
                unit = normalize_unit(match.group(3))
                item = {"characteristic": characteristic, "value": value, "unit": unit}
                if item not in results:
                    results.append(item)
                if len(results) >= max_items:
                    return results

    # IP / защита / текстовые характеристики
    text_patterns = [
        (r"(степень защиты)\s*[:\-–—]?\s*(IP\s*\d{2})", "Степень защиты"),
        (r"(материал)\s*[:\-–—]?\s*([А-Яа-яA-Za-z0-9 ,\-]{3,80})", "Материал"),
    ]
    for pattern, name in text_patterns:
        for match in re.finditer(pattern, normalized_text, flags=re.IGNORECASE):
            value = match.group(2).strip()
            item = {"characteristic": name, "value": value, "unit": ""}
            if item not in results:
                results.append(item)
            if len(results) >= max_items:
                return results

    return results
