import asyncio
import pathlib
from collections import defaultdict
from aiogram.types import FSInputFile

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.client.bot import DefaultBotProperties
from g4f.client import Client

TOKEN = "7805689486:AAGg-Ru0p653_9qd_mHyq7Ku0iR7FFwqAME"
GROUP_ID = -1002658300534  # Замените на реальный ID группы

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
client = Client()

users = {}  # user_id -> данные пациента и шаги
patients = {}  # id_code -> user_id
history = defaultdict(list)  # user_id -> список сообщений (текст или file_id)

back_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад")]],
    resize_keyboard=True
)


async def gpt_recommend_specialist(symptoms: str) -> str:
    prompt = (
        f"Пользователь описал жалобы: '{symptoms}'. "
        "Пожалуйста, дай развернутый ответ, размышления о том, какие врачи могут быть нужны. "
        "Например: 'Ваши симптомы могут указывать на... Вам скорее всего нужно посетить...'. "
        "Объясни, почему и какие варианты могут быть, чтобы пациент понимал логику."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            web_search=False
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Ваши симптомы требуют консультации терапевта для дальнейшего уточнения."


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    uid = message.from_user.id
    if uid in users:
        users.pop(uid)
    await cmd_start(message)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Начать")],
        ],
        resize_keyboard=True
    )

    BASE_DIR = pathlib.Path(__file__).parent
    photo_path = FSInputFile(BASE_DIR / "smartmed.png")

    text = (
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Этот бот поможет вам получить профессиональное направление к нужному врачу, "
        "основываясь на ваших симптомах и персональных данных.\n\n"
        "🔹 Для начала нажмите кнопку <b>Начать</b> или введите команду /get.\n\n"
        "<b>Важно:</b> нажимая кнопку <b>Начать</b>, вы даёте согласие на обработку "
        "ваших персональных данных в соответствии с законодательством.\n\n"
        "Для возврата в главное меню в любой момент используйте кнопку <b>🏠 Главное меню</b> "
        "или введите команду /start.\n\n"
        "Спасибо за доверие! ❤️"
    )

    await bot.send_photo(
        chat_id=message.chat.id,
        photo=photo_path,
        caption=text,
        parse_mode=ParseMode.HTML,  # Используем HTML, т.к. в тексте <b>теги</b>
        reply_markup=keyboard
    )


@dp.message(Command("get"))
@dp.message(lambda message: message.text == "Начать")
async def cmd_get(message: types.Message):
    if message.chat.type != "private":
        await message.answer("⚠️ Пожалуйста, напишите мне в личные сообщения для начала работы.")
        return
    users[message.from_user.id] = {
        "step": "fio",
        "id": message.from_user.id,
        "first_name": message.from_user.first_name or ""
    }
    await message.answer(
        "📝 <b>Введите ваше ФИО:</b>",
        reply_markup=back_keyboard
    )


@dp.message()
async def process_steps(message: types.Message):
    # Разрешаем обработку только в личке или в нашей группе
    if message.chat.type != "private" and message.chat.id != GROUP_ID:
        return

    # Обработка команды /send в группе
    if message.text and message.text.startswith("/send"):
        await handle_send(message)
        return

    # Далее остальная логика для личных сообщений
    if message.chat.type != "private":
        return

    uid = message.from_user.id
    text = message.text.strip()

    # ✅ Обработка "🏠 Главное меню" на любом этапе
    if text == "🏠 Главное меню":
        users.pop(uid, None)
        await cmd_start(message)
        return

    if uid not in users:
        await message.answer("Для начала нажмите кнопку <b>Начать</b> или введите команду /get.")
        return

    # Обработка кнопки "🔙 Назад"
    if text == "🔙 Назад":
        current_step = users[uid].get("step")
        step_order = ["fio", "age", "phone", "symptoms"]
        if current_step in step_order:
            idx = step_order.index(current_step)
            if idx > 0:
                prev_step = step_order[idx - 1]
                users[uid]["step"] = prev_step
                prompts = {
                    "fio": "📝 <b>Введите ваше ФИО:</b>",
                    "age": "🎂 <b>Введите ваш возраст (числом):</b>",
                    "phone": "📞 <b>Введите номер телефона:</b>",
                    "symptoms": "🩺 <b>Опишите ваши жалобы (в свободной форме):</b>"
                }
                await message.answer(prompts[prev_step], reply_markup=back_keyboard)
            else:
                await message.answer("Вы уже на первом шаге.", reply_markup=back_keyboard)
        return

    step = users[uid].get("step")

    if step == "fio":
        users[uid]["fio"] = text
        users[uid]["step"] = "age"
        await message.answer("🎂 <b>Введите ваш возраст (числом):</b>", reply_markup=back_keyboard)
    elif step == "age":
        if not text.isdigit() or not (0 < int(text) < 120):
            await message.answer("⚠️ Пожалуйста, введите корректный возраст числом от 1 до 119.", reply_markup=back_keyboard)
            return
        users[uid]["age"] = text
        users[uid]["step"] = "phone"
        await message.answer("📞 <b>Введите номер телефона:</b>", reply_markup=back_keyboard)
    elif step == "phone":
        if len(text) < 5 or not any(c.isdigit() for c in text):
            await message.answer("⚠️ Пожалуйста, введите корректный номер телефона.", reply_markup=back_keyboard)
            return
        users[uid]["phone"] = text
        users[uid]["step"] = "symptoms"
        await message.answer("🩺 <b>Опишите ваши жалобы (максимально подробно):</b>", reply_markup=back_keyboard)
    elif step == "symptoms":
        users[uid]["symptoms"] = text
        await message.answer("⏳ Ищу для вас подходящего специалиста, подождите...", reply_markup=ReplyKeyboardRemove())

        spec = await gpt_recommend_specialist(text)
        users[uid]["spec"] = spec
        users[uid]["username"] = message.from_user.username or ""

        code = str(uid)
        users[uid]["id_code"] = code
        patients[code] = uid

        users[uid]["step"] = "confirm"

        await message.answer(
            f"🧠 <b>Рекомендация от нейросети:</b>\n{spec}\n\n"
            f"📌 Ваш код пациента (Telegram ID): <b>{code}</b>\n\n"
            f"Если всё верно, нажмите кнопку <b>Отправить врачу</b>, чтобы направить данные специалисту.\n"
            f"Или воспользуйтесь кнопкой <b>🏠 Главное меню</b> для возврата.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="Отправить врачу")],
                    [KeyboardButton(text="🏠 Главное меню")]
                ],
                resize_keyboard=True,
            )
        )
    elif step == "confirm":
        if text == "Отправить врачу":
            data = users[uid]
            text_msg = (
                f"⚠️ <b>Новый пациент:</b>\n"
                f"🆔 Код (Telegram ID): <b>{data['id_code']}</b>\n"
                f"👤 {data['fio']} ({data['age']} лет)\n"
                f"📞 {data['phone']}\n"
                f"💬 Жалобы: {data['symptoms']}\n"
                f"🧠 Рекомендация нейросети: {data['spec']}\n"
            )

            if data.get('username'):
                text_msg += f"📎 Telegram: <a href='https://t.me/{data['username']}'>{data['first_name']}</a>"
            else:
                text_msg += f"📎 Telegram: <a href='tg://user?id={data['id']}'>{data['first_name']}</a>"

            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Ответить пациенту", callback_data=f"reply_{data['id_code']}")]
                ]
            )
            await bot.send_message(chat_id=GROUP_ID, text=text_msg, reply_markup=reply_markup)
            await message.answer(
                f"✅ Ваш запрос успешно отправлен врачу.\n"
                f"📌 Ваш код для связи: <b>{data['id_code']}</b>\n\n"
                f"Вы можете вернуться в главное меню в любой момент, нажав кнопку <b>🏠 Главное меню</b>.",
                reply_markup=ReplyKeyboardRemove()
            )
            users[uid]["step"] = "waiting_direction"
        else:
            await message.answer(
                "Пожалуйста, нажмите кнопку <b>Отправить врачу</b> или воспользуйтесь <b>🏠 Главное меню</b>.",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="Отправить врачу")],
                        [KeyboardButton(text="🏠 Главное меню")]
                    ],
                    resize_keyboard=True,
                )
            )
    else:
        await message.answer("Для начала нажмите кнопку <b>Начать</b> или введите команду /get.")


@dp.message(Command("history"))
async def send_history(message: types.Message):
    if message.chat.type != "private":
        await message.answer("⚠️ Эта команда доступна только в личных сообщениях.")
        return

    uid = message.from_user.id
    docs = history.get(uid, [])

    if not docs:
        await message.answer("📭 У вас пока нет направлений.")
        return

    await message.answer(f"📚 Ваши направления ({len(docs)}):")
    for item in docs:
        if item['type'] == 'text':
            await message.answer(f"📄 Текст: {item['content']}")
        elif item['type'] == 'photo':
            await message.answer_photo(item['file_id'], caption=item.get('caption', ''))
        elif item['type'] == 'document':
            await message.answer_document(item['file_id'], caption=item.get('caption', ''))


@dp.message(Command("send"))
async def handle_send(message: types.Message):
    # Разрешаем команду только в группе
    if message.chat.id != GROUP_ID:
        return

    # Обработка текстового сообщения
    if message.text and message.text.startswith("/send"):
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.reply("⚠️ Использование: /send <код пациента> <сообщение>")
            return

        code, msg = args[1], args[2]
        if code not in patients:
            await message.reply("❌ Пациент с таким кодом не найден.")
            return

        uid = patients[code]
        try:
            await bot.send_message(uid, f"📩 Сообщение от врача:\n{msg}")
            history[uid].append({'type': 'text', 'content': msg})
            await message.reply("✅ Сообщение отправлено.")
        except Exception as e:
            await message.reply(f"❌ Ошибка при отправке: {e}")

    # Обработка медиафайлов с подписью /send
    elif message.caption and message.caption.startswith("/send"):
        args = message.caption.split(maxsplit=2)
        if len(args) < 3:
            await message.reply("⚠️ Использование: /send <код пациента> <описание>")
            return

        code, description = args[1], args[2]
        if code not in patients:
            await message.reply("❌ Пациент с таким кодом не найден.")
            return

        uid = patients[code]
        try:
            if message.photo:
                file_id = message.photo[-1].file_id
                await bot.send_photo(uid, file_id, caption=f"📷 От врача:\n{description}")
                history[uid].append({'type': 'photo', 'file_id': file_id, 'caption': description})
            elif message.document:
                file_id = message.document.file_id
                await bot.send_document(uid, file_id, caption=f"📄 От врача:\n{description}")
                history[uid].append({'type': 'document', 'file_id': file_id, 'caption': description})

            await message.reply("✅ Медиафайл отправлен пациенту.")
        except Exception as e:
            await message.reply(f"❌ Ошибка при отправке: {e}")


@dp.callback_query(lambda c: c.data and c.data.startswith("reply_"))
async def handle_reply_callback(callback: CallbackQuery):
    code = callback.data.split("_", maxsplit=1)[1]
    if code not in patients:
        await callback.answer("Пациент не найден.", show_alert=True)
        return

    await callback.message.answer(
        f"✍️ Напишите сообщение пациенту:\n"
        f"1. Текст: `/send {code} ваш текст`\n"
        f"2. Медиафайлы отправлять в личное сообщение",
        parse_mode="Markdown"
    )
    await callback.answer()


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())