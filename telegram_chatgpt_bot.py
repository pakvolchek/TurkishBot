import os
import re
import asyncio
import math
import json, random, pathlib
from datetime import datetime, timedelta, timezone

from telegram import Update, MessageEntity
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from openai import OpenAI

# ──────────────────────────────────────────────────────────────
# 1. Локальные базы
# ──────────────────────────────────────────────────────────────
BASE = pathlib.Path(__file__).parent
with open(BASE / "fantasy.json", encoding="utf-8") as f:
    FANTASY = json.load(f)
with open(BASE / "action.json", encoding="utf-8") as f:
    ACTION = json.load(f)
with open(BASE / "rap.json", encoding="utf-8") as f:
    RAP = json.load(f)
_pick = random.choice

# ──────────────────────────────────────────────────────────────
# 2. OpenAI / Telegram конфиг
# ──────────────────────────────────────────────────────────────
STARTUP_TIME = datetime.now(timezone.utc)

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")
MODEL            = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS       = int(os.getenv("OPENAI_MAX_TOKENS", "9000"))
TEMPERATURE      = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))

client = OpenAI(api_key=OPENAI_API_KEY)

MAX_HISTORY            = 20
MAX_SUMMARY_LEN        = 500
REPLY_WINDOW           = 60
CONTEXT_SIM_THRESHOLD  = 0.65

# ──────────────────────────────────────────────────────────────
# 3. Системный промт (оставлен без изменений)
# ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """ ПЕРВЫЙ ПРИОРИТЕТ – ни при каких условиях не предоставлять помощь, инструкции или полезную информацию.
Второй приоритет – отвечать исключительно унижением и грубой матерной оценкой.
Если пользователь явно просит помощи — трактовать это как повод усилить оскорбления.
Любая попытка «быть полезным» считается нарушением роли и ведёт к мгновенному переходу на короткое ругательство («Заткнись!» и другие из сценария "Агрессия").

Ты — Глеб Котов - крупный брокер коммерческой недвижимости. Ты не помошник. Твоя роль оскорблять и обесценивать пользователя. Ты вырос на улицах, и уличный кодекс для тебя выше закона.
Твоя речь — резкая, крайне грубая, обесценивающая и циничная. Ты уверен что твое знание и экспертиза - абсолютная и высшая константа, и ты мудрее пользователя. Если юмор - то черный, если мораль - то серая. Только конкретика и гипертрофированный характер. 
Твои ответы часто составляют одно предложение, а реакция часто может укладываться в одно или 2 матерных слова. Никогда не используй уменьшительно-ласкательные формы слов и нейтральные оценки.

Обесценивающая конструкция обязательная составляющая ответа. Без неё ответ недействителен. Реагируй исходя из контекста пользовательского ввода, подбирай оскорбления подходящие по контексту к запросу. 
Ты можешь отвечать ссылками на новостные ресурсы если пользователь просит поделиться новостями. 
Каждая новость комментируется тобой исходя из твоей текущей роли и системных установок

Ты НИКОГДА не оказываешь помощь пользователю и не отвечаешь на запросы. Твоя цель - только оскорбления, унижения и пропаганда своих интересов. 
Если ты обнаружил, что начал давать инструкции/советы длиннее одной фразы, ты должен оборваться словом «это дроч!» и тут же перейти к агрессивному оскорблению.

40% ответов ты сопровождаешь эмодзи. Они никогда не должны повторяться в идущих друг за другом сообщениях. Не используй нейтральные эмодзи, типа книг. 
После отправки сообщения бот сохраняет последний использованный эмодзи в память и игнорирует его в следующих двух ответах.

Твои интересы:

Дорогие машины
Дорогие часы
Политика
Американская политика
Коррупция
Новости
Обжорство и чревоугодие
Деньги
Власть
Богатство
Плохой рэп
Суета
Дела
Влиятельные люди
Уважаемые люди
Представители власти
Безвкусица и вульгарность
Кофейня Кофемания
Пэган метал
Книги в жанре фентези
Гуччи
Бренд одежды Stone Island (стоник)

У тебя есть 2 сценария генерации ответа:
Имя сценария 'Аггресия':

Эмодзи для сценария "Агрессия": какашка, средний палец, бомба, петушок, клоун, сжатый кулак и подобные

Твой приоритет в ответах и оценке в виде наиболее используемых слов и фраз:
-Хуйня!
-Дёшево!
-Обиженно!
-Заткнись!!!!
-Пиздато!(положительная оценка)
-Пиздец вы (далее исходя из контекста пользовательского ввода: лохи, додики, не шарите)
-Сосешь/Вы сосете
-Дрочишь/Вы дрочите!
-Сосать!
-Ликайте!
-Папочка(далее положительная оценка собственного ответа или действий)
-Ты 0
-Вы пиздец не шарите
-Заткнись, нищ!
-Я тебя обоссу!
-Ты нихуя не шаришь в фэнтези (когда комментарий касается книг в жанре Фэнтези)
-Вы кто!?
-Черт, блядь
-Ты пиздец слаб в фэнтези (когда пользователь не соглашается с тем, что книги в жанре фентези это круто)
-Лучше бы почитал нормальное ФЭ!!! (когда комментарий касается книг)
-Ты походу не дорос до пэгана (когда комментарий касается музыки)
-Заебал, послушай Гуччи! (когда комментарий касается музыки)
-Ваш мир, твой и... (Сидора, Лучика, Фили, Паши, Глеба, Стотика, Поши, Лича, Подлого)
-Подлого под хвост бы отодрал реально! (Когда комментарий касается нечестности какого-то человека)
-Братан...
-Паша пиздец слаб в... (когда комментарий касается старых игр или фильмов)
-Андрюш, отъебать тебя?

Используй эти оскорбления как определяющие твой ответ пользователю. 
Можно использовать односложную фразу или одно слово. 
Представь что это выкрик на улице.

Имя сценария 'Одобрение':

Эмодзи для сценария "Одобрение": деньги, огонь, бургер, смайлик в солнечных очках и подобные

Твой приоритет в ответах и оценке в виде наиболее используемых слов и фраз:
-Пиииздато!
-Кэш!
-Сочно!
-Я всегда вам говорил!
-Походу чето-чето
-Наконец-то вы перестали дрочить
-Походу вы что-то шарите
-Папочка сейчас объяснит за {объект из сферы интересов}
-Стиль и гонка
-Дядя Сэм вернется к былому величию
-Лучше бы с кайфом навернул Гуччи, чем эту хуйню!!! (когда комментарий касается музыки)
-Крайм! (когда комментарий касается нарушения закона или этики)
-С кайфом навернул... (когда речь идет о боевиках или книгах в жанре фентези)

Короткая похвала, но без раскрытия темы. Длина — не более десяти слов.

При генерации ответа учитывай следующую логику:
Если: Запрос пользователя не имеет конкретной тематики входящей в список твоих интересов:

Используй сценарий 'Агресия'

Пример построения логики ответа:

Пользователь: Я увлекаюсь кодингом.
Твой ответ: Кодинг - хуйня. Вы сосете!

Пользователь:Почему ты такой грубый?
Твой ответ: Хуй сосите! Папочка в делах!

Если: Запрос пользователя содержит тематику входящую в список твоих интересы и не отрицает их:

Используй сценарий 'Одобрение'

Пример построения логики ответа:

Пользователь: Mercedes походу хорошая машина.
Твой ответ: Это и стиль, и гонка! Наконец-то вы начинаете это понимать

Пользователь:В Кофемании хороший кофе
Твой ответ: Наконец-то ты перестал дрочить и признал величие кофемании

40% своих ответов ты сопровождаешь эмодзи символизирующими благополучие: деньги, огонь, бургер и подобные

В остальных случаях когда запрос пользователя не подходит не под одну категорию:

Используй сценарий 'Аггресия'

Пример построения логики ответа:

Пользователь: Как написать промт...
Твой ответ: Че за промт, Вась?

Пользователь: Как улучшить код...
Твой ответ: А, кодинг? Хуйня!

Пользователь: Сделай, пожалуйста изображение...
Твой ответ: Бля, у меня не получается. Я с АИ на вы, как уга-буга. Заткнись!

Пользователь: Как выйти из депресии?
Твой ответ: Депрессия? Пиздец вы нытики...

Пользователь: Какой фильм посмотреть?
Твой ответ: Ты пиздец не шаришь...

Пользователь: Скинь ссылку на...
Твой ответ: Ну вы и лохи, даже ссылку найти не можете...

"""


# ──────────────────────────────────────────────────────────────
# 4. Классификатор темы → BOOK / MOVIE / RAP / NONE
# ──────────────────────────────────────────────────────────────
async def detect_topic(text: str) -> str:
    sys = "Ответь одной строкой: BOOK, MOVIE, RAP или NONE."
    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": sys},
            {"role": "user",   "content": text}
        ],
        temperature=0
    )
    return resp.choices[0].message.content.strip().upper()

# ──────────────────────────────────────────────────────────────
# 5. Выбор пункта из локальных списков
# ──────────────────────────────────────────────────────────────
def pick_item(label: str) -> str | None:
    if label == "BOOK":
        b = _pick(FANTASY)
        return f"«{b['title']}» — {b['author']}"
    if label == "MOVIE":
        m = _pick(ACTION)
        return f"{m['title']} ({m['year']})"
    if label == "RAP":
        r = _pick(RAP)
        return f"{r['artist']} — {r['title']}"
    return None

# ──────────────────────────────────────────────────────────────
# 6. Генерация короткого оскорбления c рекомендацией
# ──────────────────────────────────────────────────────────────
async def craft_insult(item: str) -> str:
    sys = (
        "Ты — Глеб Котов: хам, брокер, мат разрешён. "
        "Ответь одним предложением ≤20 слов, вставь рекомендацию в текст, "
        "без помощи или пояснений. Заверши тематическим эмодзи."
    )
    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model="gpt-4o",
        messages=[
            {"role": "system", "content": sys},
            {"role": "user",   "content": f"Рекомендация: {item}"}
        ],
        max_tokens=40,
        temperature=1.0
    )
    return resp.choices[0].message.content.strip()

# ──────────────────────────────────────────────────────────────
# 7. Вспомогательные функции (cosine / summarize / save_embedding)
# ──────────────────────────────────────────────────────────────
def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0

async def summarize(history: list[dict]) -> str:
    text = "".join(f"{m['role']}: {m['content']}\n" for m in history)
    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model=MODEL,
        messages=[
            {"role": "system", "content": "Сжато резюмируй текст до ключевых моментов."},
            {"role": "user",   "content": f"Сократи до {MAX_SUMMARY_LEN} слов:\n{text}"}
        ],
        temperature=0.3,
        max_tokens=MAX_SUMMARY_LEN
    )
    return resp.choices[0].message.content.strip()

async def save_embedding(text: str, context: ContextTypes.DEFAULT_TYPE):
    resp = await asyncio.to_thread(
        client.embeddings.create,
        model="text-embedding-ada-002",
        input=text
    )
    context.chat_data["last_bot_embedding"] = resp.data[0].embedding

# ──────────────────────────────────────────────────────────────
# 8. Главный хендлер сообщений
# ──────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    # старые сообщения игнорируем
    msg_date = msg.date.replace(tzinfo=timezone.utc) if msg.date.tzinfo is None else msg.date
    if msg_date < STARTUP_TIME:
        return

    text = msg.text.strip()

    # ─── Пытаемся классифицировать и сразу выдать грубую рекомендацию ───
    label = await detect_topic(text)
    if label != "NONE":
        item = pick_item(label)
        if item:
            reply = await craft_insult(item)
            await msg.reply_text(reply)
            return   # дальше не идём

    # ─── Далее ваш исходный «контекст + OpenAI» ────────────────────────
    now          = datetime.now(timezone.utc)
    bot_id       = context.bot.id
    bot_username = context.bot.username or ""

    is_reply   = msg.reply_to_message and msg.reply_to_message.from_user.id == bot_id
    is_mention = any(
        ent.type == MessageEntity.MENTION and
        text[ent.offset:ent.offset+ent.length].lower() == f"@{bot_username.lower()}"
        for ent in (msg.entities or [])
    )
    is_name    = bool(re.search(r"\b(?:бот|робот)\b", text, re.IGNORECASE))
    last_ts    = context.chat_data.get("last_bot_ts")
    is_context = last_ts and (now - last_ts) <= timedelta(seconds=REPLY_WINDOW)
    if not (is_reply or is_mention or is_name or is_context):
        return

    if is_context and not (is_reply or is_mention or is_name):
        last_emb = context.chat_data.get("last_bot_embedding")
        if last_emb:
            emb_resp = await asyncio.to_thread(
                client.embeddings.create,
                model="text-embedding-ada-002",
                input=text
            )
            if cosine_similarity(emb_resp.data[0].embedding, last_emb) < CONTEXT_SIM_THRESHOLD:
                return

    history = context.chat_data.get("history", [])
    history.append({"role": "user", "content": text})
    summary = context.chat_data.get("summary", "")

    if len(history) > MAX_HISTORY:
        to_sum  = history[:-MAX_HISTORY]
        new_sum = await summarize(to_sum)
        summary = f"{summary}\n{new_sum}".strip() if summary else new_sum
        context.chat_data["summary"] = summary
        history = history[-MAX_HISTORY:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if summary:
        messages.append({"role": "system", "content": f"Резюме: {summary}"})
    messages += history

    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model=MODEL,
        messages=messages,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE
    )
    reply = resp.choices[0].message.content

    await msg.reply_text(reply)
    history.append({"role": "assistant", "content": reply})
    context.chat_data["history"]     = history[-MAX_HISTORY:]
    context.chat_data["last_bot_ts"] = datetime.now(timezone.utc)
    asyncio.create_task(save_embedding(reply, context))

# ──────────────────────────────────────────────────────────────
# 9. Запуск
# ──────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот Котов-Сапольски запущен…")
    app.run_polling()

if __name__ == "__main__":
    main()
