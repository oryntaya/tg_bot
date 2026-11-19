"""Нормы законодательства РК: разбор PDF кодексов в SQLite и поиск статьи.

Сборка базы (после добавления или замены PDF в data/pdf/):
    .venv/bin/python laws.py
"""
from __future__ import annotations

import re
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "data" / "pdf"
DB_PATH = BASE_DIR / "data" / "laws.db"

# код -> (название, ссылка на источник, PDF-файлы по порядку)
CODES: dict[str, dict] = {
    "УК": {
        "title": "Уголовный кодекс РК",
        "url": "https://adilet.zan.kz/rus/docs/K1400000226",
        "files": ["uk.pdf"],
    },
    "ГК": {
        "title": "Гражданский кодекс РК",
        "url": "https://adilet.zan.kz/rus/docs/K940001000_",
        "files": ["gk_obsh.pdf", "gk_osob.pdf"],
        # Общая часть (ст. 1–405) и Особенная часть (ст. 406–1124) — отдельные документы
        "file_urls": {
            "gk_obsh.pdf": "https://adilet.zan.kz/rus/docs/K940001000_",
            "gk_osob.pdf": "https://adilet.zan.kz/rus/docs/K990000409_",
        },
    },
    "ТК": {
        "title": "Трудовой кодекс РК",
        "url": "https://adilet.zan.kz/rus/docs/K1500000414",
        "files": ["tk.pdf"],
    },
    "КоАП": {
        "title": "Кодекс РК об административных правонарушениях",
        "url": "https://adilet.zan.kz/rus/docs/K1400000235",
        "files": ["koap.pdf"],
    },
}

# Как пользователь может написать название кодекса -> канонический код
ALIASES = {
    "ук": "УК", "ук рк": "УК", "уголовный": "УК",
    "гк": "ГК", "гк рк": "ГК", "гражданский": "ГК",
    "тк": "ТК", "тк рк": "ТК", "трудовой": "ТК",
    "коап": "КоАП", "коап рк": "КоАП", "кoап": "КоАП", "административный": "КоАП",
    # латиница
    "uk": "УК", "gk": "ГК", "tk": "ТК", "koap": "КоАП",
}

_PAGE_FOOTER = re.compile(r"^\d+ / \d+$")
_ARTICLE = re.compile(r"^Статья (\d+(?:-\d+)*)\.\s*(.*)$")
# Структурные заголовки (после них идёт название главы и т. п., к статье не относятся)
_STRUCTURE = re.compile(
    r"^(РАЗДЕЛ|Раздел|ГЛАВА|Глава|ПАРАГРАФ|Параграф|ПОДРАЗДЕЛ|Подраздел|ОБЩАЯ ЧАСТЬ|ОСОБЕННАЯ ЧАСТЬ|"
    r"ОСОБЕННАЯ ЧАСТЬ|Общая часть|Особенная часть)\b"
)
_PARA_START = re.compile(r"^(\d+[.)]|\d+-\d+[.)]|[а-я]\))\s")


def _read_pdf_text(path: Path) -> str:
    from pypdf import PdfReader  # нужен только при сборке базы

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def parse_articles(text: str) -> list[tuple[str, str, str]]:
    """Режет текст кодекса на статьи: [(номер, название, текст)]."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if not _PAGE_FOOTER.match(ln.strip())]

    articles: list[tuple[str, str, list[str]]] = []
    current: Optional[tuple[str, str, list[str]]] = None
    skipping = False  # внутри структурного заголовка до следующей статьи

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = _ARTICLE.match(line)
        if m:
            number, title = m.group(1), m.group(2).strip()
            # Название статьи может переноситься на следующую строку
            while (
                i + 1 < len(lines)
                and len(title) > 55
                and lines[i + 1].strip()
                and not _PARA_START.match(lines[i + 1].strip())
                and not _ARTICLE.match(lines[i + 1].strip())
                and not _STRUCTURE.match(lines[i + 1].strip())
                and lines[i + 1].strip()[0].islower()
            ):
                title += " " + lines[i + 1].strip()
                i += 1
            current = (number, title, [])
            articles.append(current)
            skipping = False
        elif current is not None:
            if _STRUCTURE.match(line):
                skipping = True
            if not skipping:
                current[2].append(line)
        i += 1

    result = []
    for number, title, body in articles:
        body_text = "\n".join(_strip_trailing_footnotes(body)).strip()
        result.append((number, title, body_text))
    return result


def _strip_trailing_footnotes(body: list[str]) -> list[str]:
    """Убирает «Сноска. …» в конце статьи (история изменений), сноски в середине остаются."""
    cut = None
    for i in range(len(body) - 1, -1, -1):
        line = body[i].strip()
        if line.startswith("Сноска."):
            cut = i
        elif _PARA_START.match(line):
            break
    return body[:cut] if cut is not None else body


def build_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE articles (code TEXT, number TEXT, title TEXT, text TEXT, url TEXT, "
        "PRIMARY KEY (code, number))"
    )
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    for code, info in CODES.items():
        total = 0
        for fname in info["files"]:
            path = PDF_DIR / fname
            if not path.exists():
                print(f"[{code}] нет файла {path}, пропускаю", file=sys.stderr)
                continue
            url = info.get("file_urls", {}).get(fname, info["url"])
            for number, title, body in parse_articles(_read_pdf_text(path)):
                con.execute(
                    "INSERT OR REPLACE INTO articles VALUES (?, ?, ?, ?, ?)",
                    (code, number, title, body, url),
                )
                total += 1
        print(f"{code}: {total} статей")
    con.execute("INSERT INTO meta VALUES ('built', ?)", (date.today().isoformat(),))
    con.commit()
    con.close()


# ---------- поиск (используется ботом) ----------

def normalize_code(name: str) -> Optional[str]:
    return ALIASES.get(name.strip().lower().replace(".", ""))


def parse_query(args: str) -> Optional[tuple[str, str]]:
    """'188 УК' / 'УК 188' / '188-1 ук' -> ('УК', '188-1'); при ошибке None."""
    parts = args.replace("ст.", " ").replace("статья", " ").split()
    if len(parts) < 2:
        return None
    number = next((p for p in parts if re.fullmatch(r"\d+(-\d+)?", p)), None)
    code_words = " ".join(p for p in parts if p != number)
    code = normalize_code(code_words)
    if number is None or code is None:
        return None
    return code, number


def get_article(code: str, number: str) -> Optional[dict]:
    if not DB_PATH.exists():
        return None
    con = sqlite3.connect(DB_PATH)
    try:
        row = con.execute(
            "SELECT title, text, url FROM articles WHERE code = ? AND number = ?", (code, number)
        ).fetchone()
        built = con.execute("SELECT value FROM meta WHERE key = 'built'").fetchone()
    finally:
        con.close()
    if row is None:
        return None
    return {
        "code": code,
        "code_title": CODES[code]["title"],
        "url": row[2],
        "number": number,
        "title": row[0],
        "text": row[1],
        "built": built[0] if built else "",
    }


if __name__ == "__main__":
    build_db()
