# fetch_once.py
# ────────────────────────────────────────────────────────────────────
# ОДНОРАЗОВО загружает три открытых источника и создаёт локальные
# JSON-файлы: fantasy.json, action.json, rap.json.
# Запускайте в корне проекта (F:\TurkishBot):
#     python fetch_once.py
# Дальше боту интернет больше не нужен.
# ────────────────────────────────────────────────────────────────────

import json
import re
import html
import requests

# ────────────────────────────────────────────────────────────────────
# 1. ФЭНТЕЗИ-КНИГИ  (Open Library, без ключей)
# ────────────────────────────────────────────────────────────────────
fantasy_url = "https://openlibrary.org/subjects/fantasy.json?limit=500"
fantasy_raw = requests.get(fantasy_url, timeout=30).json()["works"]

FANTASY = [
    {
        "title":  w["title"],
        "author": ", ".join(a["name"] for a in w["authors"])
    }
    for w in fantasy_raw
]

# ────────────────────────────────────────────────────────────────────
# 2. «ТУПЫЕ» БОЕВИКИ  (GitHub wikipedia-movie-data, жанр Action)
# ────────────────────────────────────────────────────────────────────
movies_src = (
    "https://raw.githubusercontent.com/prust/"
    "wikipedia-movie-data/master/movies.json"
)
movies_raw = requests.get(movies_src, timeout=60).json()

ACTION = [
    {"title": m["title"], "year": m["year"]}
    for m in movies_raw
    if "Action" in m.get("genres", []) and m.get("year", 0) >= 1980
][:500]  # возьмём первые 500

# ────────────────────────────────────────────────────────────────────
# 3. ПЛОХОЙ РЭП  (страница Wiki «List of music considered the worst»)
# ────────────────────────────────────────────────────────────────────
worst_url = "https://en.wikipedia.org/wiki/List_of_music_considered_the_worst"
html_text = requests.get(worst_url, timeout=30).text

# «“Название трека” – Исполнитель (год)»  — берём 2010-е и 2020-е
raw_songs = re.findall(r'“([^”]+)”[^–—]+–\s*([^<]+?)\s*\((20\d{2})', html_text)

RAP = [
    {
        "title":  html.unescape(title.strip()),
        "artist": html.unescape(artist.strip()),
        "year":   year
    }
    for title, artist, year in raw_songs
    if "rap" in title.lower() or "rap" in artist.lower()  # грубый фильтр
][:300]

# ────────────────────────────────────────────────────────────────────
# 4. Записываем на диск
# ────────────────────────────────────────────────────────────────────
for name, data in (("fantasy", FANTASY),
                   ("action",  ACTION),
                   ("rap",     RAP)):
    with open(f"{name}.json", "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)

print("Готово! ",
      { "fantasy": len(FANTASY),
        "action":  len(ACTION),
        "rap":     len(RAP) })
