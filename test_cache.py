# test_cache.py
from db import get_connection, create_tables
from cache_service import upsert_ad

conn = get_connection()
create_tables(conn)

# Вставляем объявление
ad = {
    "avito_id": "999999999",
    "query_text": "тест",
    "title": "Тестовое объявление",
    "price": "100 ₽",
    "address": "Москва",
    "description": "Описание",
    "published_at": "Сегодня",
    "views_count": "10",
    "url": "https://avito.ru/test_999999999",
    "status": "active"
}

print("Первый запуск (должен быть inserted):")
result1 = upsert_ad(conn, ad)
print(f"  Результат: {result1}")

# Обновляем цену
ad["price"] = "200 ₽"
ad["title"] = "Изменённое название"

print("\nВторой запуск (должен быть updated):")
result2 = upsert_ad(conn, ad)
print(f"  Результат: {result2}")

# Третий запуск без изменений
print("\nТретий запуск (должен быть skipped):")
result3 = upsert_ad(conn, ad)
print(f"  Результат: {result3}")

conn.close()