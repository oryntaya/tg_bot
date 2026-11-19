from __future__ import annotations

import asyncio
import html
import logging
import os

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from dotenv import load_dotenv

import laws
from music import MusicError, download_preview, get_track, search_tracks
from weather import WeatherError, get_climate_text

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

dp = Dispatcher()


@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Отправь мне название города, и я пришлю погоду и климатические данные.\n"
        "Например: <code>Алматы</code> или <code>London</code>\n\n"
        "🎵 Поиск музыки: <code>/music Imagine Dragons Believer</code>\n"
        "⚖️ Статья закона РК: <code>/ст 188 УК</code> (кодексы: УК, ГК, ТК, КоАП)"
    )


MAX_CHUNK = 3500  # лимит Telegram 4096 символов, с запасом на заголовок, подвал и разметку


def split_text(text: str, limit: int = MAX_CHUNK) -> list[str]:
    """Режет длинный текст на части по строкам (строка длиннее лимита режется жёстко)."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit and current:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


@dp.message(Command("ст", "st", "law"))
async def law_article(message: Message, command: CommandObject) -> None:
    parsed = laws.parse_query(command.args or "")
    if parsed is None:
        await message.answer(
            "⚖️ Формат: <code>/ст номер кодекс</code>\n"
            "Например: <code>/ст 188 УК</code>, <code>/ст 1 ГК</code>, <code>/ст 52 ТК</code>, "
            "<code>/ст 50 КоАП</code>\n"
            "Кодексы: УК, ГК, ТК, КоАП (Республика Казахстан). Можно и латиницей: <code>/law 188 uk</code>"
        )
        return

    code, number = parsed
    article = laws.get_article(code, number)
    if article is None:
        await message.answer(f"🤷 Статья {html.escape(number)} в {html.escape(code)} не найдена.")
        return

    header = (
        f"⚖️ <b>Статья {html.escape(article['number'])}. {html.escape(article['title'])}</b>\n"
        f"<i>{html.escape(article['code_title'])}</i>\n"
    )
    footer = (
        f"\n🔗 <a href=\"{article['url']}\">Источник: adilet.zan.kz</a>\n"
        f"<i>Текст на {article['built']}; проверяй актуальную редакцию по ссылке.</i>"
    )
    chunks = split_text(html.escape(article["text"]))
    chunks[0] = f"{header}\n{chunks[0]}"
    chunks[-1] = f"{chunks[-1]}\n{footer}"
    no_preview = LinkPreviewOptions(is_disabled=True)
    for chunk in chunks:
        await message.answer(chunk, link_preview_options=no_preview)


@dp.message(Command("music"))
async def music_search(message: Message, command: CommandObject, http: aiohttp.ClientSession) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.answer("🎵 Напиши, что искать: <code>/music название или исполнитель</code>")
        return

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        tracks = await search_tracks(http, query)
    except MusicError:
        log.exception("music service error")
        await message.answer("⚠️ Сервис музыки сейчас недоступен, попробуй чуть позже.")
        return

    # Без превью отправить нечего
    tracks = [t for t in tracks if t.get("preview")]
    if not tracks:
        await message.answer("🤷 Ничего не нашёл. Попробуй изменить запрос.")
        return

    rows = [
        [
            InlineKeyboardButton(
                text=f"{t['artist']['name']} — {t['title_short']} ({t['album']['title']})"[:60],
                callback_data=f"mt:{t['id']}",
            )
        ]
        for t in tracks
    ]
    await message.answer(
        "🎵 Нашёл вот что, выбери трек:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


@dp.callback_query(F.data.startswith("mt:"))
async def music_track(call: CallbackQuery, http: aiohttp.ClientSession) -> None:
    await call.answer("Загружаю превью…")
    try:
        track = await get_track(http, int(call.data.split(":", 1)[1]))
        audio = await download_preview(http, track["preview"])
    except (MusicError, KeyError, ValueError):
        log.exception("music track error")
        await call.message.answer("⚠️ Не получилось загрузить трек, попробуй другой.")
        return

    artist = track["artist"]["name"]
    title = track["title"]
    await call.message.bot.send_chat_action(call.message.chat.id, ChatAction.UPLOAD_VOICE)
    await call.message.answer_audio(
        BufferedInputFile(audio, filename=f"{artist} - {title}.mp3"),
        title=title,
        performer=artist,
        duration=30,
        caption=(
            f"💿 {html.escape(track['album']['title'])}\n"
            f"⏱ Превью 30 сек. Полный трек: <a href=\"{track['link']}\">слушать в Deezer</a>"
        ),
    )


@dp.message(F.text & ~F.text.startswith("/"))
async def city_handler(message: Message, http: aiohttp.ClientSession) -> None:
    query = message.text.strip()
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        text = await get_climate_text(http, query)
    except WeatherError:
        log.exception("weather service error")
        await message.answer("⚠️ Сервис погоды сейчас недоступен, попробуй чуть позже.")
        return

    if text is None:
        await message.answer("🤷 Не нашёл такой город. Проверь название и попробуй ещё раз.")
        return
    await message.answer(text)


async def skip_offline_updates(bot: Bot) -> None:
    """Подтверждает у Telegram все обновления, накопленные пока бот был офлайн,
    чтобы они не обрабатывались. Вызывать до запуска polling."""
    await bot.delete_webhook(drop_pending_updates=True)
    # offset=-1 возвращает только последнее обновление в очереди
    last = await bot.get_updates(offset=-1, limit=1, timeout=0)
    if last:
        # Подтверждаем его (и всё, что было раньше) — Telegram удалит их из очереди
        await bot.get_updates(offset=last[0].update_id + 1, limit=1, timeout=0)
        log.info("Пропущены сообщения, пришедшие в офлайне (последнее update_id=%s)", last[0].update_id)
    else:
        log.info("Сообщений, пришедших в офлайне, нет")


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN не задан в .env")

    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    async with aiohttp.ClientSession() as http:
        dp["http"] = http
        # Сообщения, пришедшие пока бот был офлайн, игнорируем
        await skip_offline_updates(bot)
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
