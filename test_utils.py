# test_utils.py
from utils import normalize_href, is_ad_url, extract_avito_id_from_url, build_search_url

print("Тест normalize_href:")
print(f"  /test/123 → {normalize_href('/test/123')}")
print(f"  #anchor → {normalize_href('#anchor')}")
print(f"  javascript:void(0) → {normalize_href('javascript:void(0)')}")

print("\nТест is_ad_url:")
print(f"  https://www.avito.ru/moskva/knigi/kniga_123456789 → {is_ad_url('https://www.avito.ru/moskva/knigi/kniga_123456789')}")
print(f"  https://www.avito.ru/profile → {is_ad_url('https://www.avito.ru/profile')}")
print(f"  https://google.com → {is_ad_url('https://google.com')}")

print("\nТест extract_avito_id_from_url:")
print(f"  https://avito.ru/kniga_123456789 → {extract_avito_id_from_url('https://avito.ru/kniga_123456789')}")
print(f"  https://avito.ru/kniga → {extract_avito_id_from_url('https://avito.ru/kniga')}")

print("\nТест build_search_url:")
print(f"  книга → {build_search_url('книга')}") 