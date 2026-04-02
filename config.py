from pathlib import Path

# Базовая директория проекта
BASE_DIR = Path(__file__).resolve().parent

# БД
DB_PATH = BASE_DIR / "avito_cache.db"

# Таймауты
PAGE_TIMEOUT_MS = 60_000
NAVIGATION_TIMEOUT_MS = 60_000

# Количество попыток
CARD_OPEN_RETRIES = 3

# Паузы
DELAY_BETWEEN_CARDS_SEC = 5.0
DELAY_BETWEEN_PAGES_SEC = 8.0
DELAY_BETWEEN_RETRIES_SEC = 6.0

# Пагинация
DEFAULT_PAGES = 1
MAX_ALL_PAGES = 100

# Режим браузера
DEFAULT_HEADLESS = False

# Excel
EXCEL_SHEET_NAME = "Avito Ads"

# Логирование
LOG_LEVEL = "INFO"

# Анти-детект настройки
RANDOM_START_DELAY = (3, 8)
RANDOM_SCROLL = (100, 500)

# Список User-Agent для ротации
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# Капча
CAPTCHA_MANUAL_TIMEOUT_SEC = 120
CAPTCHA_RETRY_DELAYS = [3, 8, 15]  # секунды между попытками при сетевых ошибках

# Прокси (опционально)
PROXY_ENABLED = False
PROXY_LIST = []  # ["http://user:pass@ip:port", ...]

# Прокси настройки
PROXY_TIMEOUT_SEC = 10
PROXY_MAX_RETRIES = 3
PROXY_ROTATION_INTERVAL = 50  # количество запросов до смены прокси