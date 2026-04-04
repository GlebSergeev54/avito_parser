"""
Эмулятор для тестирования scraper.py без реального доступа к Avito.
"""

import sys
import logging
from typing import Dict, Any, List, Optional, Tuple
from unittest.mock import MagicMock, patch
import time

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


class MockPage:
    """Эмуляция страницы Playwright."""
    
    def __init__(self, url: str = "", content: str = ""):
        self.url = url
        self._content = content
        self._closed = False
        self._calls = []
    
    def goto(self, url: str, **kwargs):
        self._calls.append(("goto", url))
        self.url = url
        return None
    
    def locator(self, selector: str):
        return MockLocator(selector, self)
    
    def text_content(self):
        return self._content
    
    def set_extra_http_headers(self, headers: Dict):
        self._calls.append(("set_headers", headers))
    
    def close(self):
        self._closed = True
    
    def reload(self):
        self._calls.append(("reload",))
    
    def evaluate(self, script: str):
        self._calls.append(("evaluate", script[:50]))
    
    def wait_for_timeout(self, ms: int):
        pass
    
    def wait_for_load_state(self, state: str, timeout: int = None):
        pass
    
    def set_default_timeout(self, timeout: int):
        """Добавленный метод для совместимости."""
        self._calls.append(("set_default_timeout", timeout))
    
    @property
    def closed(self):
        return self._closed


class MockLocator:
    """Эмуляция локатора Playwright."""
    
    def __init__(self, selector: str, page: MockPage):
        self.selector = selector
        self.page = page
    
    def all(self):
        if self.selector == '[data-marker="item"]':
            return [MockElement(i, self.page) for i in range(3)]
        return []
    
    def first(self):
        return MockElement(0, self.page)
    
    def count(self):
        if self.selector == '[data-marker="item"]':
            return 3
        return 1
    
    def is_visible(self):
        return True
    
    def click(self, **kwargs):
        pass


class MockElement:
    """Эмуляция HTML элемента."""
    
    def __init__(self, index: int, page: MockPage):
        self.index = index
        self.page = page
    
    def get_attribute(self, name: str):
        if name == "href":
            return f"/test/ad_{self.index}_123456789"
        return None
    
    def locator(self, selector: str):
        return MockLocator(selector, self.page)
    
    def click(self, **kwargs):
        pass


class MockBrowser:
    """Эмуляция браузера Playwright."""
    
    def __init__(self):
        self._closed = False
    
    def new_context(self, **kwargs):
        return MockContext()
    
    def close(self):
        self._closed = True


class MockContext:
    """Эмуляция контекста браузера."""
    
    def __init__(self):
        self.pages = []
    
    def new_page(self):
        page = MockPage()
        self.pages.append(page)
        return page
    
    def cookies(self):
        return []
    
    def add_cookies(self, cookies):
        pass
    
    def route(self, pattern: str, handler):
        pass
    
    def close(self):
        pass


def test_guard_page_state():
    """Тест метода guard_page_state."""
    print("\n" + "=" * 60)
    print("Тест guard_page_state")
    print("=" * 60)
    
    from scraper import PageWithHumanization
    
    test_cases = [
        ("", "loading"),
        ("<html><body>объявление снято с публикации</body></html>", "closed"),
        ("<html><body>captcha iframe</body></html>", "blocked"),
        ("<html><body>нормальная страница с объявлениями</body></html>", "ok"),
    ]
    
    for content, expected in test_cases:
        mock_page = MockPage(content=content)
        wrapper = PageWithHumanization(mock_page)
        
        wrapper.is_blocked_page = MagicMock(return_value=(expected == "blocked"))
        wrapper.get_page_text = MagicMock(return_value=content.lower())
        
        is_ok, status = wrapper.guard_page_state()
        print(f"   Контент: '{content[:40]}...' -> статус: {status} (ожидался: {expected})")
        assert status == expected, f"Ожидался {expected}, получен {status}"
    
    print("   Все тесты guard_page_state пройдены!")


def test_is_blocked_page_no_false_positive():
    """
    Специальный тест: проверяем, что is_blocked_page НЕ срабатывает ложно.
    Это критично, чтобы скрапер не думал, что капча есть, когда её нет.
    """
    print("\n" + "=" * 60)
    print("Тест is_blocked_page (ложные срабатывания)")
    print("=" * 60)
    
    from scraper import PageWithHumanization
    
    # Нормальные страницы, на которых НЕТ капчи
    normal_contents = [
        "<html><body><h1>Книги</h1><div data-marker='item'>Объявление 1</div></body></html>",
        "<html><body><div class='iva-item-content'>Обычная карточка</div></body></html>",
        "<html><body><span>Цена: 500 ₽</span></body></html>",
        "<html><body>Просто длинный текст без признаков капчи</body></html>",
    ]
    
    print("   Проверка нормальных страниц (должны НЕ определяться как капча):")
    
    for content in normal_contents:
        mock_page = MockPage(content=content)
        wrapper = PageWithHumanization(mock_page)
        
        # Мокаем wait_for_page_load и get_page_text
        wrapper.wait_for_page_load = MagicMock(return_value=True)
        wrapper.get_page_text = MagicMock(return_value=content.lower())
        
        # Мокаем page.locator для body
        mock_body_locator = MagicMock()
        mock_body_locator.count.return_value = 1
        wrapper.page.locator = MagicMock(return_value=mock_body_locator)
        
        is_blocked = wrapper.is_blocked_page()
        status = "БЛОКИРОВКА" if is_blocked else "нормально"
        print(f"   - {content[:40]}... -> {status}")
        
        # нормальная страница НЕ должна определяться как капча
        assert is_blocked is False, f"Ложное срабатывание! Страница определена как капча: {content[:50]}"
    
    print("\n   Проверка страниц с капчей (должны определяться):")
    
    # Страницы, на которых ЕСТЬ капча
    captcha_contents = [
        "<html><body><iframe src='https://captcha.com'></iframe></body></html>",
        "<html><body><div class='captcha-container'>Подтвердите, что вы человек</div></body></html>",
        "<html><body><div id='captcha'>Проверка безопасности</div></body></html>",
        "<html><body><span>captcha verification required</span></body></html>",
    ]
    
    for content in captcha_contents:
        mock_page = MockPage(content=content)
        wrapper = PageWithHumanization(mock_page)
        
        wrapper.wait_for_page_load = MagicMock(return_value=True)
        wrapper.get_page_text = MagicMock(return_value=content.lower())
        
        mock_body_locator = MagicMock()
        mock_body_locator.count.return_value = 1
        wrapper.page.locator = MagicMock(return_value=mock_body_locator)
        
        is_blocked = wrapper.is_blocked_page()
        status = "БЛОКИРОВКА" if is_blocked else "нормально"
        print(f"   - {content[:40]}... -> {status}")
        
        # Страница с капчей ДОЛЖНА определяться
        assert is_blocked is True, f"Капча не обнаружена: {content[:50]}"
    
    print("\n   Тест is_blocked_page пройден! Ложных срабатываний нет.")


def test_collect_items_with_selectors():
    """Тест сбора ссылок."""
    print("\n" + "=" * 60)
    print("Тест collect_items_with_selectors")
    print("=" * 60)
    
    from scraper import PageWithHumanization
    
    mock_page = MockPage()
    wrapper = PageWithHumanization(mock_page)
    
    items = wrapper.collect_items_with_selectors()
    print(f"   Собрано ссылок: {len(items)}")
    
    for url, idx, _ in items:
        print(f"   - {url}")
    
    if len(items) > 0:
        print("   Тест collect_items_with_selectors пройден!")
    else:
        print("   ВНИМАНИЕ: Собрано 0 ссылок (мок требует доработки)")


def test_is_already_in_db():
    """Тест проверки БД."""
    print("\n" + "=" * 60)
    print("Тест is_already_in_db")
    print("=" * 60)
    
    from scraper import is_already_in_db
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    
    mock_cursor.fetchone.return_value = (1,)
    result = is_already_in_db(mock_conn, "123456789", "тест")
    print(f"   Существующая запись: {result} (ожидался True)")
    assert result is True
    
    mock_cursor.fetchone.return_value = None
    result = is_already_in_db(mock_conn, "987654321", "тест")
    print(f"   Новая запись: {result} (ожидался False)")
    assert result is False
    
    result = is_already_in_db(None, "123456789", "тест")
    print(f"   Нет соединения: {result} (ожидался False)")
    assert result is False
    
    print("   Все тесты is_already_in_db пройдены!")


def test_get_next_page_url():
    """Тест формирования URL следующей страницы."""
    print("\n" + "=" * 60)
    print("Тест get_next_page_url")
    print("=" * 60)
    
    from scraper import get_next_page_url
    
    test_cases = [
        ("https://www.avito.ru/all?q=книга", 2, "https://www.avito.ru/all?q=книга&p=2"),
        ("https://www.avito.ru/all?q=книга&p=1", 2, "https://www.avito.ru/all?q=книга&p=2"),
        ("https://www.avito.ru/all?q=книга&sort=date", 3, "https://www.avito.ru/all?q=книга&sort=date&p=3"),
    ]
    
    for url, page_num, expected in test_cases:
        result = get_next_page_url(url, page_num)
        print(f"   {url} + p={page_num} -> {result}")
        assert result == expected
    
    print("   Все тесты get_next_page_url пройдены!")


def test_go_to_next_page_with_retries():
    """Тест перехода на следующую страницу."""
    print("\n" + "=" * 60)
    print("Тест go_to_next_page_with_retries")
    print("=" * 60)
    
    from scraper import go_to_next_page_with_retries, PageWithHumanization
    
    mock_page = MockPage()
    wrapper = PageWithHumanization(mock_page)
    wrapper.goto_with_retries = MagicMock(return_value=(True, "success"))
    wrapper.guard_page_state = MagicMock(return_value=(True, "ok"))
    wrapper.has_items = MagicMock(return_value=True)
    wrapper.is_empty_search = MagicMock(return_value=False)
    wrapper.handle_captcha = MagicMock(return_value=True)
    
    mock_context = MockContext()
    mock_main_page = MockPage()
    
    success, status = go_to_next_page_with_retries(
        main_wrapper=wrapper,
        context=mock_context,
        main_page=mock_main_page,
        next_page_url="https://avito.ru/page2",
        next_page_number=2,
        retries=2,
    )
    
    print(f"   Результат: success={success}, status={status}")
    assert success is True
    
    print("   Тест go_to_next_page_with_retries пройден!")


def test_handle_captcha():
    """Тест обработки капчи."""
    print("\n" + "=" * 60)
    print("Тест handle_captcha")
    print("=" * 60)
    
    from scraper import PageWithHumanization
    
    mock_page = MockPage()
    wrapper = PageWithHumanization(mock_page)
    
    # Тест 1: нет капчи
    wrapper.is_blocked_page = MagicMock(return_value=False)
    result = wrapper.handle_captcha()
    print(f"   Нет капчи: {result} (ожидался True)")
    assert result is True
    
    # Тест 2: есть капча, try_solve_captcha решает её
    wrapper.is_blocked_page = MagicMock(return_value=True)
    
    with patch("scraper.try_solve_captcha", return_value=True):
        with patch.object(wrapper, 'wait_random') as mock_wait:
            result = wrapper.handle_captcha()
            print(f"   Капча решена автоматически: {result} (ожидался True)")
            assert result is True
    
    # Тест 3: есть капча, ручное решение
    wrapper.is_blocked_page = MagicMock(return_value=True)
    
    with patch("scraper.try_solve_captcha", return_value=False):
        with patch.object(wrapper, 'wait_random') as mock_wait:
            is_blocked_values = [True, True, True, False]
            wrapper.is_blocked_page = MagicMock(side_effect=is_blocked_values)
            
            with patch("time.sleep") as mock_sleep:
                result = wrapper.handle_captcha()
                print(f"   Капча решена вручную: {result} (ожидался True)")
                assert result is True
    
    print("   Тест handle_captcha пройден!")


def run_emulator_test():
    """Запуск полной эмуляции iterate_ads."""
    print("\n" + "=" * 60)
    print("Тестирование scraper.py через эмулятор")
    print("=" * 60)
    
    with patch("scraper.sync_playwright") as mock_playwright:
        mock_playwright_instance = MagicMock()
        mock_browser = MockBrowser()
        mock_playwright_instance.chromium.launch.return_value = mock_browser
        mock_playwright.return_value.__enter__.return_value = mock_playwright_instance
        
        with patch("scraper.stealth_sync") as mock_stealth:
            with patch("scraper.Humanization") as mock_humanization:
                with patch("scraper.save_cookies") as mock_save_cookies:
                    with patch("scraper.load_cookies") as mock_load_cookies:
                        mock_humanization.return_value = MagicMock()
                        mock_stealth.return_value = None
                        
                        from scraper import iterate_ads
                        
                        print("\n1. Запуск iterate_ads с эмуляцией...")
                        
                        test_params = {
                            "query_text": "тест",
                            "pages": 1,
                            "all_pages": False,
                            "headless": True,
                            "max_time": 0,
                            "only_new": False,
                            "conn": None,
                            "start_time": None,
                        }
                        
                        results = []
                        try:
                            for ad_data in iterate_ads(**test_params):
                                results.append(ad_data)
                                print(f"   Получено объявление: {ad_data.get('title', 'no title')}")
                        except Exception as e:
                            print(f"   Ошибка: {e}")
                            import traceback
                            traceback.print_exc()
                        
                        print(f"\n2. Результат: получено {len(results)} объявлений")
                        
                        print("\n3. Проверка вызовов моков:")
                        print(f"   playwright.chromium.launch вызван: {mock_playwright_instance.chromium.launch.called}")
                        print(f"   stealth_sync вызван: {mock_stealth.called}")
                        print(f"   Humanization вызван: {mock_humanization.called}")
                        
                        print("\n" + "=" * 60)
                        print("Тестирование завершено")
                        print("=" * 60)


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("ЗАПУСК ЭМУЛЯТОРА ДЛЯ ТЕСТИРОВАНИЯ SCRAPER")
    print("=" * 60)
    
    test_guard_page_state()
    test_is_blocked_page_no_false_positive()  # <-- НОВЫЙ ТЕСТ НА ЛОЖНЫЕ СРАБАТЫВАНИЯ
    test_collect_items_with_selectors()
    test_is_already_in_db()
    test_get_next_page_url()
    test_go_to_next_page_with_retries()
    test_handle_captcha()
    
    run_emulator_test()
    
    print("\n" + "=" * 60)
    print("ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
    print("=" * 60)