import asyncio
import re
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from openai import AsyncOpenAI

# --- НАСТРОЙКИ ---
TOKEN = "1780243415:JQQ_RUzI-Gmd08s4kgO6EXghwHfVqbOxLDw"
# Кастомный эндпоинт Shuzagram для aiogram
shuzagram_server = TelegramAPIServer.from_base("https://api.shuzagram.com/bot")
session = AiohttpSession(server=shuzagram_server)

# Настройки для LLM (можешь вставить свой ключ от OpenRouter, Groq или Gemini)
API_KEY = "ТВОЙ_API_КЛЮЧ_LLM"
BASE_URL = "https://openrouter.ai/api/v1"  
MODEL_NAME = "deepseek/deepseek-chat"      

# Инициализация бота с кастомным сервером
bot = Bot(token=TOKEN, session=session)
dp = Dispatcher()
ai_client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

# --- БАЗА ДАННЫХ (SQLite) ---
db = sqlite3.connect("rp_bot.db")
cursor = db.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    affection INTEGER DEFAULT 10,
    history TEXT DEFAULT ''
)
""")
db.commit()


def get_user(user_id: int):
    cursor.execute("SELECT affection, history FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, affection, history) VALUES (?, 10, '')", (user_id,))
        db.commit()
        return 10, ""
    return row[0], row[1]


def update_user(user_id: int, affection: int, history: str):
    affection = max(0, min(100, affection))  # Удерживаем шкалу в пределах от 0% до 100%
    cursor.execute("UPDATE users SET affection = ?, history = ? WHERE user_id = ?", (affection, history, user_id))
    db.commit()


# --- РАСЧЁТ РАНГА И ШКАЛЫ СЕРДЕЧЕК ---
def get_rank_and_bar(affection: int):
    if affection < 20:
        rank = "Незнакомка"
    elif affection < 45:
        rank = "Напарница"
    elif affection < 70:
        rank = "Близкая подруга"
    elif affection < 90:
        rank = "Особенный человек"
    else:
        rank = "Влюблена"

    filled = affection // 10
    bar = "🩷" * filled + "🖤" * (10 - filled)
    return rank, bar


def status_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💗 Близость и статус", callback_data="check_status")],
        [InlineKeyboardButton(text="🔄 Сбросить диалог", callback_data="reset_chat")]
    ])


# --- ГЕНЕРАЦИЯ ОТВЕТА ИИ ---
async def generate_rp_reply(user_id: int, user_text: str):
    affection, history = get_user(user_id)
    rank, _ = get_rank_and_bar(affection)

    system_prompt = f"""
Ты — Юки, харизматичная аниме-девушка в текстовой ролевой игре (RP).
Текущий уровень близости с пользователем: {affection}% (Статус: {rank}).

Правила общения:
1. Пиши от первого лица. Всегда описывай свои действия, жесты, мимику и окружение в звёздочках с новой строки (например: *Она поправила прядь волос и слегка улыбнулась*).
2. После описания действия с отступом пиши свою прямую речь.
3. Строго учитывай уровень близости ({affection}%):
   - 0-20%: ты осторожна, немного язвительна или держишь дистанцию.
   - 21-50%: ты общаешься как добрая напарница, иногда флиртуешь или дразнишь.
   - 51-100%: ты проявляешь сильную привязанность, заботу и нежность.
4. В самом конце своего сообщения ОБЯЗАТЕЛЬНО добавь оценку того, как слова пользователя повлияли на симпатию, строго в формате [DELTA:X], где X — число от -3 до +3 (например: [DELTA:+2] или [DELTA:-1]). Никак иначе этот тег не комментируй.
"""

    # Берём последние 10 реплик для контекста памяти
    lines = [line for line in history.split("\n") if line][-10:]
    messages = [{"role": "system", "content": system_prompt}]
    for line in lines:
        if line.startswith("U: "):
            messages.append({"role": "user", "content": line[3:]})
        elif line.startswith("A: "):
            messages.append({"role": "assistant", "content": line[3:]})
    messages.append({"role": "user", "content": user_text})

    response = await ai_client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.85,
        max_tokens=450
    )

    raw_reply = response.choices[0].message.content.strip()

    # Вытаскиваем изменение близости [DELTA:+2] из ответа нейросети
    delta = 0
    match = re.search(r"\[DELTA:([+-]?\d+)\]", raw_reply)
    if match:
        delta = int(match.group(1))
        raw_reply = re.sub(r"\[DELTA:[+-]?\d+\]", "", raw_reply).strip()

    new_affection = max(0, min(100, affection + delta))
    new_history = "\n".join(lines + [f"U: {user_text}", f"A: {raw_reply}"])
    update_user(user_id, new_affection, new_history)

    # Форматируем звёздочки в HTML-курсив для Telegram
    formatted_reply = re.sub(r"\*(.*?)\*", r"<i>*\1*</i>", raw_reply)
    return formatted_reply, delta, new_affection


# --- ОБРАБОТЧИКИ СООБЫТИЙ ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    get_user(message.from_user.id)
    intro = (
        "<i>*Она прислонилась к дверному косяку и с любопытством посмотрела на тебя, слегка наклонив голову*</i>\n\n"
        "Ну привет. Не ожидала, что ты заглянешь так скоро... О чём поболтаем?"
    )
    await message.answer(intro, parse_mode="HTML", reply_markup=status_keyboard())


@dp.message(Command("status"))
async def cmd_status(message: Message):
    affection, _ = get_user(message.from_user.id)
    rank, bar = get_rank_and_bar(affection)
    text = (
        f"💗 <b>Близость: {affection}%</b>\n"
        f"{bar}\n\n"
        f"💬 Статус: <b>{rank}</b>"
    )
    await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "check_status")
async def cb_status(callback: CallbackQuery):
    affection, _ = get_user(callback.from_user.id)
    rank, bar = get_rank_and_bar(affection)
    text = (
        f"💗 Близость: {affection}%\n"
        f"{bar}\n"
        f"💬 Статус: {rank}"
    )
    await callback.answer(text, show_alert=True)


@dp.callback_query(F.data == "reset_chat")
async def cb_reset(callback: CallbackQuery):
    update_user(callback.from_user.id, 10, "")
    await callback.message.answer("🔄 <i>Память очищена, близость сброшена до 10%.</i>", parse_mode="HTML")
    await callback.answer()


@dp.message(F.text)
async def handle_message(message: Message):
    # Показываем статус печати
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    reply, delta, new_affection = await generate_rp_reply(message.from_user.id, message.text)

    # Красиво добавляем информацию об изменении шкалы внизу сообщения
    if delta > 0:
        reply += f"\n\n<code>[💗 Близость +{delta}% → {new_affection}%]</code>"
    elif delta < 0:
        reply += f"\n\n<code>[💔 Близость {delta}% → {new_affection}%]</code>"

    await message.answer(reply, parse_mode="HTML", reply_markup=status_keyboard())


async def main():
    print("Бот запущен на сервере Shuzagram...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
