# Avito Parser

Парсер объявлений Avito с кэшированием в SQLite и экспортом в Excel.

## Стек технологий

- **Playwright** — оптимален для динамических сайтов (как Avito). Поддерживается Python, позволяет работать с реальным браузером, обходить JS и часть защит.
- **humanization** — добавляет "человеческое" поведение (задержки, клики), снижает вероятность блокировок.
- **stealth** — скрывает признаки автоматизации браузера. Важно для стабильной работы на сайтах с защитой (+ loguru как зависимость).
- **sqlite3** — встроенная в Python база данных, не требует установки.
- **openpyxl** — простая библиотека для создания Excel-файлов в Python.
- **argparse** — стандартный модуль Python для CLI.
- **logging** — встроенный инструмент логирования.
- **requests** — для получения бесплатных прокси через API ProxyScrape.
- **playwright-captcha** — опциональная библиотека для автоматического решения капчи.

## Установка

```bash
# Клонировать репозиторий
git clone https://github.com/GlebSergeev54/avito_parser.git
cd avito_parser

# Создать виртуальное окружение
python -m venv venv

# Активировать (Windows)
venv\Scripts\activate

# Активировать (Linux/Mac)
source venv/bin/activate

# Установить зависимости
pip install -r requirements.txt

# Установить браузеры Playwright
playwright install
```

## Запуск
```bash

# Базовый запуск (1 страница)
python main.py "книга"

# Указать количество страниц
python main.py "книга" --pages 3

# Только новые объявления (которых нет в БД)
python main.py "книга" --only-new

# Ограничить время работы (60 секунд)
python main.py "книга" --max-time 60

# Скрытый режим (без окна браузера)
python main.py "книга" --headless

# Все страницы поиска
python main.py "книга" --all-pages
```

## Тестирование
```bash

# Проверка работы кэша (insert/update/skip)
python test_cache.py

# Проверка вспомогательных функций
python test_utils.py

# Проверка БД и экспорта в Excel
python test_db_excel.py

# Эмуляция работы парсера (без реального Avito)
python test_scraper_emulator.py
```
