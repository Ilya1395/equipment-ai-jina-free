import json
import re
from typing import Dict, List, Optional

import requests

from .normalize import normalize_characteristic, normalize_unit, split_value_unit
from .regex_extract import extract_by_regex

HF_API_URL = "https://api-inference.huggingface.co/models/{model}"
DEFAULT_MODELS = {
    "Qwen 2.5 7B Instruct": "Qwen/Qwen2.5-7B-Instruct",
    "Mistral 7B Instruct v0.3": "mistralai/Mistral-7B-Instruct-v0.3",
    "Zephyr 7B Beta": "HuggingFaceH4/zephyr-7b-beta",
    "Phi-3 Mini 4K Instruct": "microsoft/Phi-3-mini-4k-instruct",
}


def _build_prompt(class_name: str, subclass_name: str, model_code: str, source_text: str) -> str:
    source_text = source_text[:12000]
    return f"""
Ты извлекаешь технические характеристики оборудования из текста источника.

Дано:
Класс: {class_name}
Подкласс: {subclass_name}
Код модели: {model_code}

Правила:
1. Извлекай только характеристики, значения и единицы измерения, которые прямо указаны в тексте.
2. Не придумывай значения.
3. Если значение или единица измерения не найдены, не добавляй строку, кроме текстовых характеристик вроде материала или IP.
4. Ответ верни только JSON-массивом без пояснений.
5. Формат каждого объекта:
{{"characteristic":"Название характеристики","value":"Значение","unit":"Ед. изм."}}

Текст источника:
{source_text}
""".strip()


def _extract_json(text: str) -> List[Dict[str, str]]:
    if not text:
        return []
    match = re.search(r"\[\s*\{.*?\}\s*\]", text, flags=re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    cleaned = []
    for item in data:
        if not isinstance(item, dict):
            continue
        characteristic = normalize_characteristic(str(item.get("characteristic", "")).strip())
        value = str(item.get("value", "")).strip()
        unit = normalize_unit(str(item.get("unit", "")).strip())
        if value and not unit:
            value2, unit2 = split_value_unit(value)
            value, unit = value2, unit2
        if characteristic and value:
            cleaned.append({"characteristic": characteristic, "value": value, "unit": unit})
    return cleaned


def call_huggingface(prompt: str, model: str, hf_token: str) -> str:
    headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}
    payload = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": 900, "temperature": 0.1, "return_full_text": False},
        "options": {"wait_for_model": True},
    }
    response = requests.post(HF_API_URL.format(model=model), headers=headers, json=payload, timeout=80)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first.get("generated_text", "") or first.get("summary_text", "") or json.dumps(data, ensure_ascii=False)
    if isinstance(data, dict):
        return data.get("generated_text", "") or json.dumps(data, ensure_ascii=False)
    return str(data)


def extract_characteristics(
    class_name: str,
    subclass_name: str,
    model_code: str,
    source_text: str,
    model: str,
    hf_token: Optional[str] = None,
) -> List[Dict[str, str]]:
    # Сначала быстрый строгий парсер: он не требует токена и дает стабильный резерв.
    regex_items = extract_by_regex(source_text)

    if not hf_token:
        return regex_items

    try:
        prompt = _build_prompt(class_name, subclass_name, model_code, source_text)
        llm_text = call_huggingface(prompt, model=model, hf_token=hf_token)
        llm_items = _extract_json(llm_text)
    except Exception:
        llm_items = []

    merged = []
    seen = set()
    for item in llm_items + regex_items:
        key = (item.get("characteristic", "").lower(), item.get("value", ""), item.get("unit", ""))
        if key not in seen and item.get("characteristic") and item.get("value"):
            seen.add(key)
            merged.append(item)
    return merged
