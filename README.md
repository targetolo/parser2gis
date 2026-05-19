# 2GIS Parser Web

Веб-интерфейс для парсинга данных с 2GIS.

## Деплой на Railway

1. Залей папку на GitHub
2. Зайди на [railway.app](https://railway.app)
3. New Project → Deploy from GitHub repo
4. Выбери репозиторий
5. Railway автоматически найдёт Dockerfile и задеплоит

После деплоя Railway даст тебе URL вида `https://твой-проект.up.railway.app`

## Локальный запуск

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Открой http://localhost:8000

## Использование

1. Вставь ссылку с поиском 2GIS (например `https://2gis.ru/spb/search/кафе`)
2. Выбери формат: xlsx / csv / json
3. Укажи максимум записей
4. Нажми **НАЧАТЬ ПАРСИНГ**
5. Скачай файл

## Важно

- Парсер использует Chromium в headless-режиме
- Один запрос может занять от 30 секунд до нескольких минут
- Файлы хранятся во временной папке `/tmp/parser_results`
