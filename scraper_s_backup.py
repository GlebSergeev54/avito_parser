import logging
import re
from typing import Iterator

from playwright_stealth import stealth_sync
from playwright.sync_api import (
    BrowserContext,
    Page,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from config import (
    CARD_OPEN_RETRIES,
    DEFAULT_HEADLESS,
    DELAY_BETWEEN_CARDS_SEC,
    DELAY_BETWEEN_PAGES_SEC,
    DELAY_BETWEEN_RETRIES_SEC,
    MAX_ALL_PAGES,
    NAVIGATION_TIMEOUT_MS,
    PAGE_TIMEOUT_MS,
)
from parser import parse_ad_page
from utils import build_search_url

logger = logging.getLogger(__name__)


def apply_humanization(page: Page) -> None:
    """
    Пока оставляем только stealth + небольшие паузы.
    """
    try:
        stealth_sync(page)
        page.set_viewport_size({"width": 1280, "height": 720})
        logger.debug("Stealth применён к странице")
    except Exception as e:
        logger.warning("Ошибка при применении stealth: %s", e)


def is_ad_url(url: str) -> bool:
    if not url:
        return False

    if url.startswith("/"):
        url = f"https://www.avito.ru{url}"

    if "avito.ru" not in url:
        return False

    skip_parts = [
        "/profile/",
        "/brands/",
        "/favorites",
        "/support",
        "/help",
        "/apps",
        "/business",
        "/rossiya",
        "/items/",
        "/services/",
        "/about",
        "/safety",
        "/delivery",
        "/pro/",
        "/account",
        "/#",
    ]
    if any(part in url for part in skip_parts):
        return False

    return re.search(r"_(\d+)(?:\?|$)", url) is not None


def normalize_href(href: str | None) -> str | None:
    if not href:
        return None

    href = href.strip()
    if not href:
        return None

    if href.startswith("/"):
        href = f"https://www.avito.ru{href}"

    return href


def collect_listing_urls(page: Page) -> list[str]:
    hrefs: list[str] = []

    locators = page.locator("a").all()
    for locator in locators:
        try:
            href = normalize_href(locator.get_attribute("href"))
            if not href:
                continue

            if is_ad_url(href):
                hrefs.append(href)
        except Exception:
            continue

    return list(dict.fromkeys(hrefs))


def block_app_pages(route: Route) -> None:
    url = route.request.url.lower()

    blocked_markers = [
        "avito.ru/apps",
        "utm_campaign=avito_banner",
        "utm_source=avito_banner",
        "utm_medium=referral",
    ]

    if any(marker in url for marker in blocked_markers):
        logger.info("Блокируем app/banner request: %s", route.request.url)
        route.abort()
        return

    route.continue_()


def close_unexpected_pages(context: BrowserContext, main_page: Page) -> None:
    for p in context.pages:
        if p == main_page:
            continue
        try:
            logger.info("Закрываем лишнюю вкладку: %s", p.url)
            p.close()
        except Exception:
            continue


def dismiss_app_banner(page: Page) -> None:
    close_selectors = [
        "button[aria-label='Закрыть']",
        "button[aria-label='close']",
        "button:has-text('Закрыть')",
        "button:has-text('×')",
        "button:has-text('✕')",
        "button:has-text('✖')",
    ]

    for selector in close_selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible():
                locator.click(timeout=1000)
                logger.info("Закрыли баннер через selector: %s", selector)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue

    try:
        page.evaluate(
            """
            () => {
                const nodes = [...document.querySelectorAll('*')];
                for (const el of nodes) {
                    const text = (el.innerText || '').toLowerCase();
                    if (
                        text.includes('как дальше пользоваться авито на ios') ||
                        text.includes('приложение авито') ||
                        text.includes('скачать авито')
                    ) {
                        const block = el.closest('div');
                        if (block) block.remove();
                    }
                }
            }
            """
        )
    except Exception:
        pass


def safe_open_search_page(page: Page, url: str, context: BrowserContext) -> None:
    logger.info("Открываем страницу поиска: %s", url)
    apply_humanization(page)
    page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
    page.wait_for_timeout(2500)
    close_unexpected_pages(context, page)
    dismiss_app_banner(page)


def open_card_with_retries(page: Page, url: str, retries: int) -> bool:
    for attempt in range(1, retries + 1):
        try:
            logger.info("Открытие карточки: %s (попытка %s/%s)", url, attempt, retries)
            apply_humanization(page)

            page.wait_for_timeout(500)
            page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            page.wait_for_timeout(1500)

            try:
                page.evaluate("window.scrollBy(0, 150)")
            except Exception:
                pass

            return True

        except PlaywrightTimeoutError:
            logger.warning("Timeout при открытии карточки: %s", url)
        except Exception as exc:
            logger.warning("Ошибка при открытии карточки %s: %s", url, exc)

        if attempt < retries:
            page.wait_for_timeout(int((DELAY_BETWEEN_RETRIES_SEC + 0.5) * 1000))

    return False


def get_next_page_url(search_url: str, next_page_number: int) -> str:
    if re.search(r"([?&])p=\d+", search_url):
        return re.sub(r"([?&])p=\d+", rf"\1p={next_page_number}", search_url)

    separator = "&" if "?" in search_url else "?"
    return f"{search_url}{separator}p={next_page_number}"


def iterate_ads(
    query_text: str,
    pages: int | None = None,
    all_pages: bool = False,
    headless: bool | None = None,
) -> Iterator[dict]:
    if headless is None:
        headless = DEFAULT_HEADLESS

    search_url = build_search_url(query_text)
    seen_urls: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )

        context.route("**/*", block_app_pages)

        main_page = context.new_page()
        main_page.set_default_timeout(PAGE_TIMEOUT_MS)

        try:
            safe_open_search_page(main_page, search_url, context)

            max_pages = MAX_ALL_PAGES if all_pages else (pages or 1)
            current_page_number = 1
            current_page_url = search_url

            while current_page_number <= max_pages:
                logger.info("Обрабатываем страницу поиска #%s", current_page_number)

                close_unexpected_pages(context, main_page)
                dismiss_app_banner(main_page)

                listing_urls = collect_listing_urls(main_page)
                logger.info("Найдено ссылок-кандидатов: %s", len(listing_urls))

                if not listing_urls:
                    logger.warning(
                        "На странице #%s не найдено ссылок на объявления. Останавливаемся.",
                        current_page_number,
                    )
                    break

                for url in listing_urls:
                    if url in seen_urls:
                        continue

                    seen_urls.add(url)

                    card_page = context.new_page()
                    card_page.set_default_timeout(PAGE_TIMEOUT_MS)

                    try:
                        opened = open_card_with_retries(card_page, url, CARD_OPEN_RETRIES)
                        if not opened:
                            logger.warning("Не удалось открыть карточку после retry: %s", url)
                            continue

                        ad_data = parse_ad_page(card_page, query_text, url)
                        if ad_data is not None:
                            yield ad_data

                        card_page.wait_for_timeout(int((DELAY_BETWEEN_CARDS_SEC + 0.3) * 1000))
                    finally:
                        try:
                            card_page.close()
                        except Exception:
                            pass

                if not all_pages and current_page_number >= max_pages:
                    break

                next_page_number = current_page_number + 1
                next_page_url = get_next_page_url(current_page_url, next_page_number)

                try:
                    logger.info("Переходим на страницу поиска #%s", next_page_number)
                    main_page.goto(
                        next_page_url,
                        wait_until="domcontentloaded",
                        timeout=NAVIGATION_TIMEOUT_MS,
                    )
                    main_page.wait_for_timeout(2000 + int(DELAY_BETWEEN_PAGES_SEC * 1000))

                    close_unexpected_pages(context, main_page)
                    dismiss_app_banner(main_page)

                    current_page_number = next_page_number
                    current_page_url = next_page_url
                except Exception as exc:
                    logger.warning(
                        "Не удалось открыть страницу поиска #%s: %s",
                        next_page_number,
                        exc,
                    )
                    break

        finally:
            browser.close()