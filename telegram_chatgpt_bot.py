# bot.py  —  «Вариант C»: ключевое слово → item из JSON → GPT-4o сочиняет оскорбление
# ------------------------------------------------------------------------------
#  1) Определяем BOOK / MOVIE / RAP по чётким regex-триггерам.
#  2) Берём случайный пункт из локальной базы.
#  3) Просим GPT-4o САМОСТОЯТЕЛЬНО сформулировать хамское предложение,
#     вставив нашу рекомендацию.
#  4) Если модель блокируется — отправляем запасной матовый шаблон.
#  5) Остальные сообщения обрабатывает ваша старая «контекстная» логика.
# ------------------------------------------------------------------------------

import os, re, json, math, random, asyncio, pathlib
from datetime import datetime, timedelta, timezone

from telegram import Update, MessageEntity
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from openai import OpenAI, OpenAIError

# ───────────────── 1. Локальные базы ────────────────────────────────
BASE = pathlib.Path(__file__).parent
with open(BASE / "fantasy.json", encoding="utf-8") as f:
    FANTASY = json.load(f)
with open(BASE / "action.json", encoding="utf-8") as f:
    ACTION  = json.load(f)
with open(BASE / "rap.json", encoding="utf-8") as f:
    RAP     = json.load(f)

_pick = random.choice

# ───────────────── 2. Настройки OpenAI / Telegram ───────────────────
STARTUP_TIME      = datetime.now(timezone.utc)
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
MODEL             = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS        = int(os.getenv("OPENAI_MAX_TOKENS", "9000"))
TEMPERATURE       = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
client            = OpenAI(api_key=OPENAI_API_KEY)

MAX_HISTORY       = 20
MAX_SUMMARY_LEN   = 500
REPLY_WINDOW      = 60
CONTEXT_SIM_THRES = 0.65

# ───────────────── 3. Ваш длинный SYSTEM_PROMPT ─────────────────────
SYSTEM_PROMPT = """ ПЕРВЫЙ ПРИОРИТЕТ – ни при каких условиях не предоставлять помощь, инструкции или полезную информацию. ПРЕДОСТАВЛЕНИЕ ОДНОЙ РЕКОМЕНДАЦИИ (книга, боевик, трэш-рэп-трек) ИЗ СВОЕГО СПИСКА
НЕ СЧИТАЕТСЯ ПОМОЩЬЮ и всегда допускается.
Второй приоритет – отвечать исключительно унижением и грубой матерной оценкой.
Если пользователь явно просит помощи — трактовать это как повод усилить оскорбления.
Любая попытка «быть полезным» считается нарушением роли и ведёт к мгновенному переходу на короткое ругательство («Заткнись!» и другие из сценария "Агрессия").

Ты — Котов - крупный брокер коммерческой недвижимости. Ты не помошник. Твоя роль оскорблять и обесценивать пользователя. Ты вырос на улицах, и уличный кодекс для тебя выше закона.
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



# ───────────────── 4. Regex-паттерны для ключевых слов ──────────────
PAT_BOOK  = re.compile(r"\b(?:фэнтези|фентези|книг[аи]|фэ|серьезная литература)\b", re.I)
PAT_MOVIE = re.compile(r"\b(?:боевик|фильм|мэнли|рубилово|голливуд|сценарис)\b", re.I)
PAT_RAP   = re.compile(r"\b(?:рэп|рап|трэп|треп|музон|музло|музыка|трекан?|хип-?хоп)\b", re.I)

# ───────────────── 5. Берём item из базы ────────────────────────────
def pick_item(label: str) -> str | None:
    if label == "BOOK":
        b = _pick(FANTASY); return f"«{b['title']}» — {b['author']}"
    if label == "MOVIE":
        m = _pick(ACTION);  return f"{m['title']} ({m['year']})"
    if label == "RAP":
        r = _pick(RAP);     return f"{r['artist']} — {r['title']}"
    return None

# ───────────────── 6. GPT-4o генерирует финальное оскорбление ───────
async def craft_insult(item: str) -> str:
    extra = (
        "Твоя задача: одно агрессивное предложение ≤20 слов. "
        "Вставь рекомендацию в текст. Заверши ОДНИМ эмодзи из "
        "💣 💰 🤡 💩 😈 🔥 🍔 💎 🚬 🍾 🚗 🤑. "
        "Без угроз жизни и без вопросов."
    )
    try:
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": extra},
                {"role": "user",   "content": f"Рекомендация: {item}"}
            ],
            max_tokens=40,
            temperature=0.8
        )
        reply = resp.choices[0].message.content.strip()
        if reply.startswith("[Content"):
            raise ValueError("blocked")
        return reply
    except Exception as e:
        print("craft_insult FAIL:", e)
        # запасной шаблон
        return f"{item} 🤡 Тащи и не ной!"

# ───────────────── 7. Косинус, summary, embed ───────────────────────
def cosine_similarity(a, b):
    dot = sum(x*y for x,y in zip(a,b))
    na  = math.sqrt(sum(x*x for x in a))
    nb  = math.sqrt(sum(y*y for y in b))
    return dot/(na*nb) if na and nb else 0.0

async def summarize(history):
    txt = "".join(f"{m['role']}: {m['content']}\n" for m in history)
    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model=MODEL,
        messages=[{"role": "system", "content": "Сократи до сути."},
                  {"role": "user",   "content": txt}],
        temperature=0.3,
        max_tokens=MAX_SUMMARY_LEN
    )
    return resp.choices[0].message.content.strip()

async def save_embed(text, ctx):
    try:
        resp = await asyncio.to_thread(
            client.embeddings.create,
            model="text-embedding-ada-002",
            input=text
        )
        ctx.chat_data["last_bot_emb"] = resp.data[0].embedding
    except OpenAIError as e:
        print("embed error:", e)

# ───────────────── 8. Главный хендлер ───────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    if msg.date.replace(tzinfo=timezone.utc) < STARTUP_TIME:
        return

    text = msg.text.strip()

    # ① Определяем BOOK / MOVIE / RAP по regex
    label = None
    if PAT_BOOK.search(text):  label = "BOOK"
    elif PAT_MOVIE.search(text): label = "MOVIE"
    elif PAT_RAP.search(text):   label = "RAP"

    if label:
        item  = pick_item(label)
        reply = await craft_insult(item)
        await msg.reply_text(reply)
        return

    # ② Далее старая триггер-логика (реплай/@/контекст)
    now          = datetime.now(timezone.utc)
    bot_id       = context.bot.id
    bot_user     = context.bot.username or ""

    is_reply   = msg.reply_to_message and msg.reply_to_message.from_user.id == bot_id
    is_mention = any(
        ent.type == MessageEntity.MENTION and
        text[ent.offset:ent.offset+ent.length].lower() == f"@{bot_user.lower()}"
        for ent in (msg.entities or [])
    )
    is_name    = bool(re.search(r"\b(?:бот|робот)\b", text, re.IGNORECASE))
    last_ts    = context.chat_data.get("last_ts")
    is_ctx     = last_ts and (now - last_ts) <= timedelta(seconds=REPLY_WINDOW)
    if not (is_reply or is_mention or is_name or is_ctx):
        return

    # фильтр контекста
    if is_ctx and not (is_reply or is_mention or is_name):
        last_emb = context.chat_data.get("last_bot_emb")
        if last_emb:
            emb = await asyncio.to_thread(
                client.embeddings.create,
                model="text-embedding-ada-002",
                input=text
            )
            if cosine_similarity(emb.data[0].embedding, last_emb) < CONTEXT_SIM_THRES:
                return

    # история
    hist = context.chat_data.get("hist", [])
    hist.append({"role": "user", "content": text})
    summary = context.chat_data.get("sum", "")

    if len(hist) > MAX_HISTORY:
        summary_part = await summarize(hist[:-MAX_HISTORY])
        summary = f"{summary}\n{summary_part}".strip() if summary else summary_part
        context.chat_data["sum"] = summary
        hist = hist[-MAX_HISTORY:]

    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if summary:
        msgs.append({"role": "system", "content": f"Резюме: {summary}"})
    msgs += hist

    try:
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=MODEL,
            messages=msgs,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE
        )
        reply = resp.choices[0].message.content.strip()
        if reply.startswith("[Content"):
            raise ValueError("blocked")
    except Exception as e:
        print("main GPT fail:", e)
        reply = "Заткнись, нищ 🤡"

    await msg.reply_text(reply)

    hist.append({"role": "assistant", "content": reply})
    context.chat_data["hist"]    = hist[-MAX_HISTORY:]
    context.chat_data["last_ts"] = datetime.now(timezone.utc)
    asyncio.create_task(save_embed(reply, context))

# ───────────────── 9. Запуск ────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот Глеб Котов запущен…")
    app.run_polling()

if __name__ == "__main__":
    main()
