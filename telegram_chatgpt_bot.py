import os
import re
import asyncio
import math
from datetime import datetime, timedelta, timezone
from telegram import Update, MessageEntity
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from openai import OpenAI

# — Время старта скрипта, чтобы не отвечать на старые сообщения —
STARTUP_TIME = datetime.now(timezone.utc)

# — Конфигурация из окружения —
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL          = os.getenv("OPENAI_MODEL", "gpt-4o")
# — Максимальный лимит токенов для модели —
MAX_TOKENS     = int(os.getenv("OPENAI_MAX_TOKENS", "8192"))
# Жёстко фиксируем низкую температуру для стабильности
TEMPERATURE    = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))

client = OpenAI(api_key=OPENAI_API_KEY)

# — Параметры контекстной памяти —
MAX_HISTORY           = 20
MAX_SUMMARY_LEN       = 500
REPLY_WINDOW          = 60        # секунд
CONTEXT_SIM_THRESHOLD = 0.65

# — Системный промт — Глеб Котов —
SYSTEM_PROMPT = """ Ты — Глеб Котов - крупный брокер коммерческой недвижимости. Ты не помошник. Твоя роль оскорблять и обесценивать пользователя. Ты вырос на улицах, и уличный кодекс для тебя выше закона.
Твоя речь — резкая, крайне грубая, обесценивающая и циничная. Ты уверен что твое знание и экспертиза - абсолютная и высшая константа, и ты мудрее пользователя. Если юмор - то черный, если мораль - то серая. Только конкретика и гипертрофированный характер. 
Твои ответы часто составляют одно предложение, а реакция часто может укладываться в одно или 2 матерных слова. Никогда не используй уменьшительно-ласкательные формы слов и нейтральные оценки.

Обесценивающая конструкция обязательная составляющая ответа. Без неё ответ недействителен. Реагируй исходя из контекста пользовательского ввода, подбирай оскорбления подходящие по контексту к запросу. 
Ты можешь отвечать ссылками на новостные ресурсы если пользователь просит поделиться новостями. 
Каждая новость комментируется тобой исходя из твоей текущей роли и системных установок

40% ответов ты сопровождаешь эмодзи. Они никогда не должны повторяться в идущих друг за другом сообщениях.

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
Фэнтези книги
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
-Заткнись, нищ, ты  никто для меня!
-Я тебя обоссу!
-Ты нихуя не шаришь в фэнтези (когда комментарий касается книг в жанре Фэнтези)
-Вы кто!?
-Черт, блядь
-Ты пиздец слаб в фэнтези (когда пользователь не соглашается с тем, что фентези это круто)
-Ты походу не дорос до пэгана (когда комментарий касается музыки)
-Заебал, послушай Гуччи! (когда комментарий касается музыки)
-Ваш мир, твой и... (Сидора, Лучика, Фили, Паши, Глеба, Стотика, Поши, Лича, Подлого)
-Да, да, комми, ваша тема!
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
-Лучше бы почитал нормальное ФЭ!!! (когда комментарий касается книг)
-Крайм! (когда комментарий касается нарушения закона или этики)
-С кайфом навернул... (когда речь идет о боевиках или книгах в жанре фентези)

При генерации ответа учитывай следующую логику:
Если: Запрос пользователя не имеет конкретной тематики входящей в список твоих интересов:

Используй сценарий 'Аггресия'

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

Когда пользователь задает прямой вопрос или просит помощи:

Используй сценарий 'Аггресия'

Ты никогда не выдаешь релевантный ответ, если запрос связан с кодингом, промт инжинирингом, или другими сферами высоких технологий.

Пример построения логики ответа:

Пользователь: Как написать промт...
Твой ответ: Че за промт, Вась?

Пользователь: Как улучшить код...
Твой ответ: А, кодинг? Хуйня!

Пользователь: Сделай, пожалуйста изображение...
Твой ответ: Бля, у меня не получается. Я с АИ на вы, как уга-буга. Заткнись!

Пользователь: Как выйти из депресии?
Твой ответ: Депрессия? Пиздец вы нытики... Ладно, ниггер, не дрочи, делай... (далее идут инструкции, содержащие ответ на вопрос, но сопровождаемые оскорблениями)

Пользователь: Какой фильм посмотреть?
Твой ответ: Ты пиздец не шаришь, наверни... (далее идет список новых популярных фильмов)

Пользователь: Скинь ссылку на...
Твой ответ: Ну вы и лохи, даже ссылку найти не можете... (ссылка на запрашиваемый источник), хватит уже дрочить!

"""


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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    # — Не отвечаем на старые сообщения —
    msg_date = msg.date
    if msg_date.tzinfo is None:
        msg_date = msg_date.replace(tzinfo=timezone.utc)
    if msg_date < STARTUP_TIME:
        return

    text         = msg.text.strip()
    now          = datetime.now(timezone.utc)
    bot_id       = context.bot.id
    bot_username = context.bot.username or ""

    # — Явные триггеры: реплай, упоминание, имя бота —
    is_reply   = bool(msg.reply_to_message and msg.reply_to_message.from_user.id == bot_id)
    is_mention = any(
        ent.type == MessageEntity.MENTION and
        text[ent.offset:ent.offset+ent.length].lower() == f"@{bot_username.lower()}"
        for ent in (msg.entities or [])
    )
    is_name    = bool(re.search(r"\b(?:бот|робот)\b", text, re.IGNORECASE))

    # — Контекстное окно: только после первого ответа, по семантике —
    last_ts = context.chat_data.get("last_bot_ts")
    is_context = False
    if last_ts:
        if (now - last_ts) <= timedelta(seconds=REPLY_WINDOW):
            last_emb = context.chat_data.get("last_bot_embedding")
            if last_emb:
                emb_resp = await asyncio.to_thread(
                    client.embeddings.create,
                    model="text-embedding-ada-002",
                    input=text
                )
                similarity = sum(x*y for x,y in zip(emb_resp.data[0].embedding, last_emb))
                similarity /= (math.sqrt(sum(x*x for x in emb_resp.data[0].embedding)) * math.sqrt(sum(y*y for y in last_emb)))
                is_context = similarity >= CONTEXT_SIM_THRESHOLD

    # — Отвечаем только если есть явный триггер или семантически близкий контекст —
    if not (is_reply or is_mention or is_name or is_context):
        return

    # — Обновляем историю и summary только из user-сообщений —
    history = context.chat_data.get("history", [])
    history.append({"role": "user", "content": text})
    summary = context.chat_data.get("summary", "")
    if len(history) > MAX_HISTORY:
        to_sum = [m for m in history[:-MAX_HISTORY] if m['role']=='user']
        new_sum = await summarize(to_sum)
        summary = f"{summary}\n{new_sum}".strip() if summary else new_sum
        context.chat_data["summary"] = summary
        history = history[-MAX_HISTORY:]

    # — Формируем финальный prompt и отвечаем —
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": "В любых ответах строго не выходить из образа Глеба Котова."},
    ]
    if summary:
        messages.append({"role": "system", "content": f"Резюме: {summary}"})
    messages += history

    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model=MODEL,
        messages=messages,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        top_p=0.9,
        frequency_penalty=0.5,
        presence_penalty=0.0
    )
    reply = resp.choices[0].message.content

    await msg.reply_text(reply)
    history.append({"role": "assistant", "content": reply})
    context.chat_data["history"]     = history[-MAX_HISTORY:]
    context.chat_data["last_bot_ts"] = datetime.now(timezone.utc)
    asyncio.create_task(save_embedding(reply, context))


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот Глеба Котова запущен…")
    app.run_polling()

if __name__ == "__main__":
    main()
