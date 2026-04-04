"""
Модуль main.py - точка входа в программу

- Парсинг аргументов командной строки
- Настройку логирования
- Инициализацию базы данных
- Запуск парсера (iterate_ads)
- Обработку полученных объявлений
- Экспорт результатов в Excel
- Сбор и вывод статистики
"""

import argparse
import logging
import time

from cache_service import upsert_ad
from db import create_tables, get_connection
from exporter import export_query_to_excel
from scraper import iterate_ads


def setup_logging() -> None:
    """
    система логирования
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def parse_args():
    """
    Парсит аргументы командной строки.
    
    Обязательные аргументы:
        query - поисковый запрос на русском языке
    
    Опциональные аргументы:
        --pages       количество страниц поиска (по умолчанию 1)
        --all-pages   все страницы
        --headless    запустить браузер без окна
        --max-time    максимальное время работы в секундах (0 = без ограничений)
        --only-new    парсить только объявления, которых нет в БД
    
    возвращает
        argparse.Namespace: объект с атрибутами для каждого аргумента
    """

    parser = argparse.ArgumentParser(description="Avito parser with SQLite cache and Excel export")
    parser.add_argument("query", help="Поисковый запрос на русском")
    parser.add_argument("--pages", type=int, default=1, help="Количество страниц поиска")
    parser.add_argument("--all-pages", action="store_true", help="Обходить все страницы поиска")
    parser.add_argument("--headless", action="store_true", help="Запуск браузера без окна")
    
    # новые параметры
    parser.add_argument("--max-time", type=int, default=0, 
                        help="Максимальное время работы в секундах (0 = без ограничений)")
    parser.add_argument("--only-new", action="store_true", 
                        help="Парсить только новые объявления (которых нет в БД)")
    
    return parser.parse_args()


def validate_ad_data(ad_data: dict) -> tuple[bool, str | None]:
    """
    Проверка критичных полей в объявлении
    - avito_id: идентификатор объявления
    - title: название
    - price: цена
    - published_at: дата публикации
    - views_count: количество просмотров
    - url: ссылка
    - status: статус (active/closed)

    возвращает:
        tuple[bool, str | None]: (валидно, имя отсутствующего поля)
        - (True, None) - все поля заполнены
        - (False, "title") - нет заголовка, и т.д.
    """
    required_fields = [
        "avito_id",
        "title",
        "price",
        "published_at",
        "views_count",
        "url",
        "status",
    ]

    for field in required_fields:
        if not ad_data.get(field):
            return False, field

    return True, None


def main():
    """
    Главная функция программы
    
    1. Парсинг аргументов командной строки
    2. Логирование
    3. Подключение к БД и создание таблиц
    4. Инициализация статистики
    5. Запуск парсера (iterate_ads) - получение объявлений по одному
    6. Для каждого объявления:
       - Пропуск already_exists (режим --only-new)
       - Валидация данных (разная для active и closed)
       - Сохранение/обновление в БД через upsert_ad
       - Обновление статистики
    7. Экспорт всех объявлений по запросу в Excel
    8. Вывод итоговой статистики
    """
    args = parse_args()
    setup_logging()

    logger = logging.getLogger(__name__)
    logger.info("Старт программы. Запрос: %s", args.query)
    
    start_time = time.time()

    conn = get_connection()
    create_tables(conn)
    
    # статистика 
    stats = {
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "skipped_closed": 0,
        "invalid": 0,
        "skipped_existing": 0,  
    }

    try:
        # Основной цикл: получаем объявления от парсера
        for ad_data in iterate_ads(
            query_text=args.query,
            pages=args.pages,
            all_pages=args.all_pages,
            headless=args.headless,
            max_time=args.max_time,      
            only_new=args.only_new,      
            conn=conn,                   
            start_time=start_time,       
        ):
            # Для already_exists пропускаем сразу
            if ad_data.get("_skip_reason") == "already_exists":
                stats["skipped_existing"] += 1
                continue
            
             # Валидация критичных полей
            is_valid, missing_field = validate_ad_data(ad_data)

            # Для closed объявлений валидируем только по avito_id, url, status
            if ad_data.get("status") == "closed":
                if not ad_data.get("avito_id") or not ad_data.get("url") or not ad_data.get("status"):
                    logger.warning("Пропуск closed-объявления: не хватает критичных полей")
                    stats["invalid"] += 1
                    continue
            else:
                # active объявление требует всех полей
                if not is_valid:
                    logger.warning(
                        "Пропуск объявления %s: отсутствует критичное поле %s",
                        ad_data.get("url"),
                        missing_field,
                    )
                    stats["invalid"] += 1
                    continue

            # Сохраняем или обновляем объявление в БД
            result = upsert_ad(conn, ad_data)
            stats[result] += 1

        # Экспорт всех объявлений по запросу в Excel
        output_path = export_query_to_excel(conn, args.query)
        logger.info("Excel сохранен: %s", output_path)

        # Итоговая статистика
        logger.info(
            "Готово. inserted=%s updated=%s skipped=%s skipped_closed=%s invalid=%s skipped_existing=%s",
            stats["inserted"],
            stats["updated"],
            stats["skipped"],
            stats["skipped_closed"],
            stats["invalid"],
            stats["skipped_existing"],
        )
    finally:
        conn.close()

# точка входа при запуске скрипта напрямую
if __name__ == "__main__":
    main()