#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
storage.py — Хранение пользовательских данных в User_Data.json

Структура файла:
{
    "<user_id>": {
        "city": "Москва",
        "lat": 55.7522,
        "lon": 37.6156,
        "notifications": {
            "enabled": true,
            "interval_h": 2
        }
    }
}
"""

import json
import os
import sys
from typing import Any, Dict

DATA_FILE = "User_Data.json"

# ---------------------------------------------------------------------------
# Внутренние утилиты
# ---------------------------------------------------------------------------

def _log_error(message: str) -> None:
    print(f"❌ [storage] {message}", file=sys.stderr)


def _load_all() -> Dict[str, Any]:
    """Загружает весь файл и возвращает словарь. При ошибке — пустой dict."""
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            _log_error(f"Файл {DATA_FILE} содержит не объект JSON — сброс.")
            return {}
        return data
    except json.JSONDecodeError as exc:
        _log_error(f"Некорректный JSON в {DATA_FILE}: {exc}")
        return {}
    except OSError as exc:
        _log_error(f"Не удалось прочитать {DATA_FILE}: {exc}")
        return {}


def _save_all(data: Dict[str, Any]) -> None:
    """Сохраняет весь словарь в файл. При ошибке пишет в stderr."""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        _log_error(f"Не удалось записать {DATA_FILE}: {exc}")


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def load_user(user_id: int) -> Dict[str, Any]:
    """
    Загружает данные пользователя по его ID.

    Args:
        user_id: числовой идентификатор пользователя (например, Telegram user_id).

    Returns:
        Словарь с полями city, lat, lon, notifications.
        Если пользователь не найден — возвращает словарь с дефолтными значениями:
        {
            "city": None,
            "lat": None,
            "lon": None,
            "notifications": {"enabled": False, "interval_h": 3}
        }
    """
    all_data = _load_all()
    key = str(user_id)
    if key in all_data:
        return all_data[key]

    # Дефолтный профиль для нового пользователя
    return {
        "city": None,
        "lat":  None,
        "lon":  None,
        "notifications": {
            "enabled":    False,
            "interval_h": 3,
        },
    }


def save_user(user_id: int, data: Dict[str, Any]) -> None:
    """
    Сохраняет (или обновляет) данные пользователя.

    Args:
        user_id: числовой идентификатор пользователя.
        data:    словарь с полями city, lat, lon, notifications.
                 Передавать можно неполный словарь — существующие поля
                 будут смёрджены, а не перезаписаны целиком.

    Example:
        save_user(123456, {"city": "Москва", "lat": 55.75, "lon": 37.62})
        save_user(123456, {"notifications": {"enabled": True, "interval_h": 6}})
    """
    all_data = _load_all()
    key = str(user_id)

    existing = all_data.get(key, {})

    # Глубокий мёрдж для вложенного поля notifications
    if "notifications" in data and "notifications" in existing:
        merged_notifications = {**existing["notifications"], **data["notifications"]}
        data = {**data, "notifications": merged_notifications}

    all_data[key] = {**existing, **data}
    _save_all(all_data)


def delete_user(user_id: int) -> bool:
    """
    Удаляет пользователя из хранилища.

    Returns:
        True — если пользователь был удалён, False — если не найден.
    """
    all_data = _load_all()
    key = str(user_id)
    if key not in all_data:
        return False
    del all_data[key]
    _save_all(all_data)
    return True


def get_all_users() -> Dict[str, Dict[str, Any]]:
    """
    Возвращает всех пользователей.
    Используется, например, для рассылки уведомлений по расписанию.
    """
    return _load_all()
