from pathlib import Path
from sqlite3 import Connection

from openpyxl import Workbook

from config import BASE_DIR, EXCEL_SHEET_NAME
from utils import now_iso, safe_filename


def export_query_to_excel(conn: Connection, query_text: str) -> Path:
    """
    Выгружает данные по query_text в Excel.
    """
    cursor = conn.execute(
        """
        SELECT
            query_text,
            avito_id,
            title,
            price,
            address,
            description,
            published_at,
            views_count,
            url,
            status,
            created_at_cache,
            updated_at_cache
        FROM ads
        WHERE query_text = ?
        ORDER BY id
        """,
        (query_text,),
    )
    rows = cursor.fetchall()

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = EXCEL_SHEET_NAME

    headers = [
        "Поисковый запрос",
        "Номер объявления",
        "Название",
        "Цена",
        "Адрес",
        "Описание",
        "Дата публикации",
        "Кол-во просмотров",
        "Ссылка на объявление",
        "Статус объявления",
        "Время добавления в кеш",
        "Время последнего обновления в кеше",
    ]
    worksheet.append(headers)

    for row in rows:
        worksheet.append(
            [
                row["query_text"],
                row["avito_id"],
                row["title"],
                row["price"],
                row["address"],
                row["description"],
                row["published_at"],
                row["views_count"],
                row["url"],
                row["status"],
                row["created_at_cache"],
                row["updated_at_cache"],
            ]
        )

    timestamp = now_iso().replace(":", "-")
    filename = f"{safe_filename(query_text)}_{timestamp}.xlsx"
    output_path = BASE_DIR / filename
    workbook.save(output_path)

    return output_path