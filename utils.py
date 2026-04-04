# вспомогательные утилиты 

import re
from datetime import datetime
from urllib.parse import quote_plus

#возвращает время
def now_iso() -> str: 
    return datetime.now().isoformat(timespec="seconds")

# нормализация текста, убираем лишние пробелы
def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None #пустая строка
    value = value.replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned if cleaned else None

 # извлекает id из URL
def extract_avito_id_from_url(url: str | None) -> str | None:
    if not url:
        return None 
    match = re.search(r"_(\d+)(?:\?|$)", url)
    if match:
        return match.group(1)
    return None

# формирует URL для поиска на Avito
def build_search_url(query: str) -> str:
    encoded_query = quote_plus(query)
    return f"https://www.avito.ru/all?q={encoded_query}"

 # возвращает пустую строку после нормализации
def normalize_for_compare(value: str | None) -> str:
    normalized = normalize_text(value)
    return normalized if normalized is not None else ""

# строка -> допустимое имя файла
def safe_filename(value: str) -> str:
    value = re.sub(r'[\\/*?:"<>|]', "_", value)
    value = re.sub(r"\s+", "_", value).strip("_")
    return value or "avito_export"

# нормализует URL-ссылку из атрибута href
def normalize_href(href: str | None) -> str | None:
    if not href:
        return None

    href = href.strip()
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return None

    if href.startswith("/"):
        href = f"https://www.avito.ru{href}"

    return href

#  проверяет, является ли URL ссылкой на объявление
def is_ad_url(url: str) -> bool:
    if not url:
        return False

    url = url.strip().lower()

    if "avito.ru" not in url:
        return False

    skip_parts = [
        "/profile/", "/brands/", "/favorites", "/support",
        "/help", "/apps", "/business", "/rossiya",
        "/items/", "/services/", "/about", "/safety",
        "/delivery", "/pro/", "/account", "/#",
    ]
    if any(part in url for part in skip_parts):
        return False

    return re.search(r"_(\d+)(?:\?|$)", url) is not None