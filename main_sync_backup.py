import argparse
import logging

from cache_service import upsert_ad
from db import create_tables, get_connection
from exporter import export_query_to_excel
from scraper import iterate_ads


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Avito parser with SQLite cache and Excel export")
    parser.add_argument("query", help="Поисковый запрос на русском")
    parser.add_argument("--pages", type=int, default=1, help="Количество страниц поиска")
    parser.add_argument("--all-pages", action="store_true", help="Обходить все страницы поиска")
    parser.add_argument("--headless", action="store_true", help="Запуск браузера без окна")
    return parser.parse_args()


def validate_ad_data(ad_data: dict) -> tuple[bool, str | None]:
    """
    Проверка критичных полей.
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
    args = parse_args()
    setup_logging()

    logger = logging.getLogger(__name__)
    logger.info("Старт программы. Запрос: %s", args.query)

    conn = get_connection()
    create_tables(conn)

    stats = {
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "skipped_closed": 0,
        "invalid": 0,
    }

    try:
        for ad_data in iterate_ads(
            query_text=args.query,
            pages=args.pages,
            all_pages=args.all_pages,
            headless=args.headless,
        ):
            is_valid, missing_field = validate_ad_data(ad_data)

            # Для closed валидируем мягче: важно наличие avito_id, url, status
            if ad_data.get("status") == "closed":
                if not ad_data.get("avito_id") or not ad_data.get("url") or not ad_data.get("status"):
                    logger.warning("Пропуск closed-объявления: не хватает критичных полей")
                    stats["invalid"] += 1
                    continue
            else:
                if not is_valid:
                    logger.warning(
                        "Пропуск объявления %s: отсутствует критичное поле %s",
                        ad_data.get("url"),
                        missing_field,
                    )
                    stats["invalid"] += 1
                    continue

            result = upsert_ad(conn, ad_data)
            stats[result] += 1

        output_path = export_query_to_excel(conn, args.query)
        logger.info("Excel сохранен: %s", output_path)

        logger.info(
            "Готово. inserted=%s updated=%s skipped=%s skipped_closed=%s invalid=%s",
            stats["inserted"],
            stats["updated"],
            stats["skipped"],
            stats["skipped_closed"],
            stats["invalid"],
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()