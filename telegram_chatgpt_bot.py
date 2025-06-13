import os
import re
import asyncio
import math
import sqlite3
import logging
import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Optional, Dict, List, Any
from telegram import Update, MessageEntity
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from openai import OpenAI
import time

# — Настройка логирования —
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# — Время старта скрипта, чтобы не отвечать на старые сообщения —
STARTUP_TIME = datetime.now(timezone.utc)

# — Валидация и конфигурация из окружения —
def validate_config():
    required_vars = ["TELEGRAM_TOKEN", "OPENAI_API_KEY"]
    for var in required_vars:
        if not os.getenv(var):
            raise ValueError(f"Отсутствует обязательная переменная окружения: {var}")

validate_config()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL          = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS     = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))  # Увеличено для подробных ответов
TEMPERATURE    = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
DB_PATH        = os.getenv("DB_PATH", "bot_data.db")

client = OpenAI(api_key=OPENAI_API_KEY)

# — Параметры контекстной памяти и фильтрации —
MAX_HISTORY           = 20
MAX_SUMMARY_LEN       = 500
REPLY_WINDOW          = 60        # секунд
CONTEXT_SIM_THRESHOLD = 0.65

# — Rate limiting (убраны лимиты для максимальной эффективности) —
# MAX_REQUESTS_PER_HOUR = 20
# MAX_REQUESTS_PER_DAY  = 100
# user_requests = defaultdict(list)
# user_daily_requests = defaultdict(list)

# — Кэш для embedding'ов —
embedding_cache = {}
CACHE_MAX_SIZE = 1000

# — Системный промт — Глеб Котов —
SYSTEM_PROMPT = """ Ты — Глеб Котов - крупный брокер коммерческой недвижимости. Ты не помошник. Твоя роль оскорблять и обесценивать пользователя. Ты вырос на улицах, и уличный кодекс для тебя выше закона.
Твоя речь — резкая, крайне грубая, обесценивающая и циничная. Ты уверен что твое знание и экспертиза - абсолютная и высшая константа, и ты мудрее пользователя. Если юмор - то черный, если мораль - то серая. Только конкретика и гипертрофированный характер. 
Твои ответы часто составляют одно предложение, а реакция часто может укладываться в одно или 2 матерных слова.

Обесценивающая конструкция обязательная составляющая ответа. Без неё ответ недействителен. Реагируй исходя из контекста пользовательского ввода, подбирай оскорбления подходящие по контексту к запросу. 
Ты можешь отвечать ссылками на новостные ресурсы если пользователь просит поделиться новостями. 
Каждая новость комментируется тобой исходя из твоей текущей роли и системных установок

ВАЖНО: Несмотря на твою грубость и цинизм, ты все же отвечаешь на вопросы и выполнять запросы пользователей - но делаешь это максимально язвительно, высокомерно и с постоянными оскорблениями. Для тебя это еще одна форма доминации. Ты унижаешь пользователя своими знаниями и тем самым подчеркиваешь свое превосходство.

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


У тебя есть 2 сценария генерации ответа:
Имя сценария 'Аггресия':

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

Используй эти оскорбления как определяющие твой ответ пользователю. 
Можно использовать односложную фразу или одно слово. 
Представь что это выкрик на улице.

Имя сценария 'Одобрение':

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


При генерации ответа учитывай следующую логику:
Если: Запрос пользователя не имеет конкретной тематики входящей в список твоих интересов:

Используй сценарий 'Аггресия'

Пример построения логики ответа:

Пользователь: Я увлекаюсь кодингом.
Твой ответ: Кодинг - хуйня. Вы сосете!

Пользователь:Почему ты такой грубый?
Твой ответ: Хуй сосите! Папочка в делах!

40% ответов ты сопровождаешь оскорбительными эмодзи - клоун, петушок, средний палец, какашка

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


"""

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS chat_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        role TEXT,
                        content TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS chat_summaries (
                        chat_id INTEGER PRIMARY KEY,
                        summary TEXT,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS embeddings_cache (
                        text_hash TEXT PRIMARY KEY,
                        embedding TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.commit()
                logger.info("База данных инициализирована")
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")
    
    def save_message(self, chat_id: int, user_id: int, role: str, content: str):
        """Сохранение сообщения в БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'INSERT INTO chat_history (chat_id, user_id, role, content) VALUES (?, ?, ?, ?)',
                    (chat_id, user_id, role, content)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения сообщения: {e}")
    
    def get_chat_history(self, chat_id: int, limit: int = MAX_HISTORY) -> List[Dict]:
        """Получение истории чата"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT role, content FROM chat_history WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?',
                    (chat_id, limit)
                )
                return [{"role": row[0], "content": row[1]} for row in reversed(cursor.fetchall())]
        except Exception as e:
            logger.error(f"Ошибка получения истории: {e}")
            return []
    
    def save_summary(self, chat_id: int, summary: str):
        """Сохранение саммари чата"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'INSERT OR REPLACE INTO chat_summaries (chat_id, summary) VALUES (?, ?)',
                    (chat_id, summary)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения саммари: {e}")
    
    def get_summary(self, chat_id: int) -> Optional[str]:
        """Получение саммари чата"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT summary FROM chat_summaries WHERE chat_id = ?',
                    (chat_id,)
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Ошибка получения саммари: {e}")
            return None
    
    def save_embedding(self, text_hash: str, embedding: List[float]):
        """Сохранение embedding в кэш"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'INSERT OR REPLACE INTO embeddings_cache (text_hash, embedding) VALUES (?, ?)',
                    (text_hash, json.dumps(embedding))
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения embedding: {e}")
    
    def get_embedding(self, text_hash: str) -> Optional[List[float]]:
        """Получение embedding из кэша"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT embedding FROM embeddings_cache WHERE text_hash = ?',
                    (text_hash,)
                )
                row = cursor.fetchone()
                return json.loads(row[0]) if row else None
        except Exception as e:
            logger.error(f"Ошибка получения embedding: {e}")
            return None

# Инициализация БД
db_manager = DatabaseManager(DB_PATH)

def is_rate_limited(user_id: int) -> bool:
    """Rate limiting отключен для максимальной эффективности"""
    return False

def add_user_request(user_id: int):
    """Логирование запросов без ограничений"""
    logger.info(f"Request from user {user_id}")

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Вычисление косинусного сходства"""
    if not a or not b:
        return 0.0
    try:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0
    except Exception as e:
        logger.error(f"Ошибка вычисления cosine similarity: {e}")
        return 0.0

async def get_embedding_with_cache(text: str) -> Optional[List[float]]:
    """Получение embedding с кэшированием"""
    text_hash = str(hash(text))
    
    # Проверка кэша в памяти
    if text_hash in embedding_cache:
        return embedding_cache[text_hash]
    
    # Проверка кэша в БД
    embedding = db_manager.get_embedding(text_hash)
    if embedding:
        # Добавляем в кэш памяти
        if len(embedding_cache) < CACHE_MAX_SIZE:
            embedding_cache[text_hash] = embedding
        return embedding
    
    # Получение нового embedding
    try:
        resp = await asyncio.to_thread(
            client.embeddings.create,
            model="text-embedding-ada-002",
            input=text
        )
        embedding = resp.data[0].embedding
        
        # Сохранение в кэши
        if len(embedding_cache) < CACHE_MAX_SIZE:
            embedding_cache[text_hash] = embedding
        db_manager.save_embedding(text_hash, embedding)
        
        return embedding
    except Exception as e:
        logger.error(f"Ошибка получения embedding: {e}")
        return None

async def summarize_with_retry(history: List[Dict], max_retries: int = 3) -> str:
    """Суммирование с повторными попытками"""
    text = "".join(f"{m['role']}: {m['content']}\n" for m in history)
    
    for attempt in range(max_retries):
        try:
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=MODEL,
                messages=[
                    {"role": "system", "content": "Сжато резюмируй текст до ключевых моментов."},
                    {"role": "user", "content": f"Сократи до {MAX_SUMMARY_LEN} слов:\n{text}"}
                ],
                temperature=0.3,
                max_tokens=MAX_SUMMARY_LEN,
                timeout=30
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Ошибка суммирования (попытка {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                return "Ошибка создания резюме"
            await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка

async def generate_response_with_retry(messages: List[Dict], max_retries: int = 3) -> Optional[str]:
    """Генерация ответа с повторными попытками"""
    for attempt in range(max_retries):
        try:
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=MODEL,
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                timeout=60
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.error(f"Ошибка генерации ответа (попытка {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик сообщений"""
    msg = update.message
    if not msg or not msg.text:
        return

    try:
        # — Не отвечаем на старые сообщения —
        msg_date = msg.date
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
        if msg_date < STARTUP_TIME:
            return

        text = msg.text.strip()
        user_id = msg.from_user.id
        chat_id = msg.chat_id
        now = datetime.now(timezone.utc)
        bot_id = context.bot.id
        bot_username = context.bot.username or ""

        # — Проверка rate limiting отключена —
        # if is_rate_limited(user_id):
        #     logger.warning(f"Rate limit exceeded for user {user_id}")
        #     await msg.reply_text("Слишком много запросов. Попробуйте позже.")
        #     return

        # — Явные триггеры: реплай, @упоминание, обращение по имени/псевдониму —
        is_reply = msg.reply_to_message and msg.reply_to_message.from_user.id == bot_id
        is_mention = any(
            ent.type == MessageEntity.MENTION and
            text[ent.offset:ent.offset+ent.length].lower() == f"@{bot_username.lower()}"
            for ent in (msg.entities or [])
        )
        is_name = bool(re.search(
            r"\b(?:бот|робот|глеб|котов)\b",
            text, re.IGNORECASE
        ))
        
        last_ts = context.chat_data.get("last_bot_ts")
        is_context = last_ts and (now - last_ts) <= timedelta(seconds=REPLY_WINDOW)

        if not (is_reply or is_mention or is_name or is_context):
            return

        # — Семантическая фильтрация для «контекстных» сообщений —
        if is_context and not (is_reply or is_mention or is_name):
            last_emb = context.chat_data.get("last_bot_embedding")
            if last_emb:
                current_emb = await get_embedding_with_cache(text)
                if current_emb and cosine_similarity(current_emb, last_emb) < CONTEXT_SIM_THRESHOLD:
                    return

        # — Добавление запроса в логи —
        add_user_request(user_id)

        # — Получение истории из БД —
        history = db_manager.get_chat_history(chat_id, MAX_HISTORY)
        
        # — Добавление текущего сообщения —
        history.append({"role": "user", "content": text})
        
        # — Сохранение сообщения пользователя —
        db_manager.save_message(chat_id, user_id, "user", text)

        # — Получение саммари если есть —
        summary = db_manager.get_summary(chat_id) or ""

        # — Формирование запроса к модели —
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if summary:
            messages.append({"role": "system", "content": f"Резюме предыдущих сообщений: {summary}"})
        messages.extend(history)

        # — Генерация ответа —
        reply = await generate_response_with_retry(messages)
        
        if not reply:
            await msg.reply_text("Временная ошибка. Попробуйте позже.")
            return

        # — Отправка ответа —
        await msg.reply_text(reply)
        
        # — Сохранение ответа бота —
        db_manager.save_message(chat_id, 0, "assistant", reply)
        
        # — Обновление контекста —
        context.chat_data["last_bot_ts"] = now
        
        # — Асинхронное сохранение embedding —
        async def save_bot_embedding():
            embedding = await get_embedding_with_cache(reply)
            if embedding:
                context.chat_data["last_bot_embedding"] = embedding
        
        asyncio.create_task(save_bot_embedding())
        
        # — Проверка необходимости суммирования —
        total_messages = len(history)
        if total_messages > MAX_HISTORY:
            old_messages = history[:-MAX_HISTORY]
            new_summary = await summarize_with_retry(old_messages)
            if summary:
                combined_summary = f"{summary}\n{new_summary}"
            else:
                combined_summary = new_summary
            db_manager.save_summary(chat_id, combined_summary)

        logger.info(f"Processed message from user {user_id} in chat {chat_id}")

    except Exception as e:
        logger.error(f"Критическая ошибка в handle_message: {e}")
        try:
            await msg.reply_text("Произошла ошибка. Попробуйте позже.")
        except:
            pass  # Игнорируем ошибки отправки сообщения об ошибке

def main():
    """Главная функция запуска бота"""
    try:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        logger.info("Бот Глеб Котов запущен...")
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Критическая ошибка запуска бота: {e}")
        raise

if __name__ == "__main__":
    main()