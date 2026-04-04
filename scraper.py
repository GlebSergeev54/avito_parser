"""
- Запуск браузера и настройка
- Переход по страницам поиска
- Получение ссылок на объявления
- Открытие объявлений
- Обход капчи и блокировок
- Передачу данных в parser.py
"""

import logging
import re #regex
import random #имитация поведения человека
import time #имитация поведения человека
import json #cookies
import os #cookies
import requests #proxy
from typing import Iterator, Tuple, List, Optional, Set
from sqlite3 import Connection

from playwright_stealth import stealth_sync #обход защиты браузера
from playwright.sync_api import (
    BrowserContext,
    Page,
    Route,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from humanization import Humanization # эмулирует человеческое поведение

# Параметры работы, определяются в конфиге
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
    """
    прокси
    """
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
    """
    cookies, позволяет сохранить сессию между запусками и избегать повторной капчи
    """
    try:
        cookies = context.cookies()
        with open(path, "w") as f:
            json.dump(cookies, f)
        logger.debug(f"Cookies сохранены в {path}")
    except Exception as e:
        logger.warning(f"Ошибка сохранения cookies: {e}")


def load_cookies(context, path: str = "cookies.json") -> bool:
    """
    Загружает cookies из файла в браузер.
    Возвращает True, если cookies были загружены.
    """
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
    Обход капчи
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
            logger.info("Капча пройдена")
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
    """ 
    Класс-обертка для страницы с humanization
    Добавляет функциональность:
    - Stealth (скрытие признаков автоматизации)
    - Humanization (человеческое поведение: клики, задержки)
    - Обработка капчи
    - Повторные попытки при сетевых ошибках
    """
    
    def __init__(self, page: Page):
        self.page = page
        self.human = Humanization(page)
        self._stealth_applied = False # флаг, чтобы stealth применялся только один раз
    
    def apply_stealth(self) -> None: #применение stealth к странице
        if not self._stealth_applied:
            try:
                stealth_sync(self.page)
                self._stealth_applied = True
                logger.debug("Stealth применен")
            except Exception as e:
                logger.warning("Ошибка stealth: %s", e)

    def get_page_text(self) -> str:
        """
        безопасно получает текст всей страницы через body
        возвращает текст в нижнем регистре или пустую строку при ошибке
        """
        try:
            text = self.page.locator("body").text_content() or ""
            return text.lower()
        except Exception:
            return ""
    
    def wait_for_page_load(self, timeout_sec: int = 30) -> bool: #ожидаем загрузку страницы
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
        проверяет, не заблокировали ли доступ
        условия:
        -наличие iframe с captcha
        -наличие элементов с классом/id содержащим captcha и соответствующего текста
        
        на данном этапе возможны ложные срабатывания (!)
        """
        try:
             # загружена ли страница
            if self.page.locator("body").count() == 0:
                return False
            
            # Проверяем iframe капчи
            captcha_frame = self.page.locator("iframe[src*='captcha']")
            if captcha_frame.count() > 0:
                logger.debug("Найден iframe капчи")
                return True
            
             # Проверяем элементы капчи
            captcha_elements = self.page.locator('[class*="captcha"], [id*="captcha"]')
            if captcha_elements.count() > 0:
                # Дополнительная проверка: есть ли текст капчи на странице
                page_text = self.get_page_text()
                captcha_text_markers = ["подтвердите", "captcha", "проверка безопасности"]
                if any(marker in page_text for marker in captcha_text_markers):
                    logger.debug("Найден элемент капчи и подтверждающий текст")
                    return True
                else:
                    # Найден элемент с captcha в имени, но текст отсутствует - ложное срабатывание
                    logger.debug("Найден элемент с captcha, но текст отсутствует - ложное срабатывание")
                    return False
            
            return False
        except Exception as e:
            logger.debug(f"Ошибка проверки блокировки: {e}")
            return False
    
    def guard_page_state(self) -> Tuple[bool, str]:
        """
        проверяет состояние страницы
        возвращает:
        -blocked  - страница заблокирована (капча)
        -closed   - закрытое объявление
        -loading  - страница загрузилась не полностью
        -ok       - нормальное состояние
        """
        # Проверка блокировки
        if self.is_blocked_page():
            return False, "blocked"
        
        # Проверка на признаки закрытого объявления
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
        
        # проверка что страница не пустая
        if len(page_text.strip()) < 20:
            return False, "loading"
        
        return True, "ok"
    
    def check_captcha_before_action(self, action_name: str = "действие") -> bool:
        """
        Обнаружение капчи
        """
        if self.is_blocked_page():
            logger.warning(f"Обнаружена капча перед {action_name}")
            return self.handle_captcha()
        return True
    
    def handle_captcha(self) -> bool:
        """
        обрабатывает капчу
            1. пробует автоматическое решение (через playwright-captcha)
            2. далее  ждёт ручного решения (120 секунд)
        """
        if not self.is_blocked_page():
            return True
        
        logger.warning("Обнаружена капча")
        
        if try_solve_captcha(self.page):
            self.wait_random(2, 3)
            if not self.is_blocked_page():
                return True
        
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
        """
        # проверка результата поиска
        """
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
        
        Сначала даём странице немного времени дорисовать карточки.
        Это уменьшает риск ложной пустой выдачи.
        """
        items_data = []
        
        try:
            try:
                self.page.wait_for_selector('[data-marker="item"]', timeout=8000)
                logger.debug("Карточки появились")
            except Exception:
                logger.debug("Карточки не появились за 8 секунд, пробуем собрать то, что есть")
            
            items = self.page.locator('[data-marker="item"]').all()
            
            for idx, item in enumerate(items):
                try:
                    link = item.locator('a[data-marker="item-title"]').first
                    href = normalize_href(link.get_attribute("href"))
                    if href and is_ad_url(href):
                        items_data.append((href, idx, item))
                except Exception as e:
                    logger.debug(f"Не удалось извлечь ссылку из карточки #{idx}: {e}")
                    continue
        except Exception as e:
            logger.debug(f"Ошибка сбора карточек: {e}")
        
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
            if not self.check_captcha_before_action("клик"):
                return False
            
            time.sleep(random.uniform(0.5, 1.5))
            self.human.click_at(element, timeout=timeout)
            return True
        except Exception:
            return False
    
    def goto_with_retries(self, url: str, referer: str = None, max_retries: int = 3) -> Tuple[bool, str]:
        """Переход с повторными попытками при сетевых ошибках."""
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
                
                is_ok, status = self.guard_page_state()
                if is_ok:
                    return True, "success"
                else:
                    logger.warning(f"Страница загружена, но состояние аномально: {status}")
                    return False, status
                
            except PlaywrightTimeoutError:
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
        """Прогрев сессии - создаем видимость использования сайта человеком перед парсингом"""
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
    
    # Делаем случайную паузу перед первым переходом
    start_delay = random.uniform(*RANDOM_START_DELAY)
    logger.debug(f"Пауза перед открытием: {start_delay:.1f} сек")
    time.sleep(start_delay)
    
    # Применяем stealth плагин
    page_wrapper.apply_stealth()
    
     # Открытие страницы поиска через обёртку с ретраями 
    success, status = page_wrapper.goto_with_retries(url)
    if not success:
        logger.error(f"Не удалось загрузить страницу: {status}")
        return False, status
    
    # Ждём 20 секунд, пока страница полностью загрузятся 
    if not page_wrapper.wait_for_page_load(20):
        logger.warning("Страница не загрузилась за 20 секунд")
        return False, "timeout"
    
    # дополнительная пауза после загрузки
    # часть элементов Avito может дорисовываться уже после появления body
    time.sleep(2)
    
    # проверяем состояние страницы
    is_ok, state_status = page_wrapper.guard_page_state()
    """
    - blocked  -> капча / блокировка
    - closed   -> страница недоступна
    - loading  -> страница недогружена
    - ok       -> можно продолжать работу
    """
    if not is_ok:
        if state_status == "blocked": # автоматически или вручную пытаемся обойти капчу
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
    
    # закрываем лишние вкладки, которые могли открыться как рекламные или служебные
    close_unwanted_pages(context, page_wrapper.page)
    # пытаемся закрыть баннер приложения (предлажение установить авито)
    dismiss_app_banner(page_wrapper)
    
    """
    Выполняем прогрев страницы: скролл, движение мыши, паузы
    Для обхода защиты от неесественного поведения и для подгрузки части интерфейса
    """
    page_wrapper.warm_up()
    
    if not page_wrapper.has_items():
        logger.warning("На странице нет объявлений")
        return False, "no_items"
    
    # если передали обёртку контекста сохранение cookies для повторных запусков (возможно реже ловить капчу)
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
    """Открывает карточку через клик по ссылке."""
    for attempt in range(1, retries + 1):
        try:
            logger.debug(f"Клик по карточке (попытка {attempt}/{retries})")
            
            # не появилась ли капча после загрузки страницы 
            if not main_wrapper.check_captcha_before_action("открытие карточки"):
                return None, False, "blocked"
            
            # Берём ссылку заголовка внутри карточки — по ней обычно открывается объявление
            link = card_item.locator('a[data-marker="item-title"]').first
            
            # Используем humanized-клик 
            if not main_wrapper.human_click(link):
                raise Exception("Клик не удался")
            
             # время сайту открыть новую вкладку / страницу
            main_wrapper.wait_random(2, 3)
            
            new_page = None

            # После клика ищем новую страницу в браузерном контексте
            for page in context.pages:
                if page not in [main_wrapper.page] and "avito.ru" in page.url:
                    new_page = page
                    break

            # если страница не нашлась 
            if not new_page:
                logger.debug("Новая страница не появилась")
                continue

            # URL новой страницы совпал с URL поиска, перехода в карточку не произошло
            if new_page.url == main_wrapper.page.url:
                logger.debug("URL не изменился, переход не произошёл")
                new_page.close()
                continue
            
            # вместо карточки открывается снова выдача поиска, закрываем страницу
            if "all?q=" in new_page.url or "avito.ru/rossiya" in new_page.url:
                logger.debug("Переход привёл на страницу поиска, а не на карточку")
                new_page.close()
                continue
            
            # Оборачиваем новую страницу в тот же helper-класс для обхода защиты сайта
            new_wrapper = PageWithHumanization(new_page)
            new_wrapper.apply_stealth()
            new_wrapper.wait_random(1, 2)
            
            # проверяем, что открылось 
            is_ok, status = new_wrapper.guard_page_state()
            if not is_ok:
                if status == "blocked":
                    if new_wrapper.handle_captcha(): # капча
                        new_page.reload()
                        new_wrapper.wait_random(2, 3)
                    else:
                        new_page.close()
                        return None, False, "blocked"
                elif status == "closed":
                    return new_page, True, "closed" # закрытое объявление, всё равно передаем парсеру
                else:
                    logger.debug(f"Карточка в состоянии: {status}")
            
            return new_page, True, "success"
            
        except Exception as e:
            logger.debug(f"Ошибка при клике: {e}")
            
            if attempt < retries:
                # пауза между действиями 
                main_wrapper.wait_random(2, 4)
    
    return None, False, "click_failed"


def open_card_by_goto(
    page_wrapper: PageWithHumanization,
    url: str,
    referer: str,
    retries: int
) -> Tuple[bool, str]:
    """Открывает карточку через прямой переход с referer."""
    for attempt in range(1, retries + 1):
        try:
            logger.debug("Переход по URL: %s (попытка %s/%s)", url, attempt, retries)

            # fallback-сценарий, если клик по карточке не сработал или не открыл корректную страницу
            page_wrapper.apply_stealth()
            page_wrapper.wait_random(2, 4)
            
            # Переходим напрямую по URL карточки, но с referer от страницы поиска, 
            # чтобы переход выглядел более естественно для сайта
            success, status = page_wrapper.goto_with_retries(url, referer=referer, max_retries=1)
            if not success:
                logger.debug(f"Переход не удался: {status}")
                continue
            
            page_wrapper.wait_random(2, 4)
            
            # Если после goto URL остался таким же, как referer,
            # значит карточка фактически не открылась.
            if page_wrapper.page.url == referer:
                logger.debug("URL не изменился, переход не произошёл")
                continue
            
            # прямой переход ведёт не в карточку, а обратно в выдачу поиска.
            if "all?q=" in page_wrapper.page.url or "avito.ru/rossiya" in page_wrapper.page.url:
                logger.debug("Переход привёл на страницу поиска, а не на карточку")
                return False, "redirected_to_search"
            
            # проверка состояния страницы, получена ли реально карточка
            is_ok, state_status = page_wrapper.guard_page_state()
            if not is_ok:
                if state_status == "blocked": # капча
                    if page_wrapper.handle_captcha():
                        page_wrapper.page.reload()
                        page_wrapper.wait_random(2, 3)
                        continue
                    else:
                        return False, "blocked"
                elif state_status == "closed": # закрытое объявление, всё равно передаем парсеру
                    return True, "closed"
                else:
                    logger.debug(f"Карточка в состоянии: {state_status}")
            
            # скролл для человеческого поведения и дозагрузки элементов страницы
            page_wrapper.random_scroll()
            return True, "success"
            
        except PlaywrightTimeoutError:
            logger.warning("Timeout: %s", url)
        except Exception as exc:
            logger.warning("Ошибка: %s", exc)

        # пауза между попытками
        if attempt < retries:
            page_wrapper.wait_random(3, 6)

    return False, "timeout"


def get_next_page_url(search_url: str, next_page_number: int) -> str:
    """Формирует URL следующей страницы."""
    if re.search(r"([?&])p=\d+", search_url):
        return re.sub(r"([?&])p=\d+", rf"\1p={next_page_number}", search_url)
    
    separator = "&" if "?" in search_url else "?"
    return f"{search_url}{separator}p={next_page_number}"


def go_to_next_page_with_retries(
    main_wrapper: PageWithHumanization,
    context: BrowserContext,
    main_page: Page,
    next_page_url: str,
    next_page_number: int,
    retries: int = 2,
) -> Tuple[bool, str]:
    """
    Переход на следующую страницу поиска
    Повторяет попытку, если ошибка похожа на временную
    Возвращает: success, empty_search, no_items, blocked, loading, exception, failed
    """
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Переход на страницу #{next_page_number} (попытка {attempt}/{retries})")
            main_wrapper.wait_random(3, 5)

            # Переход на следующую страницу тоже делаем через защищённый goto:
            # он уже умеет обрабатывать сетевые ошибки и проверять состояние страницы.
            success, status = main_wrapper.goto_with_retries(next_page_url)
            if not success:
                logger.warning(f"Не удалось перейти на страницу #{next_page_number}: {status}")
                if attempt < retries:

                     # Если ошибка может быть временной, даём ещё одну попытку
                    main_wrapper.wait_random(3, 6)
                    continue
                return False, status
            
            # корректность состояни
            is_ok, state_status = main_wrapper.guard_page_state()
            if not is_ok:
                if state_status == "blocked": # капча 
                    if main_wrapper.handle_captcha():
                        main_wrapper.page.reload()
                        main_wrapper.wait_random(2, 3)
                        if attempt < retries:
                            continue
                    else:
                        if attempt < retries:
                            continue
                        return False, "blocked"

                elif main_wrapper.is_empty_search(): # конец выдачи, результатов больше нет
                    return False, "empty_search"
                
                # Страница могла недогрузиться, пробуем повторить переход
                elif state_status == "loading":
                    logger.warning("Следующая страница загрузилась не полностью")
                    if attempt < retries:
                        main_wrapper.page.reload()
                        main_wrapper.wait_random(2, 3)
                        continue
                    return False, "loading"

            # После успешного перехода убираем лишние вкладки и баннеры
            close_unwanted_pages(context, main_page)
            dismiss_app_banner(main_wrapper)

            # Финальная проверка есть ли на следующей странице карточки
            # Если карточек нет - либо конец выдачи, либо страница открылась некорректно
            if not main_wrapper.has_items():
                logger.warning(f"После перехода на странице #{next_page_number} нет карточек")
                if attempt < retries:
                    main_wrapper.page.reload()
                    main_wrapper.wait_random(2, 3)
                    continue
                return False, "no_items"

            return True, "success"

        except Exception as exc:
            logger.warning(f"Ошибка перехода на страницу #{next_page_number}: {exc}")
            if attempt < retries:
                main_wrapper.wait_random(3, 6)
                continue
            return False, "exception"

    return False, "failed"


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

    # режим работы браузера
    if headless is None:
        headless = DEFAULT_HEADLESS

    # start_time нужен для общего ограничения времени работы скрапера
    # Если он не передан снаружи, начинаем отсчёт с текущего момента
    if start_time is None:
        start_time = time.time()
    
    # URL по тексту запроса
    search_url = build_search_url(query_text)

    # защита от повторной обработки той же ссылки в одном запуске
    seen_urls: Set[str] = set()
    
     # Выбираем случайный User-Agent, чтобы открывать сайт каждый раз с разной маской
    with sync_playwright() as p:
        user_agent = random.choice(USER_AGENTS)
        logger.info(f"Запуск браузера. User-Agent: {user_agent[:50]}...")
        
        # использование прокси
        proxy_config = {}
        use_proxy = False
        if use_proxy:
            proxy_url = get_free_proxy()
            if proxy_url:
                proxy_config = {"proxy": {"server": f"http://{proxy_url}"}}
                logger.info(f"Используется прокси: {proxy_url}")
        
         # Запускаем Chromium с набором аргументов для уменьшения видимости автоматищации 
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
        
        """
        Создаём браузерный контекст (для уменьшения видимости автоматизации):
        - размеры окна
        - user-agent
        - локаль
        - таймзона
        - геолокация
        """
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=user_agent,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            permissions=["geolocation"],
            geolocation={"longitude": 37.6176, "latitude": 55.7558},
        )
        
        # Пытаемся загрузить cookies от прошлых запусков,
        # чтобы сохранить сессию и снизить вероятность повторной капчи
        load_cookies(context)

        # Перехватываем сетевые запросы и блокируем мусорные / рекламные 
        context.route("**/*", block_app_pages)
        
        # Создаём основную страницу поиска и оборачиваем её helper-классом
        main_page = context.new_page()
        main_page.set_default_timeout(PAGE_TIMEOUT_MS)
        main_wrapper = PageWithHumanization(main_page)
        
        # Небольшая обёртка нужна, чтобы при необходимости
        # передать контекст в safe_open_search_page для сохранения cookies
        class ContextWrapper:
            def __init__(self, context):
                self.context = context
        
        context_wrapper = ContextWrapper(context)
        
        try:
            """
            Открываем первую страницу поиска через "безопасную" функцию,
            где уже собраны все первичные проверки:
            stealth, загрузка, капча, баннеры, лишние вкладки, наличие карточек
            """
            success, reason = safe_open_search_page(
                main_wrapper, search_url, context, context_wrapper
            )
            if not success:
                logger.error("Не удалось открыть страницу поиска: %s", reason)
                return
            
            # сколько страниц будем обходить
            max_pages = MAX_ALL_PAGES if all_pages else (pages or 1)
            current_page_number = 1
            current_page_url = search_url
            
            # Основной цикл по страницам поисковой выдачи
            while current_page_number <= max_pages: 
                if max_time > 0 and (time.time() - start_time) > max_time: # лимит времени
                    logger.info(f"Достигнуто максимальное время работы: {max_time} секунд")
                    break
                
                logger.info(f"Обрабатываем страницу поиска #{current_page_number}")
                
                # Собираем карточки и их ссылки с текущей страницы
                items_data = main_wrapper.collect_items_with_selectors()
                logger.info(f"Найдено объявлений: {len(items_data)}")
                
                if not items_data:
                    logger.warning("На странице нет объявлений")
                    break
                
                new_items = []
                existing_items = []
                
                """
                Если включён режим only_new и есть подключение к БД,
                то делим карточки на новые и уже известные,
                чтобы приоритетно обрабатывать новые объявления
                """
                if only_new and conn:
                    for url, idx, card_item in items_data:
                        avito_id = extract_avito_id_from_url(url)
                        if avito_id and is_already_in_db(conn, avito_id, query_text):
                            existing_items.append((url, idx, card_item))
                        else:
                            new_items.append((url, idx, card_item))
                    
                    # Сначала обрабатываем новые объявления, потом существующие
                    # Это позволяет быстро получить новые данные, даже если старых много
                    items_to_process = new_items + existing_items
                    logger.info(f"Из них новых: {len(new_items)}, уже есть в БД: {len(existing_items)}")
                else:
                    items_to_process = items_data
                
                # цикл по карточкам на текущей странице
                for url, idx, card_item in items_to_process:

                    # лимит времени на уровне карточки
                    if max_time > 0 and (time.time() - start_time) > max_time:
                        logger.info("Достигнуто максимальное время работы, прерываем обработку")
                        break
                    
                    # В режиме only_new пропускаем что уже есть в БД
                    if only_new and conn:
                        avito_id = extract_avito_id_from_url(url)
                        if avito_id and is_already_in_db(conn, avito_id, query_text):
                            logger.debug(f"Пропуск существующего объявления: {avito_id}")
                            yield {"_skip_reason": "already_exists"}
                            continue
                    
                    # исключаем повторную обработку
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    
                    logger.debug(f"Обработка объявления: {url[:80]}...")
                    
                    card_page = None
                    
                    try:
                        # пытаемся открыть карточку через клик
                        card_page, opened, status = open_card_by_click(
                        main_wrapper, card_item, context, retries=CARD_OPEN_RETRIES
                        )

                        # Если клик не сработал, то используем fallback:
                        # открываем карточку прямым переходом по URL
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
                                continue
                        
                        # передаем открытую страницу в парсер
                        ad_data = parse_ad_page(card_page, query_text, url)
                        if ad_data is not None:
                            yield ad_data
                            logger.debug(f"Объявление сохранено: {ad_data.get('title', '')[:50]}")
                        
                        # пауза перед открытием след. карточки для уменьшения автоматизации 
                        delay = random.uniform(DELAY_BETWEEN_CARDS_SEC, DELAY_BETWEEN_CARDS_SEC + 2.0)
                        time.sleep(delay)
                        
                    except Exception as e:
                        logger.warning(f"Ошибка при обработке карточки {url[:80]}: {e}")
                        continue
                    
                    finally:
                        # закрываем обработанную страницу
                        if card_page:
                            try:
                                card_page.close()
                            except Exception:
                                pass
                
                # если обработали заданное количество объявлений
                if not all_pages and current_page_number >= max_pages:
                    break
                
                # Формируем URL следующей страницы поиска
                next_page_number = current_page_number + 1
                next_page_url = get_next_page_url(current_page_url, next_page_number)
                
                # Переходим на следующую страницу через отдельную функцию,
                # где уже учтены ретраи, капча, недогрузка, пустая выдача и баннеры
                success, status = go_to_next_page_with_retries(
                    main_wrapper=main_wrapper,
                    context=context,
                    main_page=main_page,
                    next_page_url=next_page_url,
                    next_page_number=next_page_number,
                    retries=2,
                )
                
                if not success:
                    # empty_search / no_items — нормальный конец пагинации.
                    # Остальные статусы означают, что переход остановился из-за проблемы
                    if status in {"empty_search", "no_items"}:
                        logger.info(f"Пагинация завершена естественно: {status}")
                    else:
                        logger.warning(f"Переход остановлен на странице #{next_page_number}: {status}")
                    break
                
                # Между страницами делаем паузу, прогреваем интерфейс
                # и сохраняем cookies текущей сессии
                main_wrapper.wait_random(DELAY_BETWEEN_PAGES_SEC, DELAY_BETWEEN_PAGES_SEC + 2.0)
                main_wrapper.warm_up()
                save_cookies(context)
                
                current_page_number = next_page_number
                current_page_url = next_page_url
                    
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
        finally:

            # при ошибке стараемся корректно завершить сессию:
            # сохраняем cookies и закрываем браузер
            save_cookies(context)
            logger.info("Закрываем браузер")
            browser.close()