from sqlite3 import Connection

from utils import now_iso, normalize_for_compare


COMPARE_FIELDS = ("status", "price", "title", "description")


def get_existing_ad(conn: Connection, avito_id: str, query_text: str):
    """
    Ищет существующую запись в кеше по составному ключу.
    """
    cursor = conn.execute(
        """
        SELECT *
        FROM ads
        WHERE avito_id = ? AND query_text = ?
        """,
        (avito_id, query_text),
    )
    return cursor.fetchone()


def insert_ad(conn: Connection, ad_data: dict) -> None:
    """
    Вставляет новое объявление в кеш.
    """
    now = now_iso()

    conn.execute(
        """
        INSERT INTO ads (
            avito_id,
            query_text,
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
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ad_data["avito_id"],
            ad_data["query_text"],
            ad_data.get("title"),
            ad_data.get("price"),
            ad_data.get("address"),
            ad_data.get("description"),
            ad_data.get("published_at"),
            ad_data.get("views_count"),
            ad_data.get("url"),
            ad_data["status"],
            now,
            now,
        ),
    )
    conn.commit()


def update_ad(conn: Connection, ad_data: dict) -> None:
    """
    Обновляет существующую запись.
    """
    now = now_iso()

    conn.execute(
        """
        UPDATE ads
        SET
            title = ?,
            price = ?,
            address = ?,
            description = ?,
            published_at = ?,
            views_count = ?,
            url = ?,
            status = ?,
            updated_at_cache = ?
        WHERE avito_id = ? AND query_text = ?
        """,
        (
            ad_data.get("title"),
            ad_data.get("price"),
            ad_data.get("address"),
            ad_data.get("description"),
            ad_data.get("published_at"),
            ad_data.get("views_count"),
            ad_data.get("url"),
            ad_data["status"],
            now,
            ad_data["avito_id"],
            ad_data["query_text"],
        ),
    )
    conn.commit()


def has_changes(existing_row, ad_data: dict) -> bool:
    """
    Проверяет, изменились ли поля, указанные в ТЗ.
    """
    for field in COMPARE_FIELDS:
        old_value = normalize_for_compare(existing_row[field])
        new_value = normalize_for_compare(ad_data.get(field))
        if old_value != new_value:
            return True
    return False


def upsert_ad(conn: Connection, ad_data: dict) -> str:
    """
    Логика кеша по ТЗ:
    - если запись новая и active -> insert
    - если запись новая и closed -> skip
    - если запись есть и изменились нужные поля -> update
    - иначе skip
    Возвращает статус действия: inserted / updated / skipped / skipped_closed
    """
    existing = get_existing_ad(conn, ad_data["avito_id"], ad_data["query_text"])

    if existing is None:
        if ad_data["status"] == "closed":
            return "skipped_closed"
        insert_ad(conn, ad_data)
        return "inserted"

    if has_changes(existing, ad_data):
        update_ad(conn, ad_data)
        return "updated"

    return "skipped"