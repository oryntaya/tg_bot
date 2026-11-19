# tg_bot

Телеграм-бот (aiogram 3, long polling):

- город → погода, часовой пояс и курсы валют;
- `/music запрос` → поиск музыки в Deezer, превью 30 сек;
- `/ст 188 УК` (`/st`, `/law`) → текст статьи УК, ГК, ТК, КоАП РК со ссылкой на adilet.zan.kz.

## Запуск

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "BOT_TOKEN=<токен от @BotFather>" > .env
.venv/bin/python bot.py
```

## База законов (`/ст`)

Скачай PDF кодексов с adilet.zan.kz (нужен вход в аккаунт) и положи в `data/pdf/` как
`uk.pdf`, `gk_obsh.pdf`, `gk_osob.pdf`, `tk.pdf`, `koap.pdf`, затем:

```bash
.venv/bin/python laws.py   # собирает data/laws.db
```

Подробности устройства проекта — в `CLAUDE.md`.
