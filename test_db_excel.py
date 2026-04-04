import sqlite3
from datetime import datetime
from db import get_connection, create_tables
from cache_service import upsert_ad
from exporter import export_query_to_excel

# Тестовые данные
test_ads = [
    {
        "avito_id": "123456789",
        "query_text": "книга",
        "title": "Война и мир",
        "price": "500 ₽",
        "price_value": 500,
        "currency": "RUB",
        "address": "Москва",
        "description": "Классическое издание",
        "published_at": "Сегодня",
        "views_count": "150 просмотров",
        "url": "https://www.avito.ru/moskva/knigi/voyna_i_mir_123456789",
        "status": "active"
    },
    {
        "avito_id": "987654321",
        "query_text": "книга",
        "title": "Преступление и наказание",
        "price": "350 ₽",
        "price_value": 350,
        "currency": "RUB",
        "address": "Санкт-Петербург",
        "description": "Классика",
        "published_at": "Вчера",
        "views_count": "89 просмотров",
        "url": "https://www.avito.ru/spb/knigi/prestuplenie_i_nakazanie_987654321",
        "status": "active"
    },
    {
        "avito_id": "555555555",
        "query_text": "книга",
        "title": None,
        "price": None,
        "price_value": None,
        "currency": None,
        "address": None,
        "description": None,
        "published_at": None,
        "views_count": None,
        "url": "https://www.avito.ru/moskva/knigi/kniga_555555555",
        "status": "closed"
    }
]

def test_database_and_excel():
    print("=" * 50)
    print("Тест 1: Подключение к БД")
    
    conn = get_connection()
    create_tables(conn)
    print("БД подключена, таблицы созданы")
    
    print("\n" + "=" * 50)
    print("Тест 2: Вставка и обновление данных")
    
    for ad in test_ads:
        result = upsert_ad(conn, ad)
        # Исправленная строка - проверка на None
        title_display = ad.get('title')
        if title_display:
            print(f"  {title_display[:30]}: {result}")
        else:
            print(f"  closed (avito_id={ad['avito_id']}): {result}")
    
    print("\n" + "=" * 50)
    print("Тест 3: Проверка содержимого БД")
    
    cursor = conn.execute("SELECT avito_id, title, price, status FROM ads WHERE query_text = 'книга'")
    rows = cursor.fetchall()
    for row in rows:
        title_display = row['title'] if row['title'] else 'closed'
        price_display = row['price'] if row['price'] else 'N/A'
        print(f"  {row['avito_id']}: {title_display} | {price_display} | {row['status']}")
    
    print("\n" + "=" * 50)
    print("Тест 4: Экспорт в Excel")
    
    output_path = export_query_to_excel(conn, "книга")
    print(f"  Excel сохранён: {output_path}")
    
    conn.close()
    
    print("\n" + "=" * 50)
    print("Тестирование завершено")
    print("Проверьте созданный Excel файл в папке проекта")

if __name__ == "__main__":
    test_database_and_excel()