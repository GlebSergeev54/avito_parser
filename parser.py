import logging
import random
import re
import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from utils import extract_avito_id_from_url, normalize_text


logger = logging.getLogger(__name__)


def _clean(value: str | None) -> str | None:
    """Нормализует текст и превращает пустые строки в None, т к
    NULL - отсутствие данных в ячейке БД
    None - пустая строка
    Чтобы не было ошибок
    """
    if value is None:
        return None
    value = normalize_text(value)
    return value if value else None

def _safe_inner_text(page: Page, selector: str, timeout: int = 2000) -> str | None:
    """
    Безопасно получает visible text элемента (inner_text)
    """
    try:
        locator = page.locator(selector).first
        if locator.count() == 0:
            return None
        locator.wait_for(state="attached", timeout=timeout)
        text = locator.inner_text(timeout=timeout)
        return _clean(text)
    except PlaywrightTimeoutError:
        return None
    except Exception:
        return None

def _safe_text_content(page: Page, selector: str, timeout: int = 2000) -> str | None:
    """
    безопасно получает text_content элемента
    """
    try:
        locator = page.locator(selector).first
        if locator.count() == 0:
            return None
        locator.wait_for(state="attached", timeout=timeout)
        text = locator.text_content(timeout=timeout)
        return _clean(text)
    except PlaywrightTimeoutError:
        return None
    except Exception:
        return None


def _safe_attr(page: Page, selector: str, attr: str, timeout: int = 2000) -> str | None:
    """Безопасно получает значение атрибута элемента"""
    try:
        locator = page.locator(selector).first
        if locator.count() == 0:
            return None
        locator.wait_for(state="attached", timeout=timeout)
        value = locator.get_attribute(attr, timeout=timeout)
        return _clean(value)
    except PlaywrightTimeoutError:
        return None
    except Exception:
        return None


def get_first_text(page: Page, selectors: list[str], timeout: int = 2500) -> str | None:
    """
    Пробует несколько селекторов подряд
    Сначала inner_text, потом text_content
    Возвращает первый непустой текст, на случай изменения верстки авито
    """
    for selector in selectors:
        text = _safe_inner_text(page, selector, timeout=timeout)
        if text:
            return text

        text = _safe_text_content(page, selector, timeout=timeout)
        if text:
            return text

    return None


def _extract_price_value(price_text: str | None, meta_price: str | None) -> int | None:
    """
    Возвращает числовую цену
    Приоритет: meta[itemprop='price'] - тег html,
    иначе извлекаем число из price_text
    """
    if meta_price:
        try:
            return int(meta_price)
        except Exception:
            pass

    if not price_text:
        return None

    if "бесплатно" in price_text.lower():
        return 0

    digits = re.sub(r"[^\d]", "", price_text)
    if not digits:
        return None

    try:
        return int(digits)
    except Exception:
        return None


def is_closed_ad(page: Page) -> bool:
    """
    Проверяет, закрыто ли объявление
    """
    try:
        page_text = normalize_text(page.locator("body").inner_text())
    except Exception:
        page_text = None

    if not page_text:
        return False

    page_text_lower = page_text.lower()

    closed_markers = [
        "объявление снято с публикации",
        "объявление не найдено",
        "страница не найдена",
        "такого объявления нет",
        "объявление закрыто",
        "снято с публикации",
        "объявление удалено",
        "товар продан",
    ]

    return any(marker in page_text_lower for marker in closed_markers)


def parse_ad_page(page: Page, query_text: str, url: str) -> dict | None:
    """
    Универсальный парсер объявления Avito

    Возвращает поля:
    - avito_id
    - title
    - price
    - address
    - description
    - published_at
    - views_count
    - url
    - status

    Дополнительно:
    - query_text
    - price_value
    - currency
    """
    avito_id = extract_avito_id_from_url(url)

    # Небольшая случайная пауза перед чтением DOM
    time.sleep(random.uniform(0.3, 0.8))

    # Закрытое объявление
    if is_closed_ad(page):
        return {
            "avito_id": avito_id,
            "query_text": query_text,
            "title": None,
            "price": None,
            "price_value": None,
            "currency": None,
            "address": None,
            "description": None,
            "published_at": None,
            "views_count": None,
            "url": url,
            "status": "closed",
        }

    # Название
    title = get_first_text(page, [
        "[data-marker='item-view/title-info']",
        "h1[itemprop='name']",
        "h1",
    ])

    if not title:
        logger.debug("Не удалось получить title у объявления: %s", url)
        return None

    # Цена
    price_text = get_first_text(page, [
        "#bx_item-price-value",
        "[data-marker='item-view/item-price-container'] span",
        "span:has-text('Бесплатно')",
        "span:has-text('₽')",
        "span:has-text('$')",
        "span:has-text('€')",
    ])

    meta_price = _safe_attr(page, "meta[itemprop='price']", "content")
    currency = _safe_attr(page, "meta[itemprop='priceCurrency']", "content")
    price_value = _extract_price_value(price_text, meta_price)

    # Адрес
    address = get_first_text(page, [
        "[itemprop='address']",
        "div[itemprop='address']",
        "[data-marker='item-view/item-address']",
        "[data-marker='item-view/address']",
    ])

    # Описание
    description = get_first_text(page, [
        "[data-marker='item-view/item-description']",
        "[itemprop='description']",
        "[data-marker='item-view/item-description-text']",
    ])

    # Дата публикации
    published_at = get_first_text(page, [
        "[data-marker='item-view/item-date']",
        "span:has-text('Сегодня')",
        "span:has-text('Вчера')",
    ])

    # Количество просмотров
    views_count = get_first_text(page, [
        "[data-marker='item-view/total-views']",
        "[data-marker='item-view/item-views']",
        "span:has-text('просмотров')",
        "span:has-text('просмотр')",
    ])

    ad_data = {
        "avito_id": avito_id,
        "query_text": query_text,
        "title": title,
        "price": price_text,
        "price_value": price_value,
        "currency": currency or "RUB",
        "address": address,
        "description": description,
        "published_at": published_at,
        "views_count": views_count,
        "url": url,
        "status": "active",
    }

    return ad_data