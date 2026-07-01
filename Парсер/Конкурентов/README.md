# Парсер сообществ взаимных активностей (Instagram)

Скрипт ищет сообщества взаимной активности, где продвигаются **только Instagram-профили**.

## Что делает

1. Ищет в интернете по целевым запросам (по умолчанию через Bing RSS, без капчи).
2. Собирает ссылки на сообщества `t.me` из результатов поиска и найденных страниц.
   - Включает встроенные seed-источники по Instagram engagement pods.
3. Анализирует публичные Telegram-превью (`t.me/s/<username>`).
4. Фильтрует сообщества:
   - есть признаки Instagram;
   - есть признаки взаимной активности (лайки/комменты/engagement);
   - нет признаков других платформ (VK, TikTok, YouTube и т.д.).
5. Сохраняет результаты в `JSON` и `CSV`.

## Установка

```bash
pip install -r requirements.txt
```

## Запуск

```bash
python parser_instagram_communities.py
```

## Полезные параметры

```bash
python parser_instagram_communities.py \
  --max-source-pages 100 \
  --out-json result.json \
  --out-csv result.csv
```

Дополнительные запросы:

```bash
python parser_instagram_communities.py \
  --search-engine ddg \
  --ddg-pages 3
```

Дополнительные запросы:

```bash
python parser_instagram_communities.py \
  --query "взаимные лайки инстаграм t.me" \
  --query "instagram engagement telegram group"
```

Дополнительные источники (seed-страницы):

```bash
python parser_instagram_communities.py \
  --seed-url "https://example.com/page-with-telegram-links"
```

Известные username можно добавить вручную:

```bash
python parser_instagram_communities.py \
  --seed-username "my_instagram_engagement_group"
```

Русскоязычный конкурентный сбор + жёсткая очистка:

```bash
python parser_instagram_communities.py \
  --ru-sources \
  --ru-only \
  --strict-filter
```

Сделать удобную читаемую таблицу из JSON:

```bash
python make_readable_table.py \
  --input-json instagram_communities_ru_strict_relaxed.json \
  --out-csv instagram_communities_ru_readable.csv \
  --out-md instagram_communities_ru_readable.md
```

Глобальный сбор (все площадки: Telegram/VK/Facebook/Discord/WhatsApp/Reddit + статьи/сервисы):

```bash
python parser_all_instagram_mutual_sources.py
```

Файлы после запуска:
- `all_instagram_mutual_candidates.csv` — все найденные кандидаты
- `instagram_mutual_communities.csv` — релевантные сообщества
- `instagram_mutual_services.csv` — релевантные сервисы/статьи

## Формат результатов

- `is_match = true` — кандидат прошёл фильтр как Instagram-only сообщество взаимной активности.
- `matched_instagram_terms` — какие Instagram-маркеры найдены.
- `matched_mutual_terms` — какие маркеры взаимной активности найдены.
- `matched_non_instagram_terms` — маркеры других платформ (если есть).

## Важно

- В Telegram есть приватные сообщества (инвайт-ссылки), их нельзя полноценно проверить без доступа.
- Поисковая выдача и Telegram могут ограничивать частые запросы, поэтому в скрипт добавлены задержки.
