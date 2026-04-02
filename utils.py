import re
from datetime import datetime
from urllib.parse import quote_plus


def now_iso() -> str:
    """Текущее время в ISO-формате."""
    return datetime.now().isoformat(timespec="seconds")


def normalize_text(value: str | None) -> str | None:
    """Мягкая нормализация текста."""
    if value is None:
        return None
    value = value.replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned if cleaned else None


def extract_avito_id_from_url(url: str | None) -> str | None:
    """Извлекает avito_id из URL."""
    if not url:
        return None
    match = re.search(r"_(\d+)(?:\?|$)", url)
    if match:
        return match.group(1)
    return None


def build_search_url(query: str) -> str:
    """Формирует URL поиска Avito."""
    encoded_query = quote_plus(query)
    return f"https://www.avito.ru/all?q={encoded_query}"


def normalize_for_compare(value: str | None) -> str:
    """Нормализация для сравнения полей в кеше."""
    normalized = normalize_text(value)
    return normalized if normalized is not None else ""


def safe_filename(value: str) -> str:
    """Безопасное имя файла."""
    value = re.sub(r'[\\/*?:"<>|]', "_", value)
    value = re.sub(r"\s+", "_", value).strip("_")
    return value or "avito_export"


def normalize_href(href: str | None) -> str | None:
    """Нормализует URL."""
    if not href:
        return None

    href = href.strip()
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return None

    if href.startswith("/"):
        href = f"https://www.avito.ru{href}"

    return href


def is_ad_url(url: str) -> bool:
    """Проверяет, является ли URL ссылкой на объявление."""
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