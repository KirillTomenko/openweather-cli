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
from typing import Optional, Tuple, Dict, Any

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("API_KEY")

GEOCODING_URL = "https://api.openweathermap.org/geo/1.0/direct"
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
CACHE_FILE = "weather_cache.json"
CACHE_TTL_HOURS = 3
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]

def log_error(message: str) -> None:
    print(f"❌ {message}", file=sys.stderr)

def make_request(url: str, params: Dict[str, Any]) -> Optional[requests.Response]:
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 429:
                wait_time = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else 4
                log_error(f"⏳ Лимит запросов. Повтор через {wait_time}с...")
                time.sleep(wait_time)
                continue
            if response.status_code >= 500:
                wait_time = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else 4
                log_error(f"⚠️ Ошибка сервера ({response.status_code}). Повтор через {wait_time}с...")
                time.sleep(wait_time)
                continue
            return response
        except requests.exceptions.ConnectionError:
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAYS[attempt]
                log_error(f"🔌 Нет соединения. Повтор через {wait_time}с...")
                time.sleep(wait_time)
            else:
                log_error("❌ Не удалось подключиться к серверу.")
                return None
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAYS[attempt]
                log_error(f"⏱️ Таймаут. Повтор через {wait_time}с...")
                time.sleep(wait_time)
            else:
                log_error("❌ Превышено время ожидания.")
                return None
        except requests.exceptions.RequestException as e:
            log_error(f"❌ Ошибка запроса: {e}")
            return None
    return None

def get_coordinates(city: str) -> Optional[Tuple[float, float]]:
    if not API_KEY:
        log_error("🔑 API_KEY не найден. Проверьте файл .env")
        return None
    params = {"q": city, "limit": 1, "lang": "ru", "appid": API_KEY}
    response = make_request(GEOCODING_URL, params)
    if response is None: return None
    if response.status_code != 200:
        if response.status_code == 401: log_error("🔑 Неверный API-ключ. Проверьте .env")
        elif response.status_code == 404: log_error(f"🏙️ Город '{city}' не найден")
        else: log_error(f"❌ Ошибка геокодинга: {response.status_code}")
        return None
    try:
        data = response.json()
    except json.JSONDecodeError:
        log_error("❌ Некорректный ответ от сервера геокодинга")
        return None
    if not data or not isinstance(data, list) or len(data) == 0:
        log_error(f"🏙️ Город '{city}' не найден в базе данных")
        return None
    location = data[0]
    lat, lon = location.get("lat"), location.get("lon")
    if lat is None or lon is None:
        log_error("❌ Не удалось получить координаты")
        return None
    return float(lat), float(lon)

def get_weather_by_coordinates(latitude: float, longitude: float) -> Optional[Dict[str, Any]]:
    if not API_KEY:
        log_error("🔑 API_KEY не найден. Проверьте файл .env")
        return None
    params = {"lat": latitude, "lon": longitude, "appid": API_KEY, "units": "metric", "lang": "ru"}
    response = make_request(WEATHER_URL, params)
    if response is None: return None
    if response.status_code != 200:
        if response.status_code == 401: log_error("🔑 Неверный API-ключ")
        elif response.status_code == 404: log_error("📍 Координаты не найдены")
        else: log_error(f"❌ Ошибка получения погоды: {response.status_code}")
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        log_error("❌ Некорректный ответ от сервера погоды")
        return None

def load_cache() -> Optional[Dict[str, Any]]:
    if not os.path.exists(CACHE_FILE): return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError): return None

def save_cache(data: Dict[str, Any], city: str, lat: float, lon: float) -> None:
    cache = {"city": city, "lat": lat, "lon": lon, "fetched_at": datetime.now().isoformat(), "weather": data}
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except IOError as e:
        log_error(f"⚠️ Не удалось сохранить кэш: {e}")

def is_cache_valid(cache: Dict[str, Any]) -> bool:
    try:
        fetched = datetime.fromisoformat(cache["fetched_at"])
        return datetime.now() - fetched < timedelta(hours=CACHE_TTL_HOURS)
    except (KeyError, ValueError): return False

def format_weather_output(weather: Dict[str, Any]) -> str:
    city_name = weather.get("name", "Неизвестный город")
    temp = weather.get("main", {}).get("temp")
    description = weather.get("weather", [{}])[0].get("description", "нет данных")
    if temp is None: return "⚠️ Температура не доступна"
    return f"🌤️ Погода в {city_name}: {temp:.1f}°C, {description}"

def get_weather_by_city(city: str, use_cache: bool = True) -> Optional[str]:
    coords = get_coordinates(city)
    if not coords:
        if use_cache:
            cache = load_cache()
            if cache and cache.get("city", "").lower() == city.lower() and is_cache_valid(cache):
                print(f"⚡ Используем кэш (получено: {cache['fetched_at']})")
                return format_weather_output(cache["weather"])
        return None
    lat, lon = coords
    weather = get_weather_by_coordinates(lat, lon)
    if weather:
        save_cache(weather, city, lat, lon)
        return format_weather_output(weather)
    if use_cache:
        cache = load_cache()
        if cache and cache.get("city", "").lower() == city.lower() and is_cache_valid(cache):
            print(f"⚡ Используем кэш (получено: {cache['fetched_at']})")
            return format_weather_output(cache["weather"])
    return None

def get_weather_by_coords_input(lat: float, lon: float) -> Optional[str]:
    weather = get_weather_by_coordinates(lat, lon)
    return format_weather_output(weather) if weather else None

def print_menu() -> None:
    print("\n" + "=" * 50)
    print("🌤️  Weather App — Выбор режима")
    print("=" * 50)
    print("  1 — Поиск по названию города")
    print("  2 — Поиск по координатам")
    print("  0 — Выход")
    print("-" * 50)

def main() -> None:
    if not API_KEY:
        log_error("🔑 API_KEY не настроен!")
        print("\n💡 Инструкция:\n   1. Откройте файл .env\n   2. Вставьте ваш ключ: API_KEY=ваш_ключ\n   3. Получите ключ: https://openweathermap.org/api")
        return

    print("🌤️  Добро пожаловать в Weather App!")
    print("💡 Введите название города, '2' для координат или '0' для выхода.\n")

    while True:
        choice = input("🏙️  Город / команда: ").strip()

        if not choice:
            continue

        if choice == "0":
            print("👋 До свидания! Хорошей погоды!")
            break

        elif choice == "2":
            try:
                lat_str = input("📍 Широта (lat): ").strip()
                lon_str = input("📍 Долгота (lon): ").strip()
                lat = float(lat_str)
                lon = float(lon_str)
                print(f"\n🔍 Ищем погоду для координат: {lat}, {lon}...")
                result = get_weather_by_coords_input(lat, lon)
            except ValueError:
                log_error("Некорректный формат координат. Попробуйте снова.")
                continue

        else:
            # Всё, что не "0" и не "2", считаем названием города
            print(f"\n🔍 Ищем погоду для: {choice}...")
            result = get_weather_by_city(choice)

        if result:
            print(f"\n✅ {result}")
        else:
            log_error("Не удалось получить данные. Проверьте название или попробуйте снова.")

        print("\n" + "-" * 50)

if __name__ == "__main__":
    main()