import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import requests

JINA_SEARCH_URL = "https://s.jina.ai/?q={query}"
TIMEOUT = 40

@dataclass
class Source:
    title: str
    url: str
    snippet: str
    text: str


def _headers(jina_api_key: Optional[str] = None) -> Dict[str, str]:
    headers = {"User-Agent": "equipment-ai-search/1.0"}
    if jina_api_key:
        headers["Authorization"] = f"Bearer {jina_api_key}"
    return headers


def build_queries(class_name: str, subclass_name: str, model_code: str) -> List[str]:
    base = f"{class_name} {subclass_name} {model_code}".strip()
    return [
        f"{base} характеристики",
        f"{model_code} технические характеристики",
        f"{model_code} паспорт",
        f"{model_code} производительность мощность масса",
    ]


def jina_search(query: str, jina_api_key: Optional[str] = None) -> str:
    url = JINA_SEARCH_URL.format(query=quote_plus(query))
    response = requests.get(url, headers=_headers(jina_api_key), timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def parse_jina_results(raw_text: str, query: str) -> List[Source]:
    if not raw_text.strip():
        return []

    # Jina обычно возвращает блоки с URL Source или URL. Парсер устойчив к изменениям формата.
    chunks = re.split(r"\n(?=Title:|\[\d+\]|URL Source:|URL:)", raw_text)
    sources: List[Source] = []
    seen = set()

    for chunk in chunks:
        text = chunk.strip()
        if not text:
            continue

        url_match = re.search(r"(?:URL Source|URL):\s*(https?://\S+)", text)
        title_match = re.search(r"(?:Title:\s*|^\[\d+\]\s*)(.+)", text, flags=re.MULTILINE)

        url = url_match.group(1).strip().rstrip(")].,") if url_match else ""
        title = title_match.group(1).strip() if title_match else "Источник из Jina Search"

        if url and url in seen:
            continue
        if url:
            seen.add(url)

        clean_text = re.sub(r"\n{3,}", "\n\n", text)
        snippet = clean_text[:700]
        if url or len(clean_text) > 100:
            sources.append(Source(title=title[:160], url=url, snippet=snippet, text=clean_text))

    if not sources:
        # Резерв: анализируем весь ответ как один источник.
        sources.append(Source(
            title="Jina Search results",
            url=JINA_SEARCH_URL.format(query=quote_plus(query)),
            snippet=raw_text[:700],
            text=raw_text,
        ))

    return sources


def collect_sources(
    class_name: str,
    subclass_name: str,
    model_code: str,
    max_sources: int = 10,
    manual_urls: Optional[List[str]] = None,
    jina_api_key: Optional[str] = None,
) -> List[Source]:
    sources: List[Source] = []
    seen_urls = set()

    for query in build_queries(class_name, subclass_name, model_code):
        if len(sources) >= max_sources:
            break
        try:
            raw = jina_search(query, jina_api_key=jina_api_key)
            for src in parse_jina_results(raw, query):
                key = src.url or src.title + src.text[:40]
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                sources.append(src)
                if len(sources) >= max_sources:
                    break
        except Exception as exc:
            sources.append(Source(
                title=f"Ошибка Jina Search по запросу: {query}",
                url="",
                snippet=str(exc),
                text="",
            ))

    for url in manual_urls or []:
        if len(sources) >= max_sources:
            break
        url = url.strip()
        if not url or url in seen_urls:
            continue
        try:
            reader_url = "https://r.jina.ai/" + url
            response = requests.get(reader_url, headers=_headers(jina_api_key), timeout=TIMEOUT)
            response.raise_for_status()
            text = response.text
            title_match = re.search(r"Title:\s*(.+)", text)
            title = title_match.group(1).strip() if title_match else url
            sources.append(Source(title=title[:160], url=url, snippet=text[:700], text=text))
            seen_urls.add(url)
        except Exception as exc:
            sources.append(Source(title=url, url=url, snippet=f"Не удалось прочитать ссылку: {exc}", text=""))

    return [s for s in sources if s.text or s.snippet]
