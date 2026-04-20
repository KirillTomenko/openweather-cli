#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot.py — Telegram-бот для получения погоды
Автор: Kirill Tomenko

Зависимости:
    pip install "python-telegram-bot[job-queue]>=20.0" python-dotenv requests

.env:
    BOT_TOKEN=ваш_токен_бота
    API_KEY=ваш_ключ_openweather
"""

import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from storage import get_all_users, load_user, save_user
from weather_app import (
    AQI_EMOJI,
    AQI_LABELS,
    analyze_air_pollution,
    get_air_pollution,
    get_coordinates,
    get_current_weather,
    get_forecast_5d3h,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Состояния ConversationHandler
# ---------------------------------------------------------------------------
(
    WEATHER_CITY,
    FORECAST_CITY,
    LOCATION_WAIT,
    COMPARE_CITY1,
    COMPARE_CITY2,
    ADVANCED_CITY,
) = range(6)

# ---------------------------------------------------------------------------
# Метки кнопок главного меню
# ---------------------------------------------------------------------------
BTN_WEATHER   = "🌤 Текущая погода"
BTN_FORECAST  = "📅 Прогноз на 5 дней"
BTN_LOCATION  = "📍 Моя геолокация"
BTN_COMPARE   = "🔁 Сравнить города"
BTN_ADVANCED  = "🔬 Расширенные данные"
BTN_NOTIF     = "🔔 Уведомления"
BTN_CANCEL    = "❌ Отмена"

MAIN_KB = ReplyKeyboardMarkup(
    [[BTN_WEATHER, BTN_FORECAST],
     [BTN_LOCATION, BTN_COMPARE],
     [BTN_ADVANCED, BTN_NOTIF]],
    resize_keyboard=True,
)
CANCEL_KB = ReplyKeyboardMarkup([[BTN_CANCEL]], resize_keyboard=True)


# ===========================================================================
# Вспомогательные функции форматирования
# ===========================================================================

def _sign(v: float) -> str:
    return f"+{v:.1f}" if v >= 0 else f"{v:.1f}"


def _fmt_current(weather: dict, city: str) -> str:
    """Красиво форматирует текущую погоду для Telegram (HTML)."""
    main   = weather.get("main", {})
    w_info = weather.get("weather", [{}])[0]
    wind   = weather.get("wind", {})
    sys_   = weather.get("sys", {})

    temp       = main.get("temp", 0)
    feels      = main.get("feels_like", 0)
    humidity   = main.get("humidity", 0)
    pressure   = main.get("pressure", 0)
    desc       = w_info.get("description", "—").capitalize()
    wind_spd   = wind.get("speed", 0)
    visibility = weather.get("visibility", 0) // 1000
    country    = sys_.get("country", "")

    sunrise = (
        datetime.fromtimestamp(sys_["sunrise"]).strftime("%H:%M")
        if sys_.get("sunrise") else "—"
    )
    sunset = (
        datetime.fromtimestamp(sys_["sunset"]).strftime("%H:%M")
        if sys_.get("sunset") else "—"
    )
    city_label = f"{city}{', ' + country if country else ''}"

    return (
        f"🌤 <b>{city_label}</b>\n"
        f"{'─' * 30}\n"
        f"🌡 Температура:  <b>{_sign(temp)}°C</b>\n"
        f"🤔 Ощущается:   <b>{_sign(feels)}°C</b>\n"
        f"💬 Описание:    {desc}\n"
        f"💧 Влажность:   {humidity}%\n"
        f"🌬 Ветер:       {wind_spd:.1f} м/с\n"
        f"📊 Давление:    {pressure} гПа\n"
        f"👁 Видимость:   {visibility} км\n"
        f"🌅 Восход:      {sunrise}  🌇 Закат: {sunset}\n"
        f"{'─' * 30}\n"
        f"<i>🕐 {datetime.now().strftime('%H:%M, %d.%m.%Y')}</i>"
    )


def _fmt_air(aqi: int, report: dict) -> str:
    """Форматирует отчёт о качестве воздуха (HTML)."""
    lines = [
        "🌬 <b>Качество воздуха</b>",
        f"{'─' * 30}",
        f"{AQI_EMOJI.get(aqi, '⚪')} AQI: <b>{aqi}</b> — {AQI_LABELS.get(aqi, '—')}",
        f"{report['emoji']} Статус: <b>{report['overall']}</b>",
    ]
    if "details" in report:
        lines.append("")
        lines.append("📊 <b>Детализация:</b>")
        for name, info in report["details"].items():
            lines.append(
                f"  • {name}\n"
                f"    {info['значение']} — <i>{info['статус']}</i>"
            )
    return "\n".join(lines)


def _group_by_day(forecast: list) -> dict:
    """Группирует прогноз по дням: {"2024-05-01": [entry, ...], ...}"""
    days: dict = {}
    for e in forecast:
        day = e["dt_txt"][:10]
        days.setdefault(day, []).append(e)
    return days


def _day_label(dt: datetime) -> str:
    DAYS   = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    MONTHS = ["янв", "фев", "мар", "апр", "май", "июн",
               "июл", "авг", "сен", "окт", "ноя", "дек"]
    today = datetime.now().date()
    delta = (dt.date() - today).days
    prefix = {0: "Сегодня", 1: "Завтра"}.get(delta, DAYS[dt.weekday()])
    return f"{prefix}, {dt.day} {MONTHS[dt.month - 1]}"


def _forecast_day_picker_kb(days: dict) -> InlineKeyboardMarkup:
    buttons = []
    for i, (day_key, entries) in enumerate(days.items()):
        dt  = datetime.strptime(entries[0]["dt_txt"], "%Y-%m-%d %H:%M:%S")
        t_min = min(e["temp"] for e in entries if e["temp"] is not None)
        t_max = max(e["temp"] for e in entries if e["temp"] is not None)
        buttons.append([InlineKeyboardButton(
            f"{_day_label(dt)}   {t_min:+.0f}°…{t_max:+.0f}°C",
            callback_data=f"fd_{i}",
        )])
    return InlineKeyboardMarkup(buttons)


def _city_not_found(city: str) -> str:
    return (
        f"🔍 Город <b>{city}</b> не найден.\n"
        "Проверь написание и попробуй ещё раз.\n"
        "Пример: <code>Москва</code> или <code>Berlin</code>"
    )


# ===========================================================================
# /start
# ===========================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "друг"
    await update.message.reply_text(
        f"👋 Привет, <b>{name}</b>!\n\n"
        "🌍 <b>Weather Bot</b> — твой персональный помощник по погоде.\n\n"
        "Выбери действие в меню ниже:",
        reply_markup=MAIN_KB,
        parse_mode=ParseMode.HTML,
    )


# ===========================================================================
# Текущая погода
# ===========================================================================

async def weather_enter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Точка входа: если город уже сохранён — сразу показываем."""
    user = load_user(update.effective_user.id)
    if user.get("city"):
        w = get_current_weather(user["lat"], user["lon"])
        if w:
            await update.message.reply_text(
                _fmt_current(w, user["city"]),
                parse_mode=ParseMode.HTML,
                reply_markup=MAIN_KB,
            )
            return ConversationHandler.END

    await update.message.reply_text(
        "🏙 Введи название города:",
        reply_markup=CANCEL_KB,
    )
    return WEATHER_CITY


async def weather_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    city   = update.message.text.strip()
    coords = get_coordinates(city)
    if not coords:
        await update.message.reply_text(
            _city_not_found(city), parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB,
        )
        return WEATHER_CITY

    lat, lon = coords
    w = get_current_weather(lat, lon)
    if not w:
        await update.message.reply_text(
            "⚠️ Не удалось получить погоду. Попробуй позже.",
            reply_markup=MAIN_KB,
        )
        return ConversationHandler.END

    save_user(update.effective_user.id, {"city": city, "lat": lat, "lon": lon})
    await update.message.reply_text(
        _fmt_current(w, city), parse_mode=ParseMode.HTML, reply_markup=MAIN_KB,
    )
    return ConversationHandler.END


# ===========================================================================
# Прогноз на 5 дней
# ===========================================================================

async def forecast_enter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = load_user(update.effective_user.id)
    if user.get("city"):
        await _send_forecast_picker(update, context, user["city"], user["lat"], user["lon"])
        return ConversationHandler.END

    await update.message.reply_text("🏙 Введи название города:", reply_markup=CANCEL_KB)
    return FORECAST_CITY


async def forecast_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    city   = update.message.text.strip()
    coords = get_coordinates(city)
    if not coords:
        await update.message.reply_text(
            _city_not_found(city), parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB,
        )
        return FORECAST_CITY

    lat, lon = coords
    await _send_forecast_picker(update, context, city, lat, lon)
    return ConversationHandler.END


async def _send_forecast_picker(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    city: str, lat: float, lon: float,
) -> None:
    forecast = get_forecast_5d3h(lat, lon)
    if not forecast:
        await update.message.reply_text("⚠️ Прогноз недоступен.", reply_markup=MAIN_KB)
        return

    context.user_data["forecast"]      = forecast
    context.user_data["forecast_city"] = city

    days = _group_by_day(forecast)
    await update.message.reply_text(
        f"📅 <b>Прогноз: {city}</b>\nВыбери день:",
        reply_markup=_forecast_day_picker_kb(days),
        parse_mode=ParseMode.HTML,
    )


async def forecast_day_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает inline-кнопки прогноза (fd_N / fd_back)."""
    query = update.callback_query
    await query.answer()

    forecast = context.user_data.get("forecast", [])
    city     = context.user_data.get("forecast_city", "—")
    days     = _group_by_day(forecast)

    if query.data == "fd_back":
        await query.edit_message_text(
            f"📅 <b>Прогноз: {city}</b>\nВыбери день:",
            reply_markup=_forecast_day_picker_kb(days),
            parse_mode=ParseMode.HTML,
        )
        return

    day_idx  = int(query.data.split("_")[1])
    day_keys = list(days.keys())
    if day_idx >= len(day_keys):
        await query.answer("Данные устарели, запроси прогноз снова.", show_alert=True)
        return

    entries   = days[day_keys[day_idx]]
    dt_first  = datetime.strptime(entries[0]["dt_txt"], "%Y-%m-%d %H:%M:%S")
    day_title = _day_label(dt_first)

    lines = [f"📅 <b>{city} — {day_title}</b>\n"]
    for e in entries:
        dt   = datetime.strptime(e["dt_txt"], "%Y-%m-%d %H:%M:%S")
        temp = e.get("temp")
        fl   = e.get("feels_like")
        desc = e.get("description", "—").capitalize()
        ws   = e.get("wind_speed")
        wd   = e.get("wind_dir", "—")
        hum  = e.get("humidity")
        pop  = e.get("pop", 0)
        rain = e.get("rain_3h", 0.0)
        snow = e.get("snow_3h", 0.0)

        t_str = f"{_sign(temp)}°C" if temp is not None else "—"
        f_str = f"{_sign(fl)}°C"   if fl   is not None else "—"
        w_str = f"{ws:.1f} м/с {wd}" if ws is not None else "—"

        line = (
            f"🕐 <b>{dt.strftime('%H:%M')}</b>  {t_str} <i>(ощущ. {f_str})</i>\n"
            f"   {desc}  💧{hum}%  💨{w_str}  ☔{pop}%"
        )
        if rain:
            line += f"  🌧{rain:.1f}мм"
        if snow:
            line += f"  ❄{snow:.1f}мм"
        lines.append(line)

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("← Назад к дням", callback_data="fd_back")]]
        ),
        parse_mode=ParseMode.HTML,
    )


# ===========================================================================
# Моя геолокация
# ===========================================================================

async def location_enter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc_kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Отправить геолокацию", request_location=True)],
         [BTN_CANCEL]],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "📍 Нажми кнопку, чтобы отправить своё местоположение:",
        reply_markup=loc_kb,
    )
    return LOCATION_WAIT


async def location_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.message.location
    if not loc:
        await update.message.reply_text("⚠️ Пожалуйста, используй кнопку «Отправить геолокацию».")
        return LOCATION_WAIT

    lat, lon = loc.latitude, loc.longitude
    w = get_current_weather(lat, lon)
    if not w:
        await update.message.reply_text("⚠️ Не удалось получить погоду по геолокации.", reply_markup=MAIN_KB)
        return ConversationHandler.END

    city = w.get("name", f"{lat:.2f},{lon:.2f}")
    save_user(update.effective_user.id, {"city": city, "lat": lat, "lon": lon})

    await update.message.reply_text(
        f"✅ Геолокация сохранена!\n📍 Определён город: <b>{city}</b>\n\n"
        + _fmt_current(w, city),
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_KB,
    )
    return ConversationHandler.END


# ===========================================================================
# Сравнить города
# ===========================================================================

async def compare_enter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔁 Введи название <b>первого</b> города:",
        reply_markup=CANCEL_KB,
        parse_mode=ParseMode.HTML,
    )
    return COMPARE_CITY1


async def compare_city1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    city   = update.message.text.strip()
    coords = get_coordinates(city)
    if not coords:
        await update.message.reply_text(
            _city_not_found(city), parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB,
        )
        return COMPARE_CITY1

    context.user_data["cmp1"] = (city, *coords)
    await update.message.reply_text(
        f"✅ Первый: <b>{city}</b>\n\nВведи название <b>второго</b> города:",
        reply_markup=CANCEL_KB,
        parse_mode=ParseMode.HTML,
    )
    return COMPARE_CITY2


async def compare_city2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    city2   = update.message.text.strip()
    coords2 = get_coordinates(city2)
    if not coords2:
        await update.message.reply_text(
            _city_not_found(city2), parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB,
        )
        return COMPARE_CITY2

    city1, lat1, lon1 = context.user_data["cmp1"]
    lat2, lon2 = coords2

    w1 = get_current_weather(lat1, lon1)
    w2 = get_current_weather(lat2, lon2)

    if not w1 or not w2:
        await update.message.reply_text("⚠️ Не удалось получить данные для сравнения.", reply_markup=MAIN_KB)
        return ConversationHandler.END

    await update.message.reply_text(
        _fmt_comparison(city1, w1, city2, w2),
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_KB,
    )
    return ConversationHandler.END


def _fmt_comparison(city1: str, w1: dict, city2: str, w2: dict) -> str:
    def ex(w):
        m = w.get("main", {})
        return {
            "temp":      m.get("temp", 0),
            "feels":     m.get("feels_like", 0),
            "humidity":  m.get("humidity", 0),
            "pressure":  m.get("pressure", 0),
            "wind":      w.get("wind", {}).get("speed", 0),
            "desc":      w.get("weather", [{}])[0].get("description", "—").capitalize(),
        }

    d1, d2 = ex(w1), ex(w2)
    c1, c2 = city1[:12], city2[:12]

    def row(icon, label, v1, v2):
        return f"{icon} {label:<16} {v1:<15} {v2}"

    table = "\n".join([
        f"{'Показатель':<20} {c1:<15} {c2}",
        "─" * 52,
        row("🌡", "Температура",  f"{_sign(d1['temp'])}°C",  f"{_sign(d2['temp'])}°C"),
        row("🤔", "Ощущается",    f"{_sign(d1['feels'])}°C", f"{_sign(d2['feels'])}°C"),
        row("💧", "Влажность",    f"{d1['humidity']}%",      f"{d2['humidity']}%"),
        row("📊", "Давление",     f"{d1['pressure']} гПа",   f"{d2['pressure']} гПа"),
        row("🌬", "Ветер",        f"{d1['wind']:.1f} м/с",   f"{d2['wind']:.1f} м/с"),
        row("💬", "Описание",     d1['desc'][:13],            d2['desc'][:13]),
    ])

    diff = d1["temp"] - d2["temp"]
    if abs(diff) < 0.5:
        verdict = "🤝 Температура одинакова!"
    elif diff > 0:
        verdict = f"🔥 Теплее в <b>{city1}</b> на {abs(diff):.1f}°C"
    else:
        verdict = f"🔥 Теплее в <b>{city2}</b> на {abs(diff):.1f}°C"

    return f"🔁 <b>Сравнение городов</b>\n\n<pre>{table}</pre>\n\n{verdict}"


# ===========================================================================
# Расширенные данные
# ===========================================================================

async def advanced_enter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = load_user(update.effective_user.id)
    if user.get("city"):
        await _send_advanced(update, user["city"], user["lat"], user["lon"])
        return ConversationHandler.END

    await update.message.reply_text(
        "🔬 Введи название города для расширенных данных:",
        reply_markup=CANCEL_KB,
    )
    return ADVANCED_CITY


async def advanced_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    city   = update.message.text.strip()
    coords = get_coordinates(city)
    if not coords:
        await update.message.reply_text(
            _city_not_found(city), parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB,
        )
        return ADVANCED_CITY

    lat, lon = coords
    save_user(update.effective_user.id, {"city": city, "lat": lat, "lon": lon})
    await _send_advanced(update, city, lat, lon)
    return ConversationHandler.END


async def _send_advanced(
    update: Update, city: str, lat: float, lon: float,
) -> None:
    w   = get_current_weather(lat, lon)
    air = get_air_pollution(lat, lon)

    if not w:
        await update.message.reply_text("⚠️ Нет данных о погоде.", reply_markup=MAIN_KB)
        return

    text = _fmt_current(w, city)
    if air:
        report = analyze_air_pollution(air["components"], extended=True)
        text  += "\n\n" + _fmt_air(air["aqi"], report)
    else:
        text += "\n\n⚠️ Данные о качестве воздуха недоступны."

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=MAIN_KB)


# ===========================================================================
# Уведомления
# ===========================================================================

async def notif_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_notif_menu(update.message.reply_text, update.effective_user.id)


async def notif_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user    = load_user(user_id)
    notif   = user.get("notifications", {"enabled": False, "interval_h": 3})
    action  = query.data

    if action == "notif_toggle":
        notif["enabled"] = not notif.get("enabled", False)
        _sync_notif_job(context, user_id, user, notif)

    elif action.startswith("notif_set_"):
        hours = int(action.split("_")[-1])
        notif["interval_h"] = hours
        if notif.get("enabled"):
            _sync_notif_job(context, user_id, user, notif)

    elif action == "notif_close":
        await query.edit_message_text("↩️ Меню уведомлений закрыто.")
        return

    save_user(user_id, {"notifications": notif})

    enabled  = notif.get("enabled", False)
    interval = notif.get("interval_h", 3)
    city     = user.get("city", "не задан")

    toggle_label = "🔕 Выключить" if enabled else "🔔 Включить"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data="notif_toggle")],
        [InlineKeyboardButton(f"{'✅' if interval==h else ''}  {h}ч", callback_data=f"notif_set_{h}")
         for h in (1, 2, 4, 6, 12, 24)],
        [InlineKeyboardButton("❌ Закрыть", callback_data="notif_close")],
    ])

    await query.edit_message_text(
        f"🔔 <b>Уведомления</b>\n\n"
        f"📍 Город: <b>{city}</b>\n"
        f"🔄 Статус: {'✅ Включены' if enabled else '❌ Выключены'}\n"
        f"⏱ Интервал: <b>{interval} ч.</b>\n\n"
        f"{'🟢 Буду присылать погоду каждые ' + str(interval) + ' ч.' if enabled else '⭕ Уведомления отключены.'}",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


async def _send_notif_menu(send_fn, user_id: int) -> None:
    user     = load_user(user_id)
    notif    = user.get("notifications", {"enabled": False, "interval_h": 3})
    enabled  = notif.get("enabled", False)
    interval = notif.get("interval_h", 3)
    city     = user.get("city", "не задан")

    toggle_label = "🔕 Выключить" if enabled else "🔔 Включить"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data="notif_toggle")],
        [InlineKeyboardButton(f"{'✅ ' if interval==h else ''}{h}ч", callback_data=f"notif_set_{h}")
         for h in (1, 2, 4, 6, 12, 24)],
        [InlineKeyboardButton("❌ Закрыть", callback_data="notif_close")],
    ])

    await send_fn(
        f"🔔 <b>Уведомления о погоде</b>\n\n"
        f"📍 Город: <b>{city}</b>\n"
        f"🔄 Статус: {'✅ Включены' if enabled else '❌ Выключены'}\n"
        f"⏱ Интервал: <b>{interval} ч.</b>\n\n"
        "Нажми <b>Включить</b> и выбери интервал:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


def _sync_notif_job(context, user_id: int, user: dict, notif: dict) -> None:
    """Создаёт или удаляет JobQueue-джобу для пользователя."""
    name = f"notif_{user_id}"
    for job in context.job_queue.get_jobs_by_name(name):
        job.schedule_removal()

    if notif.get("enabled") and user.get("city"):
        context.job_queue.run_repeating(
            _notif_job,
            interval=notif.get("interval_h", 3) * 3600,
            first=30,
            data=user_id,
            name=name,
        )


async def _notif_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Периодически отправляет погоду пользователю."""
    user_id = context.job.data
    user    = load_user(user_id)
    city    = user.get("city")
    if not city:
        return

    w = get_current_weather(user["lat"], user["lon"])
    if not w:
        return

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="🔔 <b>Уведомление о погоде</b>\n\n" + _fmt_current(w, city),
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning("Ошибка отправки уведомления %s: %s", user_id, exc)


# ===========================================================================
# Inline-режим
# ===========================================================================

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.inline_query.query.strip()
    if len(q) < 2:
        await update.inline_query.answer([], cache_time=1)
        return

    coords = get_coordinates(q)
    if not coords:
        await update.inline_query.answer(
            [InlineQueryResultArticle(
                id="nf",
                title=f"🔍 «{q}» — город не найден",
                input_message_content=InputTextMessageContent(
                    f"❌ Город «{q}» не найден."
                ),
                description="Проверь написание",
            )],
            cache_time=30,
        )
        return

    lat, lon = coords
    w = get_current_weather(lat, lon)
    if not w:
        await update.inline_query.answer([], cache_time=5)
        return

    main   = w.get("main", {})
    w_info = w.get("weather", [{}])[0]
    wind   = w.get("wind", {})

    temp   = main.get("temp", 0)
    feels  = main.get("feels_like", 0)
    hum    = main.get("humidity", 0)
    desc   = w_info.get("description", "—").capitalize()
    ws     = wind.get("speed", 0)
    city   = w.get("name", q)
    cntry  = w.get("sys", {}).get("country", "")
    icon   = w_info.get("icon", "01d")

    card = (
        f"🌤 <b>{city}{', ' + cntry if cntry else ''}</b>\n"
        f"🌡 <b>{_sign(temp)}°C</b>  🤔 ощущ. {_sign(feels)}°C\n"
        f"💬 {desc}\n"
        f"💧 {hum}%  🌬 {ws:.1f} м/с\n"
        f"<i>🕐 {datetime.now().strftime('%H:%M %d.%m.%Y')}</i>"
    )

    await update.inline_query.answer(
        [InlineQueryResultArticle(
            id=f"w_{city}",
            title=f"🌤 {city} — {_sign(temp)}°C, {desc}",
            input_message_content=InputTextMessageContent(card, parse_mode=ParseMode.HTML),
            description=f"💧 {hum}%  🌬 {ws:.1f} м/с",
            thumbnail_url=f"https://openweathermap.org/img/wn/{icon}@2x.png",
        )],
        cache_time=300,
    )


# ===========================================================================
# Отмена и фоллбэк
# ===========================================================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("↩️ Отменено.", reply_markup=MAIN_KB)
    return ConversationHandler.END


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤔 Не понял команду. Используй кнопки меню.",
        reply_markup=MAIN_KB,
    )


# ===========================================================================
# Восстановление уведомлений после перезапуска
# ===========================================================================

async def _restore_notifications(app: Application) -> None:
    users = get_all_users()
    restored = 0
    for uid_str, data in users.items():
        notif = data.get("notifications", {})
        if notif.get("enabled") and data.get("city"):
            interval = notif.get("interval_h", 3) * 3600
            app.job_queue.run_repeating(
                _notif_job,
                interval=interval,
                first=60,
                data=int(uid_str),
                name=f"notif_{uid_str}",
            )
            restored += 1
    if restored:
        logger.info("🔔 Восстановлено уведомлений: %d", restored)


# ===========================================================================
# Сборка приложения
# ===========================================================================

def _build_conv(entry_text: str, state_id: int, city_handler, entry_handler) -> ConversationHandler:
    """Фабрика однотипных диалогов «введи город»."""
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{entry_text}$"), entry_handler)],
        states={state_id: [MessageHandler(filters.TEXT & ~filters.COMMAND, city_handler)]},
        fallbacks=[MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel)],
        allow_reentry=True,
    )


def main() -> None:
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не задан! Добавь в .env: BOT_TOKEN=токен")
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_restore_notifications)
        .build()
    )

    # ── Команды ──────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", cmd_start))

    # ── Диалог: Текущая погода ───────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_WEATHER}$"), weather_enter)],
        states={WEATHER_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, weather_city)]},
        fallbacks=[MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel)],
        allow_reentry=True,
    ))

    # ── Диалог: Прогноз ──────────────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_FORECAST}$"), forecast_enter)],
        states={FORECAST_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, forecast_city)]},
        fallbacks=[MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel)],
        allow_reentry=True,
    ))

    # ── Диалог: Геолокация ───────────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_LOCATION}$"), location_enter)],
        states={LOCATION_WAIT: [MessageHandler(filters.LOCATION, location_received)]},
        fallbacks=[MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel)],
        allow_reentry=True,
    ))

    # ── Диалог: Сравнить города ──────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_COMPARE}$"), compare_enter)],
        states={
            COMPARE_CITY1: [MessageHandler(filters.TEXT & ~filters.COMMAND, compare_city1)],
            COMPARE_CITY2: [MessageHandler(filters.TEXT & ~filters.COMMAND, compare_city2)],
        },
        fallbacks=[MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel)],
        allow_reentry=True,
    ))

    # ── Диалог: Расширенные данные ───────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_ADVANCED}$"), advanced_enter)],
        states={ADVANCED_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, advanced_city)]},
        fallbacks=[MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel)],
        allow_reentry=True,
    ))

    # ── Уведомления ──────────────────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_NOTIF}$"), notif_menu))

    # ── Inline-клавиатуры ────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(forecast_day_cb, pattern=r"^fd_"))
    app.add_handler(CallbackQueryHandler(notif_cb,        pattern=r"^notif_"))

    # ── Inline-режим ─────────────────────────────────────────────────────────
    app.add_handler(InlineQueryHandler(inline_query))

    # ── Фоллбэк ──────────────────────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    logger.info("🤖 Бот запущен. Ожидаю сообщения...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
