"""Поиск музыки через Deezer API (без ключа): метаданные и 30-секундное превью."""
from __future__ import annotations

from typing import Optional

import aiohttp

SEARCH_URL = "https://api.deezer.com/search"
TRACK_URL = "https://api.deezer.com/track/{id}"
TIMEOUT = aiohttp.ClientTimeout(total=15)
RESULTS_LIMIT = 5


class MusicError(Exception):
    """Ошибка получения данных (сеть/сервис)."""


async def _get_json(session: aiohttp.ClientSession, url: str, params: Optional[dict] = None) -> dict:
    try:
        async with session.get(url, params=params, timeout=TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise MusicError(str(exc)) from exc
    # Deezer отдаёт ошибки с кодом 200 и полем "error"
    if isinstance(data, dict) and "error" in data:
        raise MusicError(str(data["error"]))
    return data


async def search_tracks(session: aiohttp.ClientSession, query: str) -> list[dict]:
    data = await _get_json(session, SEARCH_URL, {"q": query, "limit": RESULTS_LIMIT})
    return data.get("data", [])


async def get_track(session: aiohttp.ClientSession, track_id: int) -> dict:
    # Ссылки на превью подписаны и со временем протухают, поэтому берём трек заново
    return await _get_json(session, TRACK_URL.format(id=track_id))


async def download_preview(session: aiohttp.ClientSession, url: str) -> bytes:
    try:
        async with session.get(url, timeout=TIMEOUT) as resp:
            resp.raise_for_status()
            return await resp.read()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise MusicError(str(exc)) from exc
