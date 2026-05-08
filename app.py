import html
import re
from typing import List

import pandas as pd
import streamlit as st

from utils.export import dataframe_to_xlsx_bytes
from utils.llm_extract import DEFAULT_MODELS, extract_characteristics
from utils.search_jina import Source, collect_sources

st.set_page_config(page_title="Поиск характеристик оборудования", layout="wide")

CUSTOM_CSS = """
<style>
.stApp { background: linear-gradient(135deg, #eaf7ff 0%, #d8efff 50%, #cfe4ff 100%); color: #0b2f5b; }
html, body, [class*="css"], [data-testid="stMarkdownContainer"], label, p, span, div { color: #0b2f5b !important; }
section[data-testid="stSidebar"] { background: #d7ecff !important; border-right: 1px solid #a9ccec; }
.stTextInput input, .stTextArea textarea, div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {
    background-color: #f6fbff !important; color: #0b2f5b !important; border: 1px solid #8dbce6 !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder { color: #416b96 !important; }
.stButton button, .stDownloadButton button {
    background-color: #f3aaaa !important; color: #462121 !important; border: 1px solid #d98888 !important;
    border-radius: 9px !important; font-weight: 700 !important;
}
.stButton button:hover, .stDownloadButton button:hover { background-color: #ee9999 !important; color: #321515 !important; }
[data-testid="stDataFrame"] { background: #f3eaff !important; }
a { color: #083d77 !important; font-weight: 700; }
.small-title { font-size: 1.75rem; line-height: 1.2; font-weight: 800; margin-bottom: 1rem; }
.result-table-wrap { overflow-x: auto; margin-top: .35rem; border-radius: 12px; border: 1px solid #c6afea; }
table.result-table { width: 100%; border-collapse: collapse; background: #f3eaff; color: #101f3f; font-size: 13px; line-height: 1.25; }
table.result-table th { background: #dfccff; color: #101f3f; font-weight: 800; text-align: center; padding: 7px 8px; border: 1px solid #c6afea; vertical-align: middle; }
table.result-table td { background: #f6efff; color: #101f3f; padding: 6px 8px; border: 1px solid #d7c5f2; vertical-align: middle; text-align: left; }
table.result-table tr:nth-child(even) td { background: #efe4ff; }
table.result-table td:nth-child(1), table.result-table td:nth-child(2), table.result-table td:nth-child(3), table.result-table td:nth-child(5), table.result-table td:nth-child(6) { text-align: center; }
table.result-table a { color: #083d77 !important; font-weight: 800; text-decoration: underline; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.markdown('<div class="small-title">Поиск характеристик моделей оборудования</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Настройки")
    model_label = st.selectbox("Нейросеть для извлечения характеристик", list(DEFAULT_MODELS.keys()), index=0)
    custom_model = st.text_input("Своя модель Hugging Face, необязательно", value="")
    max_sources = st.slider("Количество источников для анализа", min_value=1, max_value=20, value=5, step=1)
    use_regex_without_hf = st.checkbox("Разрешить резервное извлечение без HF_TOKEN", value=True)
    st.caption("Jina Search может работать без ключа с ограничениями. Hugging Face token нужен для ИИ-извлечения; без него включается резервный парсер.")

class_name = st.text_input("Класс", value="", placeholder="Например: Насосы")
subclass_name = st.text_input("Подкласс", value="", placeholder="Например: Погружные")
model_code = st.text_input("Код модели", value="", placeholder="Например: ГНОМ 40-25")
manual_links_text = st.text_area(
    "Дополнительные ссылки для анализа, необязательно",
    value="",
    placeholder="Вставьте прямые ссылки на страницы с характеристиками, по одной ссылке на строку",
    height=90,
)

run = st.button("Найти характеристики")


def source_link(title: str, url: str) -> str:
    safe_title = html.escape(title or url or "Источник")
    safe_url = html.escape(url or "")
    if safe_url:
        return f'<a href="{safe_url}" target="_blank">{safe_title}</a>'
    return safe_title


def normalize_characteristic_name(value: str) -> str:
    text = (value or "").strip().lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^а-яa-z0-9 %/.,+-]+", "", text)
    return text


if run:
    if not class_name.strip() or not subclass_name.strip() or not model_code.strip():
        st.error("Заполните Класс, Подкласс и Код модели.")
        st.stop()

    hf_token = st.secrets.get("HF_TOKEN", "") if hasattr(st, "secrets") else ""
    jina_api_key = st.secrets.get("JINA_API_KEY", "") if hasattr(st, "secrets") else ""
    selected_model = custom_model.strip() or DEFAULT_MODELS[model_label]
    manual_urls: List[str] = [line.strip() for line in manual_links_text.splitlines() if line.strip()]

    if not hf_token and not use_regex_without_hf:
        st.error("Не указан HF_TOKEN. Добавьте его в Streamlit Secrets или включите резервное извлечение без HF_TOKEN.")
        st.stop()

    with st.spinner("Ищу источники через Jina Search/Reader..."):
        sources = collect_sources(
            class_name=class_name,
            subclass_name=subclass_name,
            model_code=model_code,
            max_sources=max_sources,
            manual_urls=manual_urls,
            jina_api_key=jina_api_key or None,
        )

    valid_sources = [s for s in sources if s.text or s.snippet]
    if not valid_sources:
        st.error("Не удалось получить источники. Попробуйте добавить прямые ссылки в поле дополнительных ссылок.")
        st.stop()

    rows = []
    progress = st.progress(0)
    with st.spinner("Извлекаю характеристики..."):
        for idx, src in enumerate(valid_sources):
            source_text = src.text or src.snippet
            items = extract_characteristics(
                class_name=class_name,
                subclass_name=subclass_name,
                model_code=model_code,
                source_text=source_text,
                model=selected_model,
                hf_token=hf_token or None,
            )
            for item in items:
                rows.append({
                    "Класс": class_name,
                    "Подкласс": subclass_name,
                    "Код модели": model_code,
                    "Характеристика": item.get("characteristic", ""),
                    "Значение": item.get("value", ""),
                    "Ед. изм.": item.get("unit", ""),
                    "Источник": source_link(src.title, src.url),
                    "Источник для экспорта": f"{src.title} - {src.url}" if src.url else src.title,
                })
            progress.progress((idx + 1) / max(len(valid_sources), 1))

    if not rows:
        st.warning("Источники найдены, но характеристики не извлечены. Попробуйте добавить прямую ссылку на страницу производителя или выбрать другую модель Hugging Face.")
        st.stop()

    df = pd.DataFrame(rows)
    df["_Характеристика_norm"] = df["Характеристика"].map(normalize_characteristic_name)
    df = df[df["_Характеристика_norm"].astype(bool)]
    df = df.drop_duplicates(subset=["Класс", "Подкласс", "Код модели", "_Характеристика_norm"], keep="first")
    display_df = df[["Класс", "Подкласс", "Код модели", "Характеристика", "Значение", "Ед. изм.", "Источник"]]
    export_df = df[["Класс", "Подкласс", "Код модели", "Характеристика", "Значение", "Ед. изм.", "Источник для экспорта"]].rename(columns={"Источник для экспорта": "Источник"})

    st.subheader("Итоговая таблица")
    table_html = display_df.to_html(escape=False, index=False, classes="result-table", border=0)
    st.markdown(f'<div class="result-table-wrap">{table_html}</div>', unsafe_allow_html=True)

    csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
    xlsx_bytes = dataframe_to_xlsx_bytes(export_df)
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("Скачать CSV", data=csv_bytes, file_name="equipment_characteristics.csv", mime="text/csv")
    with col2:
        st.download_button("Скачать XLSX", data=xlsx_bytes, file_name="equipment_characteristics.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.info("Введите класс, подкласс и код модели, затем нажмите «Найти характеристики».")
