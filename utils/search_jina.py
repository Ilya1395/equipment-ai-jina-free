import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import requests

from .text_utils import clean_text, fix_mojibake

JINA_SEARCH_URL = "https://s.jina.ai/?q={query}"
JINA_READER_PREFIX = "https://r.jina.ai/"
TIMEOUT = 60
REQUEST_DELAY_SECONDS = 1.2

@dataclass
class Source:
    title: str
    url: str
    snippet: str
    text: str


def _headers(jina_api_key: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": "equipment-ai-search/1.2",
        "Accept": "text/plain; charset=utf-8",
    }
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
        f"{model_code} насос характеристики",
    ]


def _response_text(response: requests.Response) -> str:
    # Jina sometimes returns UTF-8 text but requests may infer ISO-8859-1.
    response.encoding = "utf-8"
    text = response.text
    if "Ð" in text or "Ñ" in text or "�" in text:
        try:
            text = response.content.decode("utf-8", errors="replace")
        except Exception:
            pass
    return clean_text(text)


def jina_search(query: str, jina_api_key: Optional[str] = None) -> str:
    url = JINA_SEARCH_URL.format(query=quote_plus(query))
    response = requests.get(url, headers=_headers(jina_api_key), timeout=TIMEOUT)
    response.raise_for_status()
    return _response_text(response)


def read_url_with_jina(url: str, jina_api_key: Optional[str] = None) -> str:
    if not url:
        return ""
    reader_url = JINA_READER_PREFIX + url
    response = requests.get(reader_url, headers=_headers(jina_api_key), timeout=TIMEOUT)
    response.raise_for_status()
    return _response_text(response)


def _extract_field(patterns: List[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return clean_text(match.group(1)).strip(" -–—")
    return ""


def parse_jina_results(raw_text: str, query: str) -> List[Source]:
    raw_text = clean_text(raw_text)
    if not raw_text:
        return []

    # Typical Jina formats include repeated blocks with Title, URL Source/URL and content.
    split_pattern = r"(?=\n?\s*(?:\[\d+\]\s*)?Title\s*:|\n?\s*(?:\[\d+\]\s*)?URL Source\s*:|\n?\s*(?:\[\d+\]\s*)?URL\s*:|\n?\s*\[\d+\]\s+)"
    chunks = [c.strip() for c in re.split(split_pattern, raw_text) if c.strip()]

    sources: List[Source] = []
    seen = set()

    # First pass: parse blocks.
    for chunk in chunks:
        chunk = clean_text(chunk)
        title = _extract_field([
            r"(?:^|\n)\s*(?:\[\d+\]\s*)?Title\s*:\s*(.+)",
            r"^\s*\[\d+\]\s*(.+)",
        ], chunk)
        url = _extract_field([
            r"(?:^|\n)\s*(?:\[\d+\]\s*)?URL Source\s*:\s*(https?://\S+)",
            r"(?:^|\n)\s*(?:\[\d+\]\s*)?URL\s*:\s*(https?://\S+)",
        ], chunk)
        if not url:
            url_match = re.search(r"https?://[^\s\]\)>,]+", chunk)
            url = url_match.group(0).strip().rstrip(".,);]") if url_match else ""

        # Remove service lines; use remaining content as snippet.
        snippet = re.sub(r"(?:^|\n)\s*(?:\[\d+\]\s*)?(Title|URL Source|URL)\s*:.+", "\n", chunk, flags=re.IGNORECASE)
        snippet = clean_text(snippet)[:1200]
        if not title:
            title = url or "Источник Jina Search"

        key = url or (title + snippet[:80])
        if key in seen:
            continue
        if url or len(snippet) > 40 or "Title:" in chunk:
            seen.add(key)
            sources.append(Source(title=title[:220], url=url, snippet=snippet or chunk[:1200], text=chunk))

    # Second pass: collect title/url pairs from whole response if chunking failed.
    if not any(s.url for s in sources):
        titles = re.findall(r"(?:^|\n)\s*(?:\[\d+\]\s*)?Title\s*:\s*(.+)", raw_text, flags=re.IGNORECASE)
        urls = re.findall(r"(?:^|\n)\s*(?:\[\d+\]\s*)?(?:URL Source|URL)\s*:\s*(https?://\S+)", raw_text, flags=re.IGNORECASE)
        for idx, url in enumerate(urls):
            url = url.strip().rstrip(".,);]")
            title = clean_text(titles[idx]) if idx < len(titles) else url
            if url not in seen:
                seen.add(url)
                sources.append(Source(title=title[:220], url=url, snippet=raw_text[:1200], text=raw_text))

    if not sources:
        sources.append(Source(
            title="Jina Search results",
            url=JINA_SEARCH_URL.format(query=quote_plus(query)),
            snippet=raw_text[:1200],
            text=raw_text,
        ))

    return sources


def _merge_source_with_reader(src: Source, jina_api_key: Optional[str] = None) -> Source:
    title = fix_mojibake(src.title)
    snippet = clean_text(src.snippet)
    text_parts = [clean_text(src.text), snippet]

    if src.url:
        try:
            time.sleep(REQUEST_DELAY_SECONDS)
            reader_text = read_url_with_jina(src.url, jina_api_key=jina_api_key)
            if reader_text:
                text_parts.insert(0, reader_text)
                reader_title = _extract_field([r"(?:^|\n)\s*Title\s*:\s*(.+)"], reader_text)
                if reader_title:
                    title = reader_title
        except Exception as exc:
            text_parts.append(f"Не удалось прочитать страницу через Jina Reader: {exc}")

    merged_text = clean_text("\n\n".join([p for p in text_parts if p]))
    if not title:
        title = src.url or "Источник"
    return Source(title=title[:220], url=src.url, snippet=snippet or merged_text[:1200], text=merged_text)


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
                key = src.url or src.title + src.text[:80]
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                enriched = _merge_source_with_reader(src, jina_api_key=jina_api_key)
                sources.append(enriched)
                if len(sources) >= max_sources:
                    break
        except Exception as exc:
            # Keep a diagnostic source but do not count it as a usable web source later.
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
            time.sleep(REQUEST_DELAY_SECONDS)
            text = read_url_with_jina(url, jina_api_key=jina_api_key)
            title = _extract_field([r"(?:^|\n)\s*Title\s*:\s*(.+)"], text) or url
            sources.append(Source(title=title[:220], url=url, snippet=text[:1200], text=text))
            seen_urls.add(url)
        except Exception as exc:
            sources.append(Source(title=url, url=url, snippet=f"Не удалось прочитать ссылку: {exc}", text=""))

    return [s for s in sources if s.text or s.snippet]
