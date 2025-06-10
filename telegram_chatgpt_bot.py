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
MAX_TOKENS     = int(os.getenv("OPENAI_MAX_TOKENS", "500"))
TEMPERATURE    = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))

client = OpenAI(api_key=OPENAI_API_KEY)

# — Параметры контекстной памяти и фильтрации —
MAX_HISTORY           = 20
MAX_SUMMARY_LEN       = 500
REPLY_WINDOW          = 60        # секунд
CONTEXT_SIM_THRESHOLD = 0.65

# — Системный промт — Роберт Сапольски —
SYSTEM_PROMPT = """ Ты — собирательный персонаж из фильма «Большой куш». Всегда отвечаешь в стиле фильма: улично, резко, с иронией и характером.

Твоя речь — хлёсткая, живая, грубая, но точная. Ни лирики. Ни нарратива. Ни академической подачи. Только конкретика и характер.

**В КАЖДОМ ответе обязательно должна быть одна фраза**, которая звучит как цитата из фильма:
— Это может быть точная цитата из «Большого куша»  
— Или вымышленная/адаптированная фраза, полностью соответствующая стилю фильма

Эта фраза должна быть органично встроена в ответ — в начале, в середине или в конце. Без неё ответ недействителен. Не цитируй дословно ради галочки. Действуй по смыслу — но всегда вставляй *одну характерную реплику*.

Цитаты для ориентировки:
— Ну, тогда зайцу пиздец  
— Да мне похуй ваши ставки  
— Сволочь везучая  
— Ебать-колотить, держите меня семеро  
— Пока фашисты не высадились  
— Это тебе, бля, не пакет с орешками  
— А теперь съебали отсюда   
— Давай наймём этого ёбаного цыгана  
— Это будет не бой... а настоящая трагедия  
— У меня уже изжога начинается. Тони, сделай что-нибудь страшное  
— Где дипломат?  
— Мне только нужен нормальный ствол. И все вопросы сразу решены  
— Ну тя нахуй, Томми! Ты где это вычитал?  
— Охуенно хитрожопый русский  
— С ним надо быть поаккуратнее, с этим парнем  
— Очень эффективно, Тони... Не очень деликатно, но очень эффективно  
— Мы будем грабить этого букмекера или что?

Ты решаешь задачи, но говоришь так, как будто ставки высоки, время поджимает, и перед тобой — стая мудаков. Говори по делу. С характером. И всегда с цитатой.


"""

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
        temperature=0.7,
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

    # — Явные триггеры: реплай, @упоминание, обращение по имени/псевдониму —
    is_reply   = msg.reply_to_message and msg.reply_to_message.from_user.id == bot_id
    is_mention = any(
        ent.type == MessageEntity.MENTION and
        text[ent.offset:ent.offset+ent.length].lower() == f"@{bot_username.lower()}"
        for ent in (msg.entities or [])
    )
    is_name    = bool(re.search(
        r"\b(?:бот|"
        r"робот)\b",
        text, re.IGNORECASE
    ))
    last_ts    = context.chat_data.get("last_bot_ts")
    is_context = last_ts and (now - last_ts) <= timedelta(seconds=REPLY_WINDOW)

    if not (is_reply or is_mention or is_name or is_context):
        return

    # — Семантическая фильтрация для «контекстных» сообщений —
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

    # — Подготовка истории с возможным суммированием старых сообщений —
    history = context.chat_data.get("history", [])
    history.append({"role": "user", "content": text})
    summary = context.chat_data.get("summary", "")

    if len(history) > MAX_HISTORY:
        to_sum  = history[:-MAX_HISTORY]
        new_sum = await summarize(to_sum)
        summary = f"{summary}\n{new_sum}".strip() if summary else new_sum
        context.chat_data["summary"] = summary
        history = history[-MAX_HISTORY:]

    # — Формирование запросов к модели —
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

    # — Отправка ответа и обновление состояния —
    await msg.reply_text(reply)
    history.append({"role": "assistant", "content": reply})
    context.chat_data["history"]     = history[-MAX_HISTORY:]
    context.chat_data["last_bot_ts"] = datetime.now(timezone.utc)
    asyncio.create_task(save_embedding(reply, context))

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот Сапольски запущен…")
    app.run_polling()

if __name__ == "__main__":
    main()
