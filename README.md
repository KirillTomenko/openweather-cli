# Weather CLI (OpenWeather)

Интерактивное CLI-приложение на Python для получения **текущей погоды** через [OpenWeather API](https://openweathermap.org/api).

## Возможности

- **Поиск по городу**: вводите название города (например, `Москва`).
- **Поиск по координатам**: режим ввода `lat/lon`.
- **Русский язык и °C**: `lang=ru`, `units=metric`.
- **Ретраи при сетевых проблемах**: таймауты/обрывы соединения и ответы сервера \(5xx\).
- **Локальный кеш**: сохранение последнего успешного ответа в `weather_cache.json` на **3 часа**.
- **Понятные ошибки**: сообщения выводятся в stderr.

## Демонстрация

![Main Menu](assets/main-menu.png)

![Weather Output](assets/weather-output.png)

![Coordinates](assets/coords-search.png)

![Errors](assets/error-handling.png)

## Требования

- **Python**: 3.8+
- **OpenWeather API key**: создайте ключ в кабинете OpenWeather

## Установка

Склонируйте репозиторий и установите зависимости.

```bash
git clone https://github.com/KirillTomenko/openweather-cli.git
cd openweather-cli
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

Если `requirements.txt` отсутствует, установите вручную:

```bash
pip install requests python-dotenv
```

## Настройка API-ключа

Создайте файл `.env` в корне проекта:

```env
API_KEY=ваш_ключ_openweather
```

Приложение читает переменную `API_KEY` из `.env` при запуске.

## Запуск

```bash
python weather_app.py
```

После запуска приложение ждёт команду в приглашении:

- **Название города**: любой ввод, кроме `0` и `2` (например, `Санкт-Петербург`)
- **`2`**: перейти в режим ввода координат
- **`0`**: выход

## Как работает кеш

- Кеш хранится в файле `weather_cache.json`.
- TTL кеша: **3 часа**.
- Кеш используется как **фолбэк**, если:
  - не удалось получить координаты/погоду из API,
  - и в кеше есть свежие данные для того же города.

## Частые ошибки

- **`API_KEY не найден` / `API_KEY не настроен`**: проверьте `.env` и формат `API_KEY=...`
- **401 Unauthorized**: неверный ключ OpenWeather
- **429 Too Many Requests**: срабатывает ожидание и повтор запросов
- **Некорректный формат координат**: используйте числа (например `55.75` и `37.62`)

## Структура проекта

- `weather_app.py` — основная логика CLI
- `.env` — API-ключ (не коммитьте в публичный репозиторий)
- `weather_cache.json` — локальный кеш
- `assets/` — скриншоты для README