import logging
import re
import random
import time
import json
import os
import requests
from typing import Iterator, Tuple, List, Optional, Set
from sqlite3 import Connection

from playwright_stealth import stealth_sync
from playwright.sync_api import (
    BrowserContext,
    Page,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)
from humanization import Humanization

from config import (
    CARD_OPEN_RETRIES,
    DEFAULT_HEADLESS,
    DELAY_BETWEEN_CARDS_SEC,
    DELAY_BETWEEN_PAGES_SEC,
    DELAY_BETWEEN_RETRIES_SEC,
    MAX_ALL_PAGES,
    NAVIGATION_TIMEOUT_MS,
    PAGE_TIMEOUT_MS,
    RANDOM_START_DELAY,
    RANDOM_SCROLL,
    USER_AGENTS,
)
from parser import parse_ad_page
from utils import build_search_url, normalize_href, is_ad_url, extract_avito_id_from_url

logger = logging.getLogger(__name__)


def get_free_proxy() -> Optional[str]:
    """Получает рабочий прокси из бесплатного источника."""
    try:
        response = requests.get(
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
            timeout=10
        )
        if response.status_code == 200:
            proxies = response.text.strip().split('\r\n')
            for proxy in proxies:
                if ':' in proxy and len(proxy.split(':')) == 2:
                    return proxy
    except Exception as e:
        logger.warning(f"Не удалось получить прокси: {e}")
    return None


def save_cookies(context, path: str = "cookies.json") -> None:
    """Сохраняет cookies в файл."""
    try:
        cookies = context.cookies()
        with open(path, "w") as f:
            json.dump(cookies, f)
        logger.debug(f"Cookies сохранены в {path}")
    except Exception as e:
        logger.warning(f"Ошибка сохранения cookies: {e}")


def load_cookies(context, path: str = "cookies.json") -> bool:
    """Загружает cookies из файла."""
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                cookies = json.load(f)
                context.add_cookies(cookies)
            logger.debug(f"Cookies загружены из {path}")
            return True
    except Exception as e:
        logger.warning(f"Ошибка загрузки cookies: {e}")
    return False


def try_solve_captcha(page: Page) -> bool:
    """
    Пытается автоматически решить капчу с помощью playwright-captcha.
    """
    try:
        from playwright_captcha import CaptchaType, ClickSolver, FrameworkType
        
        logger.info("Попытка автоматического решения капчи через ClickSolver...")
        
        solver = ClickSolver(framework=FrameworkType.PLAYWRIGHT, page=page)
        
        result = solver.solve_captcha(
            captcha_container=page,
            captcha_type=CaptchaType.CLOUDFLARE_TURNSTILE
        )
        
        if result:
            logger.info("Капча успешно решена автоматически")
            time.sleep(2)
            return True
        else:
            logger.warning("Автоматическое решение капчи не удалось")
            return False
            
    except ImportError:
        logger.debug("Библиотека playwright-captcha не установлена")
        return False
    except Exception as e:
        logger.warning(f"Ошибка при автоматическом решении капчи: {e}")
        return False


def is_already_in_db(conn: Connection, avito_id: str, query_text: str) -> bool:
    """Проверяет, есть ли уже объявление в БД."""
    if not conn or not avito_id:
        return False
    
    try:
        cursor = conn.execute(
            "SELECT 1 FROM ads WHERE avito_id = ? AND query_text = ?",
            (avito_id, query_text)
        )
        return cursor.fetchone() is not None
    except Exception as e:
        logger.debug(f"Ошибка проверки БД: {e}")
        return False


class PageWithHumanization:
    """Класс-обертка для страницы с humanization."""
    
    def __init__(self, page: Page):
        self.page = page
        self.human = Humanization(page)
        self._stealth_applied = False
    
    def apply_stealth(self) -> None:
        """Применяет stealth один раз."""
        if not self._stealth_applied:
            try:
                stealth_sync(self.page)
                self._stealth_applied = True
                logger.debug("Stealth применен")
            except Exception as e:
                logger.warning("Ошибка stealth: %s", e)
    
    def get_page_text(self) -> str:
        """Безопасно получает текст всей страницы через body."""
        try:
            text = self.page.locator("body").text_content() or ""
            return text.lower()
        except Exception:
            return ""
    
    def wait_for_page_load(self, timeout_sec: int = 30) -> bool:
        """Ожидает загрузки страницы."""
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            try:
                if self.page.locator("body").count() > 0:
                    logger.debug("Страница загружена")
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        logger.warning("Страница не загрузилась за %s секунд", timeout_sec)
        return False
    
    def is_blocked_page(self) -> bool:
        """
        Проверяет, не заблокировали ли доступ.
        Сначала убеждаемся, что страница загружена.
        """
        try:
            # Сначала проверяем, что страница вообще загружена
            if self.page.locator("body").count() == 0:
                return False
            
            # Проверяем iframe капчи
            captcha_frame = self.page.locator("iframe[src*='captcha']")
            if captcha_frame.count() > 0:
                logger.debug("Найден iframe капчи")
                return True
            
            # Проверяем элементы капчи (только точные совпадения)
            captcha_elements = self.page.locator('[class*="captcha"], [id*="captcha"]')
            if captcha_elements.count() > 0:
                # Дополнительная проверка: есть ли текст капчи на странице
                page_text = self.get_page_text()
                captcha_text_markers = ["подтвердите", "captcha", "проверка безопасности"]
                if any(marker in page_text for marker in captcha_text_markers):
                    logger.debug("Найден элемент капчи и подтверждающий текст")
                    return True
                else:
                    logger.debug("Найден элемент с captcha, но текст отсутствует - ложное срабатывание")
                    return False
            
            return False
        except Exception as e:
            logger.debug(f"Ошибка проверки блокировки: {e}")
            return False
    
    def guard_page_state(self) -> Tuple[bool, str]:
        """
        Проверяет состояние страницы в контрольных точках.
        Возвращает (is_ok, status).
        status: blocked, closed, loading, ok
        """
        # Проверка блокировки
        if self.is_blocked_page():
            return False, "blocked"
        
        # Проверка текста на признаки закрытого объявления
        page_text = self.get_page_text()
        
        closed_markers = [
            "объявление снято с публикации",
            "объявление не найдено",
            "страница не найдена",
            "объявление закрыто",
            "снято с публикации",
            "объявление удалено",
            "товар продан",
        ]
        
        if any(marker in page_text for marker in closed_markers):
            return False, "closed"
        
        # Проверка, что страница не пустая
        if len(page_text.strip()) < 20:
            return False, "loading"
        
        return True, "ok"
    
    def check_captcha_before_action(self, action_name: str = "действие") -> bool:
        """
        Проверяет капчу перед важным действием.
        """
        if self.is_blocked_page():
            logger.warning(f"Обнаружена капча перед {action_name}")
            return self.handle_captcha()
        return True
    
    def handle_captcha(self) -> bool:
        """
        Обрабатывает капчу в контрольных точках.
        Сначала автоматическое решение, затем ручное.
        """
        if not self.is_blocked_page():
            return True
        
        logger.warning("Обнаружена капча")
        
        # Попытка автоматического решения
        if try_solve_captcha(self.page):
            self.wait_random(2, 3)
            if not self.is_blocked_page():
                return True
        
        # Ручное решение
        logger.info("Пожалуйста, пройдите капчу вручную. У вас есть 120 секунд.")
        
        start_time = time.time()
        while time.time() - start_time < 120:
            if not self.is_blocked_page():
                logger.info("Капча пройдена")
                time.sleep(2)
                return True
            time.sleep(2)
        
        logger.warning("Таймаут ожидания прохождения капчи")
        return False
    
    def is_empty_search(self) -> bool:
        """Проверяет, пустой ли результат поиска."""
        try:
            items = self.page.locator('[data-marker="item"]')
            if items.count() > 0:
                return False
            
            page_text = self.get_page_text()
            empty_markers = [
                "ничего не найдено",
                "по вашему запросу ничего нет",
                "объявлений не найдено",
                "ничего не нашлось",
                "попробуйте изменить запрос",
            ]
            
            if any(marker in page_text for marker in empty_markers):
                return True
            
            return False
            
        except Exception:
            return False

    def has_items(self) -> bool:
        """Проверяет, есть ли на странице объявления."""
        try:
            items = self.page.locator('[data-marker="item"]')
            count = items.count()
            logger.debug(f"Найдено карточек: {count}")
            return count > 0
        except Exception:
            return False
    
    def collect_items_with_selectors(self) -> List[Tuple[str, int, object]]:
        """
        Собирает ссылки и элементы карточек.
        Возвращает список (url, index, element).
        """
        items_data = []
        
        try:
            items = self.page.locator('[data-marker="item"]').all()
            
            for idx, item in enumerate(items):
                try:
                    link = item.locator('a[data-marker="item-title"]').first
                    href = normalize_href(link.get_attribute("href"))
                    if href and is_ad_url(href):
                        items_data.append((href, idx, item))
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Ошибка сбора: {e}")
        
        return items_data
    
    def collect_items_urls(self) -> List[str]:
        """Собирает ссылки на объявления (для fallback)."""
        urls = []
        
        try:
            items = self.page.locator('[data-marker="item"]').all()
            for item in items:
                try:
                    link = item.locator('a[data-marker="item-title"]').first
                    href = normalize_href(link.get_attribute("href"))
                    if href and is_ad_url(href):
                        urls.append(href)
                except Exception:
                    continue
        except Exception:
            pass
        
        return list(dict.fromkeys(urls))
    
    def is_valid_ad_page(self) -> Tuple[bool, str]:
        """Проверяет, является ли страница валидной карточкой объявления."""
        # Используем guard_page_state для базовых проверок
        is_ok, status = self.guard_page_state()
        if not is_ok:
            return False, status

        title_selectors = [
            "h1",
            '[data-marker="item-view/title-info"]',
        ]
        price_selectors = [
            '[itemprop="price"]',
            '[data-marker="item-view/item-price"]',
        ]
        description_selectors = [
            '[data-marker="item-view/item-description"]',
            '[data-marker="item-view/item-description-text"]',
        ]

        has_title = False
        has_price = False
        has_description = False

        try:
            for selector in title_selectors:
                if self.page.locator(selector).count() > 0:
                    has_title = True
                    break
        except Exception:
            pass

        try:
            for selector in price_selectors:
                if self.page.locator(selector).count() > 0:
                    has_price = True
                    break
        except Exception:
            pass

        try:
            for selector in description_selectors:
                if self.page.locator(selector).count() > 0:
                    has_description = True
                    break
        except Exception:
            pass

        if has_title and (has_price or has_description):
            return True, "valid"

        if has_title:
            return False, "loading"

        return False, "unknown"
    
    def random_scroll(self) -> None:
        """Случайный скролл."""
        try:
            scroll_y = random.randint(*RANDOM_SCROLL)
            self.page.evaluate(f"window.scrollBy(0, {scroll_y})")
        except Exception:
            pass
    
    def human_click(self, element, timeout: int = 3000) -> bool:
        """Человеческий клик с предварительной проверкой капчи."""
        try:
            # Проверяем капчу перед кликом
            if not self.check_captcha_before_action("клик"):
                return False
            
            time.sleep(random.uniform(0.5, 1.5))
            self.human.click_at(element, timeout=timeout)
            return True
        except Exception:
            return False
    
    def goto_with_retries(self, url: str, referer: str = None, max_retries: int = 3) -> Tuple[bool, str]:
        """
        Переход с повторными попытками при сетевых ошибках.
        Возвращает (успех, статус).
        """
        delays = [3, 8, 15]
        
        for attempt in range(1, max_retries + 1):
            try:
                time.sleep(random.uniform(0.5, 1.5))
                
                if referer:
                    self.page.set_extra_http_headers({"Referer": referer})
                
                self.page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
                
                if referer:
                    self.page.set_extra_http_headers({})
                
                time.sleep(random.uniform(0.5, 1.5))
                
                # После успешного перехода проверяем состояние
                is_ok, status = self.guard_page_state()
                if is_ok:
                    return True, "success"
                else:
                    logger.warning(f"Страница загружена, но состояние аномально: {status}")
                    return False, status
                
            except PlaywrightTimeoutError as e:
                logger.warning(f"Таймаут при переходе (попытка {attempt}/{max_retries}): {url}")
                if attempt < max_retries:
                    time.sleep(delays[attempt - 1])
                    
            except Exception as e:
                error_msg = str(e)
                if "ERR_CONNECTION_CLOSED" in error_msg or "ERR_EMPTY_RESPONSE" in error_msg:
                    logger.warning(f"Сетевая ошибка (попытка {attempt}/{max_retries}): {error_msg[:100]}")
                    if attempt < max_retries:
                        time.sleep(delays[attempt - 1])
                else:
                    logger.warning(f"Ошибка при переходе: {error_msg[:100]}")
                    return False, f"error: {error_msg[:50]}"
        
        return False, "max_retries_exceeded"
    
    def wait_random(self, min_sec: float = None, max_sec: float = None) -> None:
        """Случайная пауза."""
        if min_sec is None:
            min_sec = DELAY_BETWEEN_CARDS_SEC
        if max_sec is None:
            max_sec = min_sec + 1.0
        
        time.sleep(random.uniform(min_sec, max_sec))
    
    def warm_up(self) -> None:
        """Прогрев сессии."""
        try:
            self.random_scroll()
            self.wait_random(1, 2)
            
            self.page.mouse.move(
                random.randint(100, 500),
                random.randint(100, 500)
            )
            self.wait_random(0.5, 1)
            
            self.random_scroll()
            self.wait_random(1, 2)
        except Exception:
            pass


def block_app_pages(route: Route) -> None:
    """Блокирует рекламные запросы."""
    url = route.request.url.lower()
    
    blocked_markers = [
        "avito.ru/apps",
        "utm_campaign",
        "googleads",
        "doubleclick",
        "facebook.com/tr",
        "mc.yandex.ru",
    ]
    
    if any(marker in url for marker in blocked_markers):
        route.abort()
        return
    
    route.continue_()


def close_unwanted_pages(context: BrowserContext, main_page: Page) -> None:
    """Закрывает только рекламные вкладки."""
    unwanted_patterns = [
        "avito.ru/apps",
        "utm_campaign",
        "googleads",
        "doubleclick",
    ]
    
    for p in context.pages:
        if p == main_page:
            continue
            
        try:
            url = (p.url or "").lower()
            if any(pattern in url for pattern in unwanted_patterns):
                logger.debug(f"Закрываем рекламную вкладку: {p.url}")
                p.close()
        except Exception:
            continue


def dismiss_app_banner(page_wrapper: PageWithHumanization) -> None:
    """Закрывает баннер приложения."""
    close_selectors = [
        "button[aria-label='Закрыть']",
        "button[aria-label='close']",
        "button:has-text('Закрыть')",
        "button:has-text('×')",
        "button:has-text('✕')",
    ]
    
    for selector in close_selectors:
        try:
            locator = page_wrapper.page.locator(selector).first
            if locator.is_visible():
                if page_wrapper.human_click(locator):
                    logger.debug("Закрыли баннер")
                    page_wrapper.wait_random(0.3, 0.7)
                    return
        except Exception:
            continue


def safe_open_search_page(
    page_wrapper: PageWithHumanization, 
    url: str, 
    context: BrowserContext,
    context_wrapper: object = None
) -> Tuple[bool, str]:
    """Открывает страницу поиска с проверкой."""
    logger.info("Открываем страницу поиска: %s", url)
    
    start_delay = random.uniform(*RANDOM_START_DELAY)
    logger.debug(f"Пауза перед открытием: {start_delay:.1f} сек")
    time.sleep(start_delay)
    
    page_wrapper.apply_stealth()
    
    # Используем goto с retries
    success, status = page_wrapper.goto_with_retries(url)
    if not success:
        logger.error(f"Не удалось загрузить страницу: {status}")
        return False, status
    
    if not page_wrapper.wait_for_page_load(20):
        logger.warning("Страница не загрузилась за 20 секунд")
        return False, "timeout"
    
    time.sleep(2)
    
    # Проверяем состояние после загрузки
    is_ok, state_status = page_wrapper.guard_page_state()
    if not is_ok:
        if state_status == "blocked":
            if page_wrapper.handle_captcha():
                page_wrapper.page.reload()
                page_wrapper.wait_random(2, 3)
            else:
                return False, "blocked"
        elif state_status == "closed":
            logger.warning("Страница поиска определена как закрытая")
            return False, "closed"
        elif state_status == "loading":
            logger.warning("Страница поиска не полностью загрузилась")
            return False, "loading"
    
    close_unwanted_pages(context, page_wrapper.page)
    dismiss_app_banner(page_wrapper)
    
    page_wrapper.warm_up()
    
    if not page_wrapper.has_items():
        logger.warning("На странице нет объявлений")
        return False, "no_items"
    
    if context_wrapper and hasattr(context_wrapper, 'context'):
        save_cookies(context_wrapper.context)
    
    logger.info("Страница поиска успешно загружена")
    return True, "success"


def open_card_by_click(
    main_wrapper: PageWithHumanization,
    card_item,
    context: BrowserContext,
    retries: int = 2
) -> Tuple[Optional[Page], bool, str]:
    """
    Открывает карточку через клик по ссылке.
    Возвращает (страница_карточки, успех, статус).
    """
    for attempt in range(1, retries + 1):
        try:
            logger.debug(f"Клик по карточке (попытка {attempt}/{retries})")
            
            # Проверяем капчу перед кликом
            if not main_wrapper.check_captcha_before_action("открытие карточки"):
                return None, False, "blocked"
            
            link = card_item.locator('a[data-marker="item-title"]').first
            
            if not main_wrapper.human_click(link):
                raise Exception("Клик не удался")
            
            main_wrapper.wait_random(2, 3)
            
            new_page = None
            for page in context.pages:
                if page not in [main_wrapper.page] and "avito.ru" in page.url:
                    new_page = page
                    break
            
            if not new_page:
                logger.debug("Новая страница не появилась")
                continue
            
            # Проверяем, что URL изменился
            if new_page.url == main_wrapper.page.url:
                logger.debug("URL не изменился, переход не произошёл")
                new_page.close()
                continue
            
            # Проверяем, что новая страница не является страницей поиска
            if "all?q=" in new_page.url or "avito.ru/rossiya" in new_page.url:
                logger.debug("Переход привёл на страницу поиска, а не на карточку")
                new_page.close()
                continue
            
            new_wrapper = PageWithHumanization(new_page)
            new_wrapper.apply_stealth()
            new_wrapper.wait_random(1, 2)
            
            # Проверяем состояние карточки
            is_ok, status = new_wrapper.guard_page_state()
            if not is_ok:
                if status == "blocked":
                    if new_wrapper.handle_captcha():
                        new_page.reload()
                        new_wrapper.wait_random(2, 3)
                    else:
                        new_page.close()
                        return None, False, "blocked"
                elif status == "closed":
                    return new_page, True, "closed"
                else:
                    logger.debug(f"Карточка в состоянии: {status}")
            
            return new_page, True, "success"
            
        except Exception as e:
            logger.debug(f"Ошибка при клике: {e}")
            
            if attempt < retries:
                main_wrapper.wait_random(2, 4)
    
    return None, False, "click_failed"


def open_card_by_goto(
    page_wrapper: PageWithHumanization,
    url: str,
    referer: str,
    retries: int
) -> Tuple[bool, str]:
    """
    Открывает карточку через прямой переход с referer.
    """
    for attempt in range(1, retries + 1):
        try:
            logger.debug("Переход по URL: %s (попытка %s/%s)", url, attempt, retries)

            page_wrapper.apply_stealth()
            page_wrapper.wait_random(2, 4)
            
            success, status = page_wrapper.goto_with_retries(url, referer=referer, max_retries=1)
            if not success:
                logger.debug(f"Переход не удался: {status}")
                continue
            
            page_wrapper.wait_random(2, 4)
            
            # Проверяем, что URL изменился
            if page_wrapper.page.url == referer:
                logger.debug("URL не изменился, переход не произошёл")
                continue
            
            # Проверяем, что это не страница поиска
            if "all?q=" in page_wrapper.page.url or "avito.ru/rossiya" in page_wrapper.page.url:
                logger.debug("Переход привёл на страницу поиска, а не на карточку")
                return False, "redirected_to_search"
            
            # Проверяем состояние
            is_ok, state_status = page_wrapper.guard_page_state()
            if not is_ok:
                if state_status == "blocked":
                    if page_wrapper.handle_captcha():
                        page_wrapper.page.reload()
                        page_wrapper.wait_random(2, 3)
                        continue
                    else:
                        return False, "blocked"
                elif state_status == "closed":
                    return True, "closed"
                else:
                    logger.debug(f"Карточка в состоянии: {state_status}")
            
            page_wrapper.random_scroll()
            return True, "success"
            
        except PlaywrightTimeoutError:
            logger.warning("Timeout: %s", url)
        except Exception as exc:
            logger.warning("Ошибка: %s", exc)

        if attempt < retries:
            page_wrapper.wait_random(3, 6)

    return False, "timeout"


def get_next_page_url(search_url: str, next_page_number: int) -> str:
    """Формирует URL следующей страницы."""
    if re.search(r"([?&])p=\d+", search_url):
        return re.sub(r"([?&])p=\d+", rf"\1p={next_page_number}", search_url)
    
    separator = "&" if "?" in search_url else "?"
    return f"{search_url}{separator}p={next_page_number}"


def iterate_ads(
    query_text: str,
    pages: int | None = None,
    all_pages: bool = False,
    headless: bool | None = None,
    max_time: int = 0,
    only_new: bool = False,
    conn: Connection = None,
    start_time: float = None,
) -> Iterator[dict]:
    """Основной итератор объявлений."""
    if headless is None:
        headless = DEFAULT_HEADLESS
    
    if start_time is None:
        start_time = time.time()
    
    search_url = build_search_url(query_text)
    seen_urls: Set[str] = set()
    
    with sync_playwright() as p:
        user_agent = random.choice(USER_AGENTS)
        logger.info(f"Запуск браузера. User-Agent: {user_agent[:50]}...")
        
        # Настройка прокси (опционально, закомментировано по умолчанию)
        proxy_config = {}
        use_proxy = True
        if use_proxy:
             proxy_url = get_free_proxy()
             if proxy_url:
                 proxy_config = {"proxy": {"server": f"http://{proxy_url}"}}
                 logger.info(f"Используется прокси: {proxy_url}")
        
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
            **proxy_config
        )
        
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=user_agent,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            permissions=["geolocation"],
            geolocation={"longitude": 37.6176, "latitude": 55.7558},
        )
        
        load_cookies(context)
        
        context.route("**/*", block_app_pages)
        
        main_page = context.new_page()
        main_page.set_default_timeout(PAGE_TIMEOUT_MS)
        main_wrapper = PageWithHumanization(main_page)
        
        class ContextWrapper:
            def __init__(self, context):
                self.context = context
        
        context_wrapper = ContextWrapper(context)
        
        try:
            success, reason = safe_open_search_page(
                main_wrapper, search_url, context, context_wrapper
            )
            if not success:
                logger.error("Не удалось открыть страницу поиска: %s", reason)
                return
            
            max_pages = MAX_ALL_PAGES if all_pages else (pages or 1)
            current_page_number = 1
            current_page_url = search_url
            
            while current_page_number <= max_pages:
                # Проверка времени работы
                if max_time > 0 and (time.time() - start_time) > max_time:
                    logger.info(f"Достигнуто максимальное время работы: {max_time} секунд")
                    break
                
                logger.info(f"Обрабатываем страницу поиска #{current_page_number}")
                
                items_data = main_wrapper.collect_items_with_selectors()
                logger.info(f"Найдено объявлений: {len(items_data)}")
                
                if not items_data:
                    logger.warning("На странице нет объявлений")
                    break
                
                # Приоритизация: сначала новые объявления
                new_items = []
                existing_items = []
                
                if only_new and conn:
                    for url, idx, card_item in items_data:
                        avito_id = extract_avito_id_from_url(url)
                        if avito_id and is_already_in_db(conn, avito_id, query_text):
                            existing_items.append((url, idx, card_item))
                        else:
                            new_items.append((url, idx, card_item))
                    
                    items_to_process = new_items + existing_items
                    logger.info(f"Из них новых: {len(new_items)}, уже есть в БД: {len(existing_items)}")
                else:
                    items_to_process = items_data
                
                for url, idx, card_item in items_to_process:
                    # Проверка времени работы
                    if max_time > 0 and (time.time() - start_time) > max_time:
                        logger.info("Достигнуто максимальное время работы, прерываем обработку")
                        break
                    
                    # Проверка на already existing для only_new режима
                    if only_new and conn:
                        avito_id = extract_avito_id_from_url(url)
                        if avito_id and is_already_in_db(conn, avito_id, query_text):
                            logger.debug(f"Пропуск существующего объявления: {avito_id}")
                            yield {"_skip_reason": "already_exists"}
                            continue
                    
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    
                    logger.debug(f"Обработка объявления: {url[:80]}...")
                    
                    # Способ 1: пробуем открыть через клик
                    card_page, opened, status = open_card_by_click(
                        main_wrapper, card_item, context, retries=2
                    )
                    
                    # Способ 2: если не получилось, пробуем прямой переход
                    if not opened:
                        logger.debug(f"Клик не удался ({status}), пробуем прямой переход")
                        card_page = context.new_page()
                        card_page.set_default_timeout(PAGE_TIMEOUT_MS)
                        card_wrapper = PageWithHumanization(card_page)
                        
                        opened, status = open_card_by_goto(
                            card_wrapper, url, main_wrapper.page.url, CARD_OPEN_RETRIES
                        )
                        
                        if not opened:
                            logger.debug(f"Карточка пропущена: {status}")
                            try:
                                card_page.close()
                            except Exception:
                                pass
                            continue
                    
                    # Парсим данные
                    try:
                        ad_data = parse_ad_page(card_page, query_text, url)
                        if ad_data is not None:
                            yield ad_data
                            logger.debug(f"Объявление сохранено: {ad_data.get('title', '')[:50]}")
                        
                        delay = random.uniform(DELAY_BETWEEN_CARDS_SEC, DELAY_BETWEEN_CARDS_SEC + 2.0)
                        time.sleep(delay)
                        
                    except Exception as e:
                        logger.warning(f"Ошибка парсинга: {e}")
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
                    logger.info(f"Переход на страницу #{next_page_number}")
                    main_wrapper.wait_random(3, 5)
                    
                    success, status = main_wrapper.goto_with_retries(next_page_url)
                    if not success:
                        logger.error(f"Не удалось перейти на страницу {next_page_number}: {status}")
                        break
                    
                    # Проверяем состояние после перехода
                    is_ok, state_status = main_wrapper.guard_page_state()
                    if not is_ok:
                        if state_status == "blocked":
                            if main_wrapper.handle_captcha():
                                main_wrapper.page.reload()
                                main_wrapper.wait_random(2, 3)
                            else:
                                logger.error("Блокировка при переходе")
                                break
                        elif state_status == "empty_search" or main_wrapper.is_empty_search():
                            logger.warning("Пустая выдача")
                            break
                    
                    close_unwanted_pages(context, main_page)
                    dismiss_app_banner(main_wrapper)
                    
                    if not main_wrapper.has_items():
                        logger.warning(f"После перехода на странице #{next_page_number} нет карточек")
                        break
                    
                    main_wrapper.wait_random(DELAY_BETWEEN_PAGES_SEC, DELAY_BETWEEN_PAGES_SEC + 2.0)
                    main_wrapper.warm_up()
                    
                    save_cookies(context)
                    
                    current_page_number = next_page_number
                    current_page_url = next_page_url
                    
                except Exception as exc:
                    logger.warning(f"Ошибка перехода: {exc}")
                    break
                    
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
        finally:
            save_cookies(context)
            logger.info("Закрываем браузер")
            browser.close()