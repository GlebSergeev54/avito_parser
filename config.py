from pathlib import Path

# Базовая директория проекта
BASE_DIR = Path(__file__).resolve().parent

# БД
DB_PATH = BASE_DIR / "avito_cache.db"

# Таймауты ожидания загрузки элементов на странице в мс
PAGE_TIMEOUT_MS = 60_000
NAVIGATION_TIMEOUT_MS = 60_000

# Количество попыток открыть объявление
CARD_OPEN_RETRIES = 3

# Паузы между действиями в барузере в секундах
# Снижение нагрузки на сервер и имитация поведения человека
DELAY_BETWEEN_CARDS_SEC = 5.0
DELAY_BETWEEN_PAGES_SEC = 8.0
DELAY_BETWEEN_RETRIES_SEC = 6.0

DEFAULT_PAGES = 1 # мин количество страниц для парсинга
MAX_ALL_PAGES = 100 # макс количество страниц для парсинга

# Режим браузера, видимость графического окна
DEFAULT_HEADLESS = False

# Название Excel файла
EXCEL_SHEET_NAME = "Avito Ads"

# Логирование
LOG_LEVEL = "INFO"

# Анти-детект настройки, имитирующие поведение человека в секундах
RANDOM_START_DELAY = (3, 8) # открытие браузера и ввод запроса
RANDOM_SCROLL = (100, 500) # скорость пролистывания страницы

# Список User-Agent для ротации
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# Капча
CAPTCHA_MANUAL_TIMEOUT_SEC = 120 # время в секундах на решение пользователем 
CAPTCHA_RETRY_DELAYS = [3, 8, 15]  # секунды между попытками при сетевых ошибках

# Прокси (опционально)
PROXY_ENABLED = False
PROXY_LIST = []  # ["http://user:pass@ip:port", ...]

# Настройки прокси в секундах
PROXY_TIMEOUT_SEC = 10 # время для подключения прокси
PROXY_MAX_RETRIES = 3 # количество повторных попыток
PROXY_ROTATION_INTERVAL = 50  # количество запросов до смены прокси