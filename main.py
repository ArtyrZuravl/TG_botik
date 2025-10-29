import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

TOKEN = "7636666169:AAGv_yAKdQOGh5ZQzRBJDgVTYE4T5u0dN1U"
ADMIN_ID = 1048803501

bot = Bot(token=TOKEN)
dp = Dispatcher()
DB_NAME = "orders.db"

# Контексты
admin_context = {}          # admin_id -> order_id (для ответа)
user_context = {}           # user_id -> True/False (находится ли в процессе нового заказа)

# ====== ИНИЦИАЛИЗАЦИЯ БД ======
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                text TEXT,
                media_id TEXT,
                media_type TEXT,
                status TEXT
            )
        """)
        await db.commit()

# ====== СТАРТ ======
@dp.message(Command("start"))
async def start(message: Message):
    user_context[message.from_user.id] = False
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Сделать заказ", callback_data="new_order")],
        [InlineKeyboardButton(text="🟢 Активные заказы", callback_data="active_orders")],
        [InlineKeyboardButton(text="📜 История заказов", callback_data="history_orders")]
    ])
    await message.answer("👋 Привет! Выбери действие:", reply_markup=keyboard)

# ====== НОВЫЙ ЗАКАЗ ======
@dp.callback_query(F.data == "new_order")
async def new_order_start(callback: CallbackQuery):
    user_context[callback.from_user.id] = True
    await callback.message.answer("✏️ Отправь задание (текст + медиа, если нужно).")
    await callback.answer()

# ====== ОБРАБОТКА СООБЩЕНИЙ ======
@dp.message(F.text | F.photo | F.document | F.video | F.audio | F.voice)
async def handle_message(message: Message):
    user_id = message.from_user.id

    # 1️⃣ Админ в режиме ответа
    if user_id == ADMIN_ID and admin_context.get(ADMIN_ID):
        order_id = admin_context[ADMIN_ID]

        # Получаем id пользователя
        async with aiosqlite.connect(DB_NAME) as db:
            cur = await db.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
            res = await cur.fetchone()
        if not res:
            await message.answer("⚠️ Заказ не найден.")
            admin_context[ADMIN_ID] = None
            return
        target_user_id = res[0]

        # Определяем тип медиа
        media_id, media_type = None, None
        if message.photo:
            media_id = message.photo[-1].file_id
            media_type = "photo"
        elif message.document:
            media_id = message.document.file_id
            media_type = "document"
        elif message.video:
            media_id = message.video.file_id
            media_type = "video"
        elif message.audio:
            media_id = message.audio.file_id
            media_type = "audio"
        elif message.voice:
            media_id = message.voice.file_id
            media_type = "voice"

        # Отправляем админский ответ
        if media_id:
            send_media = {
                "photo": bot.send_photo,
                "document": bot.send_document,
                "video": bot.send_video,
                "audio": bot.send_audio,
                "voice": bot.send_voice,
            }[media_type]
            await send_media(target_user_id, media_id, caption=message.caption or "", reply_markup=None)
        if message.text:
            await bot.send_message(target_user_id, f"💬 Ответ менеджера на заказ №{order_id}:\n{message.text}")

        await message.answer(f"✅ Ответ отправлен пользователю для заказа №{order_id}")

        # Обновляем статус
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE orders SET status='Ответ дан' WHERE id=?", (order_id,))
            await db.commit()

        admin_context[ADMIN_ID] = None
        return

    # 2️⃣ Пользователь в процессе создания заказа
    if not user_context.get(user_id):
        return  # Игнорируем сообщения от обычного пользователя, если он не нажал "Сделать заказ"

    text = message.caption or message.text or "(без текста)"
    media_id, media_type = None, None

    if message.photo:
        media_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.document:
        media_id = message.document.file_id
        media_type = "document"
    elif message.video:
        media_id = message.video.file_id
        media_type = "video"
    elif message.audio:
        media_id = message.audio.file_id
        media_type = "audio"
    elif message.voice:
        media_id = message.voice.file_id
        media_type = "voice"

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO orders (user_id, username, text, media_id, media_type, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, message.from_user.username, text, media_id, media_type, "Активный"))
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid()")
        order_id = (await cur.fetchone())[0]

    await message.answer(f"✅ Заказ №{order_id} принят! Ожидай ответа менеджера.")
    user_context[user_id] = False  # Сброс контекста

    # Отправка админу
    admin_text = f"📩 *Новый заказ №{order_id}*\n👤 @{message.from_user.username}\n💬 {text}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Закрыть заказ", callback_data=f"admin_close_{order_id}")],
        [InlineKeyboardButton(text="💬 Ответить пользователю", callback_data=f"admin_reply_{order_id}")]
    ])
    if media_id:
        send_media = {
            "photo": bot.send_photo,
            "document": bot.send_document,
            "video": bot.send_video,
            "audio": bot.send_audio,
            "voice": bot.send_voice,
        }[media_type]
        await send_media(ADMIN_ID, media_id, caption=admin_text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown", reply_markup=keyboard)


# ====== КНОПКИ АКТИВНЫХ ЗАКАЗОВ ======
@dp.callback_query(F.data == "active_orders")
async def show_active(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, text FROM orders WHERE user_id=? AND status='Активный'", (callback.from_user.id,)) as cursor:
            orders = await cursor.fetchall()

    if not orders:
        await callback.message.answer("😌 У тебя нет активных заказов.")
        await callback.answer()
        return

    for o in orders:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel_{o[0]}")]
        ])
        await callback.message.answer(f"🟢 Заказ №{o[0]} — {o[1][:50]}...", reply_markup=keyboard)
    await callback.answer()


# ====== ОТМЕНА ЗАКАЗА ======
@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE orders SET status='Отменён' WHERE id=?", (order_id,))
        await db.commit()
    await callback.message.edit_text(f"❌ Заказ №{order_id} отменён.")
    await callback.answer("Заказ отменён.")


# ====== ИСТОРИЯ ЗАКАЗОВ ======
@dp.callback_query(F.data == "history_orders")
async def show_history(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, text, status FROM orders WHERE user_id=?", (callback.from_user.id,)) as cursor:
            orders = await cursor.fetchall()

    if not orders:
        await callback.message.answer("📭 История пуста.")
        await callback.answer()
        return

    msg = "📜 *История заказов:*\n\n"
    for o in orders:
        msg += f"• №{o[0]} — {o[1][:40]}... ({o[2]})\n"
    await callback.message.answer(msg, parse_mode="Markdown")
    await callback.answer()


# ====== АДМИН: ЗАКРЫТЬ ЗАКАЗ ======
@dp.callback_query(F.data.startswith("admin_close_"))
async def admin_close(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("⛔ Нет прав", show_alert=True)

    order_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE orders SET status='Закрыт' WHERE id=?", (order_id,))
        await db.commit()

        cur = await db.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
        user_id = (await cur.fetchone())[0]
        await bot.send_message(user_id, f"✅ Твой заказ №{order_id} закрыт менеджером.")

    await callback.message.edit_text(f"✅ Заказ №{order_id} закрыт.")
    await callback.answer("Заказ закрыт.")


# ====== АДМИН: ОТВЕТИТЬ ПОЛЬЗОВАТЕЛЮ ======
@dp.callback_query(F.data.startswith("admin_reply_"))
async def admin_reply(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("⛔ Нет прав", show_alert=True)

    order_id = int(callback.data.split("_")[2])
    admin_context[ADMIN_ID] = order_id
    await callback.message.answer(f"✏️ Введи текст или медиа для ответа на заказ №{order_id}:")
    await callback.answer()


# ====== ЗАПУСК ======
async def main():
    await init_db()
    print("🤖 Бот запущен и готов к работе!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
