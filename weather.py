"""Погода/климат по названию города через Open-Meteo (без API-ключа)."""
from __future__ import annotations

import html
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import aiohttp
from babel.numbers import get_territory_currencies

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
RATES_URL = "https://open.er-api.com/v6/latest/USD"
# Какие валюты показывать (в единицах местной валюты города)
RATE_CURRENCIES = ("USD", "EUR", "RUB", "CNY")
TIMEOUT = aiohttp.ClientTimeout(total=10)

# Коды погоды WMO -> описание
WEATHER_CODES = {
    0: "☀️ Ясно",
    1: "🌤 Преимущественно ясно",
    2: "⛅️ Переменная облачность",
    3: "☁️ Пасмурно",
    45: "🌫 Туман",
    48: "🌫 Изморозь",
    51: "🌦 Лёгкая морось",
    53: "🌦 Морось",
    55: "🌦 Сильная морось",
    56: "🌧 Ледяная морось",
    57: "🌧 Сильная ледяная морось",
    61: "🌧 Небольшой дождь",
    63: "🌧 Дождь",
    65: "🌧 Сильный дождь",
    66: "🌧 Ледяной дождь",
    67: "🌧 Сильный ледяной дождь",
    71: "🌨 Небольшой снег",
    73: "🌨 Снег",
    75: "❄️ Сильный снег",
    77: "❄️ Снежные зёрна",
    80: "🌦 Небольшие ливни",
    81: "🌧 Ливни",
    82: "⛈ Сильные ливни",
    85: "🌨 Снегопад",
    86: "❄️ Сильный снегопад",
    95: "⛈ Гроза",
    96: "⛈ Гроза с градом",
    99: "⛈ Сильная гроза с градом",
}

HPA_TO_MMHG = 0.750062


class WeatherError(Exception):
    """Ошибка получения данных (сеть/сервис)."""


async def _get_json(session: aiohttp.ClientSession, url: str, params: dict) -> dict:
    try:
        async with session.get(url, params=params, timeout=TIMEOUT) as resp:
            resp.raise_for_status()
            return await resp.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise WeatherError(str(exc)) from exc


async def find_city(session: aiohttp.ClientSession, name: str) -> Optional[dict]:
    data = await _get_json(
        session,
        GEOCODING_URL,
        {"name": name, "count": 1, "language": "ru", "format": "json"},
    )
    results = data.get("results")
    return results[0] if results else None


def timezone_line(tz_name: Optional[str]) -> str:
    """Часовой пояс города и текущее местное время."""
    if not tz_name:
        return ""
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:  # неизвестная зона
        return ""
    offset = now.utcoffset()
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    utc = f"UTC{sign}{hours}" + (f":{mins:02d}" if mins else "")
    return f"🕒 Часовой пояс: {html.escape(tz_name)} ({utc}), сейчас {now:%H:%M}"


async def rates_block(session: aiohttp.ClientSession, country_code: Optional[str]) -> str:
    """Курсы основных валют к местной валюте страны города.
    Любая ошибка не должна ломать основной ответ, поэтому возвращаем пустую строку."""
    if not country_code:
        return ""
    currencies = get_territory_currencies(country_code)
    if not currencies:
        return ""
    local = currencies[0]
    try:
        data = await _get_json(session, RATES_URL, {})
        rates = data["rates"]  # сколько единиц валюты за 1 USD
        if local not in rates:
            return ""
        lines = []
        for code in RATE_CURRENCIES:
            if code == local or code not in rates:
                continue
            value = rates[local] / rates[code]  # 1 code = value local
            digits = 4 if value < 1 else 2
            lines.append(f"1 {code} = {value:,.{digits}f} {local}".replace(",", " "))
    except (WeatherError, KeyError, ZeroDivisionError, ValueError):
        return ""
    if not lines:
        return ""
    return "\n\n💱 <b>Курсы валют</b>\n" + "\n".join(lines)


async def get_climate_text(session: aiohttp.ClientSession, query: str) -> Optional[str]:
    """Возвращает готовый HTML-текст ответа или None, если город не найден."""
    city = await find_city(session, query)
    if city is None:
        return None

    data = await _get_json(
        session,
        FORECAST_URL,
        {
            "latitude": city["latitude"],
            "longitude": city["longitude"],
            "current": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "precipitation",
                    "weather_code",
                    "pressure_msl",
                    "wind_speed_10m",
                ]
            ),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "wind_speed_unit": "ms",
            "timezone": "auto",
            "forecast_days": 1,
        },
    )
    cur = data["current"]
    day = data["daily"]

    place = ", ".join(
        part for part in (city.get("name"), city.get("admin1"), city.get("country")) if part
    )
    description = WEATHER_CODES.get(cur["weather_code"], "—")
    pressure = round(cur["pressure_msl"] * HPA_TO_MMHG)

    tz_line = timezone_line(city.get("timezone"))
    rates = await rates_block(session, city.get("country_code"))

    return (
        f"📍 <b>{html.escape(place)}</b>\n"
        + (f"{tz_line}\n" if tz_line else "")
        + f"{description}\n\n"
        f"🌡 Температура: <b>{cur['temperature_2m']:+.0f}°C</b> "
        f"(ощущается как {cur['apparent_temperature']:+.0f}°C)\n"
        f"📈 Сегодня: от {day['temperature_2m_min'][0]:+.0f}°C до {day['temperature_2m_max'][0]:+.0f}°C\n"
        f"💧 Влажность: {cur['relative_humidity_2m']}%\n"
        f"💨 Ветер: {cur['wind_speed_10m']:.1f} м/с\n"
        f"🧭 Давление: {pressure} мм рт. ст.\n"
        f"🌧 Осадки: {cur['precipitation']} мм (за день: {day['precipitation_sum'][0]} мм)"
        + rates
    )
