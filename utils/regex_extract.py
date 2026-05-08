import re
from typing import Dict, List

from .normalize import normalize_characteristic, normalize_unit
from .text_utils import clean_text

CHARACTERISTICS = [
    "производительность", "подача", "расход", "напор", "мощность", "мощность двигателя",
    "номинальная мощность", "потребляемая мощность", "масса", "вес", "напряжение", "частота", "ток", "диаметр",
    "длина", "ширина", "высота", "давление", "температура", "обороты", "частота вращения",
    "степень защиты", "класс защиты", "материал", "габариты", "размеры", "глубина",
    "длина кабеля", "температура жидкости", "плотность", "ph", "pH", "число оборотов",
]

UNITS = r"кВт|Вт|кг|г|т|м3/ч|м³/ч|м3/час|м³/час|куб\. м/ч|куб\.м/ч|м3/мин|м³/мин|л/с|л/мин|м|мм|см|В|кВ|А|Гц|об/мин|об\. / мин|rpm|бар|МПа|Па|°C|°С|%"
NUM = r"[<>≤≥~≈±]?[ ]*\d+(?:[\d ]*[\.,]?\d+)?(?:[ ]*[-–—/][ ]*\d+(?:[\.,]\d+)?)?"

# Useful for product tables where the unit is embedded in the characteristic name.
CHAR_WITH_UNIT = [
    (r"производительность[^\n;:]{0,30}(?:м3/ч|м³/ч|куб\.?\s*м/ч)", "Производительность", "м3/ч"),
    (r"подача[^\n;:]{0,30}(?:м3/ч|м³/ч|куб\.?\s*м/ч)", "Производительность", "м3/ч"),
    (r"напор[^\n;:]{0,20}(?:м|метр)", "Напор", "м"),
    (r"мощность[^\n;:]{0,30}(?:кВт|квт)", "Мощность", "кВт"),
    (r"масса[^\n;:]{0,20}(?:кг|килограмм)", "Масса", "кг"),
    (r"вес[^\n;:]{0,20}(?:кг|килограмм)", "Масса", "кг"),
    (r"напряжение[^\n;:]{0,20}(?:В|вольт)", "Напряжение", "В"),
    (r"частота[^\n;:]{0,20}(?:Гц|герц)", "Частота", "Гц"),
]


def _add(results: List[Dict[str, str]], characteristic: str, value: str, unit: str, max_items: int) -> bool:
    value = clean_text(value).replace(" ", "").replace(",", ".")
    unit = normalize_unit(clean_text(unit))
    characteristic = normalize_characteristic(clean_text(characteristic))
    if not characteristic or not value:
        return False
    item = {"characteristic": characteristic, "value": value, "unit": unit}
    if item not in results:
        results.append(item)
    return len(results) >= max_items


def _normalize_for_regex(text: str) -> str:
    text = clean_text(text)
    # Keep table boundaries visible but make matching across short table cells possible.
    text = text.replace("|", " ; ")
    text = re.sub(r"[\t]+", " ; ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def extract_by_regex(text: str, max_items: int = 100) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    if not text:
        return results
    normalized_text = _normalize_for_regex(text)

    for char in CHARACTERISTICS:
        patterns = [
            rf"({re.escape(char)})\s*[:\-–—]?\s*({NUM})\s*({UNITS})",
            rf"({re.escape(char)})\s+[^.;:,]{{0,80}}?({NUM})\s*({UNITS})",
            rf"({re.escape(char)})\s*[;|]\s*({NUM})\s*({UNITS})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, normalized_text, flags=re.IGNORECASE):
                if _add(results, match.group(1), match.group(2), match.group(3), max_items):
                    return results

    # Tables often have: "Производительность, м3/ч 40" or "Подача м3/ч 40".
    for char_pattern, char_name, unit in CHAR_WITH_UNIT:
        pattern = rf"({char_pattern})\s*[:;\-–—]?\s*({NUM})"
        for match in re.finditer(pattern, normalized_text, flags=re.IGNORECASE):
            if _add(results, char_name, match.group(2), unit, max_items):
                return results

    # Reverse order: "40 м3/ч производительность" within a short fragment.
    reverse_patterns = [
        (rf"({NUM})\s*(м3/ч|м³/ч|куб\.?\s*м/ч)[^.;]{{0,45}}(производительность|подача|расход)", "Производительность"),
        (rf"({NUM})\s*(м)[^.;]{{0,35}}(напор)", "Напор"),
        (rf"({NUM})\s*(кВт|квт)[^.;]{{0,45}}(мощность)", "Мощность"),
        (rf"({NUM})\s*(кг)[^.;]{{0,35}}(масса|вес)", "Масса"),
    ]
    for pattern, char_name in reverse_patterns:
        for match in re.finditer(pattern, normalized_text, flags=re.IGNORECASE):
            if _add(results, char_name, match.group(1), match.group(2), max_items):
                return results

    text_patterns = [
        (r"(степень защиты)\s*[:\-–—]?\s*(IP\s*\d{2})", "Степень защиты"),
        (r"(класс защиты)\s*[:\-–—]?\s*([А-Яа-яA-Za-z0-9 ,\-]{1,30})", "Класс защиты"),
        (r"(материал)\s*[:\-–—]?\s*([А-Яа-яA-Za-z0-9 ,\-]{3,80})", "Материал"),
    ]
    for pattern, name in text_patterns:
        for match in re.finditer(pattern, normalized_text, flags=re.IGNORECASE):
            value = clean_text(match.group(2))
            item = {"characteristic": name, "value": value, "unit": ""}
            if item not in results:
                results.append(item)
            if len(results) >= max_items:
                return results

    return results
