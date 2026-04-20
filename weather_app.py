#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weather App — Получение погоды через OpenWeather API
Автор: Kirill Tomenko
"""
import os
import sys
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

import requests
from dotenv import load_dotenv

from cache import get_cached, set_cached

load_dotenv()
API_KEY = os.getenv("API_KEY")

GEOCODING_URL = "https://api.openweathermap.org/geo/1.0/direct"
WEATHER_URL   = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL  = "https://api.openweathermap.org/data/2.5/forecast"
AIR_POLL_URL  = "http://api.openweathermap.org/data/2.5/air_pollution"

CACHE_FILE      = "weather_cache.json"
CACHE_TTL_HOURS = 3
MAX_RETRIES     = 3
RETRY_DELAYS    = [1, 2, 4]

# ---------------------------------------------------------------------------
# AQI: таблицы перевода
# ---------------------------------------------------------------------------

AQI_LABELS: Dict[int, str] = {
    1: "Хорошее",
    2: "Удовлетворительное",
    3: "Умеренное",
    4: "Плохое",
    5: "Очень плохое",
}

AQI_EMOJI: Dict[int, str] = {
    1: "🟢",
    2: "🟡",
    3: "🟠",
    4: "🔴",
    5: "🟣",
}

# Пороги WHO (мкг/м³)
COMPONENT_THRESHOLDS: Dict[str, List[Tuple[float, str]]] = {
    "pm2_5": [(0, "Безопасно"), (12, "Умеренно"),
              (35, "Вредно для чувствительных групп"), (55, "Вредно"), (150, "Очень вредно")],
    "pm10":  [(0, "Безопасно"), (54, "Умеренно"),
              (154, "Вредно для чувствительных групп"), (254, "Вредно"), (354, "Очень вредно")],
    "no2":   [(0, "Безопасно"), (53, "Умеренно"),
              (100, "Вредно для чувствительных групп"), (360, "Вредно"), (649, "Очень вредно")],
    "o3":    [(0, "Безопасно"), (54, "Умеренно"),
              (70, "Вредно для чувствительных групп"), (85, "Вредно"), (105, "Очень вредно")],
    "co":    [(0, "Безопасно"), (4400, "Умеренно"),
              (9400, "Вредно для чувствительных групп"), (12400, "Вредно"), (15400, "Очень вредно")],
    "so2":   [(0, "Безопасно"), (35, "Умеренно"),
              (75, "Вредно для чувствительных групп"), (185, "Вредно"), (304, "Очень вредно")],
}

COMPONENT_NAMES_RU: Dict[str, str] = {
    "co":    "Монооксид углерода (CO)",
    "no":    "Монооксид азота (NO)",
    "no2":   "Диоксид азота (NO₂)",
    "o3":    "Озон (O₃)",
    "so2":   "Диоксид серы (SO₂)",
    "pm2_5": "Мелкодисперсные частицы (PM2.5)",
    "pm10":  "Взвешенные частицы (PM10)",
    "nh3":   "Аммиак (NH₃)",
}

WIND_DIRECTIONS: List[str] = [
    "С", "ССВ", "СВ", "ВСВ",
    "В", "ВЮВ", "ЮВ", "ЮЮВ",
    "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ",
    "З", "ЗСЗ", "СЗ", "ССЗ",
]

# Резервный словарь локализации (EN → RU), на случай если API вернул EN
WEATHER_DESCRIPTION_RU: Dict[str, str] = {
    "clear sky": "ясно",
    "few clouds": "малооблачно",
    "scattered clouds": "переменная облачность",
    "broken clouds": "облачно с прояснениями",
    "overcast clouds": "пасмурно",
    "light rain": "небольшой дождь",
    "moderate rain": "умеренный дождь",
    "heavy intensity rain": "сильный дождь",
    "very heavy rain": "очень сильный дождь",
    "freezing rain": "ледяной дождь",
    "light snow": "небольшой снег",
    "snow": "снег",
    "heavy snow": "сильный снег",
    "sleet": "дождь со снегом",
    "shower rain": "ливень",
    "thunderstorm": "гроза",
    "mist": "туман",
    "smoke": "дымка",
    "haze": "мгла",
    "fog": "туман",
    "sand": "песок",
    "dust": "пыль",
    "drizzle": "морось",
    "light intensity drizzle": "лёгкая морось",
}


# ===========================================================================
# Утилиты
# ===========================================================================

def log_error(message: str) -> None:
    print(f"❌ {message}", file=sys.stderr)


def _localize_description(desc: str) -> str:
    """Переводит описание погоды на русский, если оно на английском."""
    return WEATHER_DESCRIPTION_RU.get(desc.lower().strip(), desc)


def make_request(url: str, params: Dict[str, Any]) -> Optional[requests.Response]:
    """GET с retry-логикой (3 попытки, паузы 1/2/4 с)."""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 429:
                wait = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else 4
                log_error(f"⏳ Лимит запросов. Повтор через {wait}с...")
                time.sleep(wait)
                continue
            if response.status_code >= 500:
                wait = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else 4
                log_error(f"⚠️ Ошибка сервера ({response.status_code}). Повтор через {wait}с...")
                time.sleep(wait)
                continue
            return response
        except requests.exceptions.ConnectionError:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAYS[attempt]
                log_error(f"🔌 Нет соединения. Повтор через {wait}с...")
                time.sleep(wait)
            else:
                log_error("Не удалось подключиться к серверу.")
                return None
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAYS[attempt]
                log_error(f"⏱️ Таймаут. Повтор через {wait}с...")
                time.sleep(wait)
            else:
                log_error("Превышено время ожидания.")
                return None
        except requests.exceptions.RequestException as exc:
            log_error(f"Ошибка запроса: {exc}")
            return None
    return None


def _parse_response(response: Optional[requests.Response], label: str) -> Optional[Dict]:
    if response is None:
        return None
    if response.status_code == 401:
        log_error("🔑 Неверный API-ключ. Проверьте .env")
        return None
    if response.status_code == 404:
        log_error(f"📍 {label}: данные не найдены (404)")
        return None
    if response.status_code != 200:
        log_error(f"❌ {label}: HTTP {response.status_code}")
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        log_error(f"❌ {label}: некорректный JSON в ответе")
        return None


# ===========================================================================
# 1. Геокодинг
# ===========================================================================

def get_coordinates(city: str, limit: int = 1) -> Optional[Tuple[float, float]]:
    """
    Возвращает (lat, lon) для города через OpenWeather Geocoding API (lang=ru).
    При пустом ответе или ошибке — None без трейсбека.
    """
    if not API_KEY:
        log_error("🔑 API_KEY не найден. Проверьте файл .env")
        return None

    params = {"q": city, "limit": limit, "lang": "ru", "appid": API_KEY}
    response = make_request(GEOCODING_URL, params)
    data = _parse_response(response, "Геокодинг")

    if data is None:
        return None
    if not isinstance(data, list) or len(data) == 0:
        log_error(f"🏙️ Город «{city}» не найден в базе данных")
        return None

    loc = data[0]
    lat, lon = loc.get("lat"), loc.get("lon")
    if lat is None or lon is None:
        log_error("Не удалось получить координаты из ответа API")
        return None
    return float(lat), float(lon)


# ===========================================================================
# 2. Текущая погода (кэш 10 мин)
# ===========================================================================

def get_current_weather(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Текущая погода для координат (units=metric, lang=ru). Кэш 10 мин."""
    if not API_KEY:
        log_error("🔑 API_KEY не найден. Проверьте файл .env")
        return None

    cached = get_cached(lat, lon, "current")
    if cached is not None:
        return cached

    params = {"lat": lat, "lon": lon, "appid": API_KEY, "units": "metric", "lang": "ru"}
    data = _parse_response(make_request(WEATHER_URL, params), "Текущая погода")
    if data:
        for w in data.get("weather", []):
            w["description"] = _localize_description(w.get("description", ""))
        set_cached(lat, lon, "current", data)
    return data


# ===========================================================================
# 3. Прогноз 5 дней / шаг 3 ч (кэш 10 мин)
# ===========================================================================

def get_forecast_5d3h(lat: float, lon: float) -> List[Dict[str, Any]]:
    """
    Прогноз на 5 дней с шагом 3 ч (до 40 записей). Кэш 10 мин.
    Возвращает список словарей или [] при ошибке.
    """
    if not API_KEY:
        log_error("🔑 API_KEY не найден. Проверьте файл .env")
        return []

    cached = get_cached(lat, lon, "forecast")
    if cached is not None:
        return cached

    params = {"lat": lat, "lon": lon, "appid": API_KEY, "units": "metric", "lang": "ru"}
    raw = _parse_response(make_request(FORECAST_URL, params), "Прогноз 5д/3ч")
    if not raw:
        return []

    result: List[Dict[str, Any]] = []
    for entry in raw.get("list", []):
        main    = entry.get("main", {})
        weather = entry.get("weather", [{}])[0]
        wind    = entry.get("wind", {})
        rain    = entry.get("rain", {})
        snow    = entry.get("snow", {})
        deg     = wind.get("deg")

        result.append({
            "dt_txt":      entry.get("dt_txt", ""),
            "temp":        main.get("temp"),
            "feels_like":  main.get("feels_like"),
            "humidity":    main.get("humidity"),
            "description": _localize_description(weather.get("description", "—")),
            "wind_speed":  wind.get("speed"),
            "wind_dir":    _degrees_to_direction(deg) if deg is not None else "—",
            "pop":         round(entry.get("pop", 0.0) * 100),
            "rain_3h":     rain.get("3h", 0.0),
            "snow_3h":     snow.get("3h", 0.0),
            "icon":        weather.get("icon", "01d"),
        })

    set_cached(lat, lon, "forecast", result)
    return result


def _degrees_to_direction(deg: float) -> str:
    return WIND_DIRECTIONS[round(deg / 22.5) % 16]


# ===========================================================================
# 4. Загрязнение воздуха (кэш 10 мин)
# ===========================================================================

def get_air_pollution(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """
    Данные Air Pollution API. Кэш 10 мин.
    Возвращает {"aqi": int, "components": dict} или None.
    """
    if not API_KEY:
        log_error("🔑 API_KEY не найден. Проверьте файл .env")
        return None

    cached = get_cached(lat, lon, "air")
    if cached is not None:
        return cached

    params = {"lat": lat, "lon": lon, "appid": API_KEY}
    raw = _parse_response(make_request(AIR_POLL_URL, params), "Качество воздуха")
    if not raw:
        return None

    items = raw.get("list", [])
    if not items:
        log_error("Качество воздуха: пустой список данных")
        return None

    item = items[0]
    data = {"aqi": item.get("main", {}).get("aqi"), "components": item.get("components", {})}
    set_cached(lat, lon, "air", data)
    return data


# ===========================================================================
# 5. Анализ загрязнения воздуха
# ===========================================================================

def analyze_air_pollution(
    components: Dict[str, float],
    extended: bool = False,
) -> Dict[str, Any]:
    """
    Сводный отчёт о качестве воздуха.
    extended=True → добавляет детализацию по каждому компоненту.
    """
    worst_level = 0
    details: Dict[str, Dict[str, Any]] = {}

    for key, thresholds in COMPONENT_THRESHOLDS.items():
        value = components.get(key)
        if value is None:
            continue

        level, status = 0, thresholds[0][1]
        for i, (threshold, label) in enumerate(thresholds):
            if value >= threshold:
                level, status = i, label

        worst_level = max(worst_level, level)

        if extended:
            unit = "мг/м³" if key == "co" else "мкг/м³"
            details[COMPONENT_NAMES_RU.get(key, key)] = {
                "значение": f"{value:.2f} {unit}",
                "статус":   status,
            }

    aqi_index = min(worst_level + 1, 5)
    result: Dict[str, Any] = {"overall": AQI_LABELS[aqi_index], "emoji": AQI_EMOJI[aqi_index]}
    if extended:
        result["details"] = details
    return result


# ===========================================================================
# Кэш текущей погоды (файловый, оставлен для совместимости с CLI)
# ===========================================================================

def load_cache() -> Optional[Dict[str, Any]]:
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_cache(data: Dict[str, Any], city: str, lat: float, lon: float) -> None:
    cache = {
        "city": city, "lat": lat, "lon": lon,
        "fetched_at": datetime.now().isoformat(), "weather": data,
    }
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except IOError as exc:
        log_error(f"⚠️ Не удалось сохранить кэш: {exc}")


def is_cache_valid(cache: Dict[str, Any]) -> bool:
    try:
        fetched = datetime.fromisoformat(cache["fetched_at"])
        return datetime.now() - fetched < timedelta(hours=CACHE_TTL_HOURS)
    except (KeyError, ValueError):
        return False


# ===========================================================================
# Форматирование (CLI)
# ===========================================================================

def format_weather_output(weather: Dict[str, Any]) -> str:
    city_name   = weather.get("name", "Неизвестный город")
    temp        = weather.get("main", {}).get("temp")
    description = weather.get("weather", [{}])[0].get("description", "нет данных")
    if temp is None:
        return "⚠️ Температура не доступна"
    return f"🌤️ Погода в {city_name}: {temp:.1f}°C, {description}"


def format_forecast_output(forecast: List[Dict[str, Any]]) -> str:
    if not forecast:
        return "⚠️ Данные прогноза недоступны"
    lines = ["📅 Прогноз на 5 дней (шаг 3 часа):\n"]
    current_day = ""
    for entry in forecast:
        try:
            dt = datetime.strptime(entry.get("dt_txt", ""), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        day_label = dt.strftime("%d.%m.%Y")
        if day_label != current_day:
            current_day = day_label
            lines.append(f"\n{'─' * 36}\n📆 {day_label}\n{'─' * 36}")
        temp, fl = entry.get("temp"), entry.get("feels_like")
        line = (
            f"  🕐 {dt.strftime('%H:%M')}  {temp:+.1f}°C (ощущ. {fl:+.1f}°C)  "
            f"{entry.get('description', '—').capitalize()}  "
            f"💧{entry.get('humidity')}%  "
            f"💨{entry.get('wind_speed', 0):.1f}м/с {entry.get('wind_dir', '—')}  "
            f"☔{entry.get('pop', 0)}%"
        )
        if entry.get("rain_3h", 0) > 0:
            line += f"  🌧️{entry['rain_3h']:.1f}мм"
        if entry.get("snow_3h", 0) > 0:
            line += f"  ❄️{entry['snow_3h']:.1f}мм"
        lines.append(line)
    return "\n".join(lines)


def format_air_pollution_output(
    aqi: int, components: Dict[str, float], extended: bool = False,
) -> str:
    report = analyze_air_pollution(components, extended=extended)
    lines = [
        "🌬️ Качество воздуха:",
        f"  {AQI_EMOJI.get(aqi, '⚪')} AQI: {aqi} — {AQI_LABELS.get(aqi, '—')}",
        f"  {report['emoji']} Общий статус: {report['overall']}",
    ]
    if extended and "details" in report:
        lines.append("\n  📊 Детализация:")
        for name, info in report["details"].items():
            lines.append(f"    • {name}: {info['значение']} — {info['статус']}")
    return "\n".join(lines)


# ===========================================================================
# Публичные обёртки
# ===========================================================================

def get_weather_by_city(city: str, use_cache: bool = True) -> Optional[str]:
    coords = get_coordinates(city)
    if not coords:
        if use_cache:
            cache = load_cache()
            if cache and cache.get("city", "").lower() == city.lower() and is_cache_valid(cache):
                return format_weather_output(cache["weather"])
        return None
    lat, lon = coords
    weather = get_current_weather(lat, lon)
    if weather:
        save_cache(weather, city, lat, lon)
        return format_weather_output(weather)
    if use_cache:
        cache = load_cache()
        if cache and cache.get("city", "").lower() == city.lower() and is_cache_valid(cache):
            return format_weather_output(cache["weather"])
    return None


def get_forecast_by_city(city: str) -> Optional[str]:
    coords = get_coordinates(city)
    if not coords:
        return None
    forecast = get_forecast_5d3h(*coords)
    return format_forecast_output(forecast) if forecast else None


def get_air_pollution_by_city(city: str, extended: bool = False) -> Optional[str]:
    coords = get_coordinates(city)
    if not coords:
        return None
    data = get_air_pollution(*coords)
    if not data:
        return None
    return format_air_pollution_output(data["aqi"], data["components"], extended=extended)


def get_weather_by_coords_input(lat: float, lon: float) -> Optional[str]:
    weather = get_current_weather(lat, lon)
    return format_weather_output(weather) if weather else None


# ===========================================================================
# CLI
# ===========================================================================

def print_menu() -> None:
    print("\n" + "=" * 50)
    print("🌤️  Weather App — Выбор режима")
    print("=" * 50)
    print("  1 — Текущая погода по городу")
    print("  2 — Поиск по координатам")
    print("  3 — Прогноз на 5 дней (3ч) по городу")
    print("  4 — Качество воздуха по городу")
    print("  5 — Качество воздуха (расширенный режим)")
    print("  0 — Выход")
    print("-" * 50)


def main() -> None:
    if not API_KEY:
        log_error("🔑 API_KEY не настроен!")
        print(
            "\n💡 Инструкция:\n"
            "   1. Откройте файл .env\n"
            "   2. Вставьте ваш ключ: API_KEY=ваш_ключ\n"
            "   3. Получите ключ: https://openweathermap.org/api"
        )
        return

    print("🌤️  Добро пожаловать в Weather App!")
    result = None

    while True:
        print_menu()
        choice = input("👉 Выберите режим: ").strip()

        if choice == "0":
            print("👋 До свидания! Хорошей погоды!")
            break
        elif choice == "1":
            city = input("🏙️  Город: ").strip()
            if city:
                result = get_weather_by_city(city)
                print(f"\n✅ {result}" if result else "")
        elif choice == "2":
            try:
                lat = float(input("📍 Широта: ").strip())
                lon = float(input("📍 Долгота: ").strip())
                result = get_weather_by_coords_input(lat, lon)
                print(f"\n✅ {result}" if result else "")
            except ValueError:
                log_error("Некорректный формат координат.")
        elif choice == "3":
            city = input("🏙️  Город: ").strip()
            if city:
                result = get_forecast_by_city(city)
                print(f"\n{result}" if result else "⚠️ Не удалось получить прогноз.")
        elif choice in ("4", "5"):
            city = input("🏙️  Город: ").strip()
            if city:
                result = get_air_pollution_by_city(city, extended=(choice == "5"))
                print(f"\n{result}" if result else "⚠️ Нет данных о воздухе.")
        else:
            log_error("Неизвестная команда.")
            continue

        if not result:
            log_error("Не удалось получить данные.")
        print("\n" + "─" * 50)


if __name__ == "__main__":
    main()
