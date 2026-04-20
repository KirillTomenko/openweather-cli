#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cache.py — Файловый кэш ответов OpenWeather API.

Кэширует JSON-ответы в ./.cache/<hash>.json на 10 минут.
Ключ кэша: (lat, lon, endpoint) → MD5.
"""

import json
import os
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

CACHE_DIR        = ".cache"
CACHE_TTL_MINUTES = 10

logger = logging.getLogger(__name__)


def _ensure_dir() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)


def _make_key(lat: float, lon: float, endpoint: str) -> str:
    raw = f"{lat:.4f},{lon:.4f},{endpoint}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def get_cached(lat: float, lon: float, endpoint: str) -> Optional[Any]:
    """
    Возвращает данные из кэша, если они ещё свежие (< CACHE_TTL_MINUTES).
    Иначе — None.
    """
    key  = _make_key(lat, lon, endpoint)
    path = _cache_path(key)

    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            cached = json.load(f)

        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        if datetime.now() - fetched_at > timedelta(minutes=CACHE_TTL_MINUTES):
            os.remove(path)
            return None

        logger.debug("Cache HIT  %s [%s, %s]", endpoint, lat, lon)
        return cached["data"]

    except (json.JSONDecodeError, KeyError, ValueError, OSError) as exc:
        logger.debug("Cache read error: %s", exc)
        return None


def set_cached(lat: float, lon: float, endpoint: str, data: Any) -> None:
    """Сохраняет данные в кэш."""
    _ensure_dir()
    key  = _make_key(lat, lon, endpoint)
    path = _cache_path(key)

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"fetched_at": datetime.now().isoformat(), "data": data},
                f,
                ensure_ascii=False,
            )
        logger.debug("Cache SET   %s [%s, %s]", endpoint, lat, lon)
    except OSError as exc:
        logger.warning("Cache write error: %s", exc)


def clear_cache() -> int:
    """Удаляет все файлы кэша. Возвращает количество удалённых файлов."""
    if not os.path.exists(CACHE_DIR):
        return 0
    count = 0
    for fname in os.listdir(CACHE_DIR):
        if fname.endswith(".json"):
            try:
                os.remove(os.path.join(CACHE_DIR, fname))
                count += 1
            except OSError:
                pass
    return count
