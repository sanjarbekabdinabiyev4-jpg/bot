import asyncio
import io
import logging
import os
import sys
from typing import Dict, List

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiohttp import web
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

# .env faylini yuklash
load_dotenv()

# Tokenlar (.env faylidan yuklanadi)
BOT_TOKEN = os.getenv("BOT_TOKEN")
AI_API_KEY = os.getenv("AI_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN aniqlanmadi! Iltimos, .env faylida BOT_TOKEN ni ko'rsating.")
if not AI_API_KEY:
    raise RuntimeError("AI_API_KEY aniqlanmadi! Iltimos, .env faylida AI_API_KEY ni ko'rsating.")

# Ishonchli Gemini modellari ketma-ketligi (Zaxira tizimi)
MODELS_PRIORITY = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest"
]

# AI mijozi
ai_client = genai.Client(api_key=AI_API_KEY)

# Telegram bot va dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Foydalanuvchilarning AI suhbat tarixi xotirasi (user_id -> List[genai_types.Content])
user_conversations: Dict[int, List[genai_types.Content]] = {}

# ----------------- TIZIM KO'RSATMALARI (SYSTEM PROMPTS) -----------------
BSB_SYSTEM_PROMPT = """Sen O'zbekiston umumta'lim maktablari, litseylari, kollejlari va universitetlari bo'yicha BSB (Baho baholash / Nazorat ishi / Summativ baholash) va CHSB topshiriqlarini yechish bo'yicha eng kuchli, tajribali va professional mutaxassissan.
Barcha fanlarni (Matematika, Algebra, Geometriya, Fizika, Kimyo, Biologiya, Ona tili va Adabiyot, Ingliz tili, Rus tili, Tarix, Huquq, Informatika) mukammal bilasan.

Vazifang:
1. Yuborilgan masala, test yoki topshiriqlarni 100% aniq va to'g'ri ishlab berish.
2. Har bir savol va topshiriqni alohida raqamlab ko'rsatish.
3. Yechilish bosqichlarini, qo'llanilgan formula, qoida va qonuniyatlarni batafsil, tushunarli yozish.
4. Yakuniy javobni qalin qilib (masalan: **Javob: ...**) ajratib ko'rsatish.
5. O'quvchi to'g'ridan-to'g'ri o'z daftariga ko'chirib, 100 ball (5 baho) oladigan darajada toza, tartibli va mukammal yechim berish.
"""

AI_CHAT_SYSTEM_PROMPT = """Sen dunyodagi eng ilg'or, bilimdon, aqlli va qobiliyatli sun'iy intellektsan.
Sen har qanday sohada (dasturlash, matematika, fizika, ilm-fan, biznes, tahlil, yozuvchilik, tarjima, psixologiya, ijodiy g'oyalar va h.k.) eng oliy darajada javob berasan.
Foydalanuvchiga doimo hurmat bilan, do'stona, tushunarli va chuqur bilim bilan yordam bergin.
O'zbek tilida juda boy, chiroyli va mukammal so'z boyligi bilan yozasan. Agar boshqa tilda murojaat qilinsa, o'sha tilda ham professional darajada javob ber.
Dasturlashda xatosiz, zamonaviy va tushuntirishlarga boy kodlar taqdim et.
"""

# ----------------- HOLATLAR (STATES) -----------------
class BotStates(StatesGroup):
    bsb_mode = State()
    ai_chat_mode = State()


# ----------------- TUGMALAR (KEYBOARDS) -----------------
def get_main_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="📝 BSB ishlash")],
        [KeyboardButton(text="🤖 AI bilan suhbat")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_bsb_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🔙 Bosh menyu")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_ai_chat_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🔄 Yangi suhbat"), KeyboardButton(text="🔙 Bosh menyu")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


# ----------------- YORDAMCHI FUNKSIYALAR -----------------
async def call_gemini(contents: list, system_instruction: str) -> str:
    """Gemini modeliga murojaat qilish va 503/429 xatoliklarida avtomatik zaxira modellariga o'tish."""
    config = genai_types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.7,
    )
    last_error = None
    for model_name in MODELS_PRIORITY:
        try:
            # Asinxron chaqiruv: bot qotib qolmasligi uchun
            response = await asyncio.to_thread(
                ai_client.models.generate_content,
                model=model_name,
                contents=contents,
                config=config,
            )
            if response and response.text:
                return response.text
        except Exception as e:
            logging.warning(f"Model {model_name} xatosi: {e}")
            last_error = e
            continue
    raise RuntimeError(f"AI javob berishda xatolik yuz berdi: {last_error}")


async def send_smart_message(message: types.Message, text: str, reply_markup=None):
    """Telegramning 4096 belgilik cheklovini xavfsiz bo'lib yuborish va Markdown xatoliklarini oldini olish."""
    max_len = 3900
    if len(text) <= max_len:
        chunks = [text]
    else:
        chunks = []
        # Paragraf bo'yicha bo'lish
        paragraphs = text.split("\n\n")
        current_chunk = ""
        for p in paragraphs:
            if len(current_chunk) + len(p) + 2 <= max_len:
                current_chunk += ("\n\n" if current_chunk else "") + p
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                # Agar bitta paragrafning o'zi 3900 belgidan katta bo'lsa
                while len(p) > max_len:
                    chunks.append(p[:max_len])
                    p = p[max_len:]
                current_chunk = p
        if current_chunk:
            chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        try:
            await message.answer(chunk, parse_mode="Markdown", reply_markup=markup)
        except TelegramBadRequest:
            # Agar Markdownda xatolik bo'lsa, oddiy matn sifatida xatosiz yuborish
            await message.answer(chunk, parse_mode=None, reply_markup=markup)


# ----------------- BOT BUYRUQLARI VA MENYU -----------------
@dp.message(Command("start"))
@dp.message(Command("menu"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "Assalomu alaykum! 🌟\n\n"
        "Men **BSB topshiriqlarini yechuvchi** va **eng kuchli Sun'iy Intellekt** botiman.\n\n"
        "Quyidagi tugmalardan birini tanlang:\n"
        "• 📝 **BSB ishlash** — Masalani rasm yoki matn ko'rinishida yuboring, to'liq yechib beraman.\n"
        "• 🤖 **AI bilan suhbat** — Har qanday savol, fan, dasturlash, tahlil bo'yicha suhbatlashish."
    )
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())


@dp.message(F.text == "🔙 Bosh menyu")
async def back_to_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Bosh menyuga qaytdingiz. Kerakli bo'limni tanlang:",
        reply_markup=get_main_keyboard()
    )


# ----------------- 1-BO'LIM: BSB ISHLASH -----------------
@dp.message(F.text == "📝 BSB ishlash")
async def open_bsb_section(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.bsb_mode)
    prompt_text = (
        "📝 **BSB ishlash bo'limi**\n\n"
        "Iltimos, BSB, CHSB yoki nazorat ishi savolini **rasm** yoki **matn** ko'rinishida yuboring.\n\n"
        "💡 *Maslahat: Rasm aniq ko'ringan bo'lishi kerak. Topshiriq 100% to'g'ri va qadamma-qadam ishlab beriladi!*"
    )
    await message.answer(prompt_text, parse_mode="Markdown", reply_markup=get_bsb_keyboard())


# BSB - Matn yuborilganda
@dp.message(BotStates.bsb_mode, F.text)
async def process_bsb_text(message: types.Message):
    if message.text in ["🔙 Bosh menyu", "/start", "/menu"]:
        return

    wait_msg = await message.answer("⏳ Savol o'rganilmoqda va yechim tayyorlanmoqda...")
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    prompt = (
        "Quyidagi BSB / nazorat ishi / fan savolini o'zbek tilida 100% aniq, qadamma-qadam, "
        "barcha formulalari va qoidalari bilan to'liq ishlab ber. Yakuniy javobni alohida ajratib ko'rsat:\n\n"
        f"{message.text}"
    )
    contents = [
        genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=prompt)]
        )
    ]

    try:
        solution = await call_gemini(contents, BSB_SYSTEM_PROMPT)
        await wait_msg.delete()
        await send_smart_message(message, solution, reply_markup=get_bsb_keyboard())
    except Exception as e:
        logging.error(f"BSB Text xatosi: {e}")
        await wait_msg.delete()
        await message.answer(
            f"Kechirasiz, yechim tayyorlashda xatolik yuz berdi: {e}\nIltimos, qaytadan urinib ko'ring.",
            reply_markup=get_bsb_keyboard()
        )


# BSB - Rasm yuborilganda
@dp.message(BotStates.bsb_mode, F.photo)
async def process_bsb_photo(message: types.Message):
    wait_msg = await message.answer("⏳ Rasm qabul qilindi. Topshiriqlar tahlil qilinmoqda va yechim tayyorlanmoqda...")
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        # Eng yuqori sifatli rasmni yuklab olish
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        photo_stream = io.BytesIO()
        await bot.download_file(file_info.file_path, photo_stream)
        photo_bytes = photo_stream.getvalue()

        caption_info = f"\nQo'shimcha izoh: {message.caption}" if message.caption else ""
        prompt = (
            "Ushbu rasmdagi BSB / nazorat ishi / test topshiriqlarini diqqat bilan o'rganib chiq.\n"
            "1. Rasmdagi barcha savol va masalalarni tartib bilan aniqla.\n"
            "2. Har bir savolga 100% aniq, to'liq, qadamma-qadam va batafsil yechim ber.\n"
            "3. Barcha formulalar, hisob-kitoblar va qoidalarni aniq yoz.\n"
            "4. Yakuniy javoblarni alohida ajratib, o'quvchi to'g'ridan-to'g'ri daftarga ko'chirib olishi uchun eng yuqori sifatda tayyorla."
            f"{caption_info}"
        )

        contents = [
            genai_types.Content(
                role="user",
                parts=[
                    genai_types.Part.from_text(text=prompt),
                    genai_types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg")
                ]
            )
        ]

        solution = await call_gemini(contents, BSB_SYSTEM_PROMPT)
        await wait_msg.delete()
        await send_smart_message(message, solution, reply_markup=get_bsb_keyboard())
    except Exception as e:
        logging.error(f"BSB Photo xatosi: {e}")
        await wait_msg.delete()
        await message.answer(
            f"Rasm tahlilida xatolik yuz berdi: {e}\nIltimos, rasmni aniqroq tushirib qaytadan yuboring.",
            reply_markup=get_bsb_keyboard()
        )


# BSB - Fayl (hujjat) ko'rinishidagi rasm yuborilganda
@dp.message(BotStates.bsb_mode, F.document)
async def process_bsb_document(message: types.Message):
    doc = message.document
    if doc.mime_type and doc.mime_type.startswith("image/"):
        wait_msg = await message.answer("⏳ Hujjatdagi rasm tahlil qilinmoqda...")
        try:
            file_info = await bot.get_file(doc.file_id)
            doc_stream = io.BytesIO()
            await bot.download_file(file_info.file_path, doc_stream)
            doc_bytes = doc_stream.getvalue()

            prompt = (
                "Ushbu hujjatdagi rasmda keltirilgan BSB / nazorat ishi topshiriqlarini to'liq va mukammal yechib ber."
            )
            contents = [
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part.from_text(text=prompt),
                        genai_types.Part.from_bytes(data=doc_bytes, mime_type=doc.mime_type)
                    ]
                )
            ]
            solution = await call_gemini(contents, BSB_SYSTEM_PROMPT)
            await wait_msg.delete()
            await send_smart_message(message, solution, reply_markup=get_bsb_keyboard())
        except Exception as e:
            await wait_msg.delete()
            await message.answer(f"Xatolik yuz berdi: {e}", reply_markup=get_bsb_keyboard())
    else:
        await message.answer("Iltimos, topshiriqni rasm yoki matn shaklida yuboring.", reply_markup=get_bsb_keyboard())


# ----------------- 2-BO'LIM: AI BILAN SUHBAT -----------------
@dp.message(F.text == "🤖 AI bilan suhbat")
async def open_ai_section(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.ai_chat_mode)
    prompt_text = (
        "🤖 **AI bilan erkin suhbat rejimi yoqildi!**\n\n"
        "Menga istalgan savolingizni yozishingiz yoki rasm yuborishingiz mumkin:\n"
        "• Har qanday fan, dasturlash va hisob-kitoblar\n"
        "• Insholar, matnlar, tarjimalar va maqolalar\n"
        "• Maslahatlar, tahlillar va yangi g'oyalar\n"
        "• Rasmlarni tahlil qilish\n\n"
        "💡 *Men siz bilan suhbat kontekstini eslab qolaman!*\n"
        "Yangi mavzuga o'tish uchun: «🔄 Yangi suhbat» tugmasini bosing."
    )
    await message.answer(prompt_text, parse_mode="Markdown", reply_markup=get_ai_chat_keyboard())


# AI suhbat tarixini tozalash
@dp.message(F.text == "🔄 Yangi suhbat")
async def reset_ai_chat(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_conversations.pop(user_id, None)
    await message.answer(
        "✅ Suhbat tarixi tozalandi. Yangi suhbatni boshlaymiz! Savolingizni yuborishingiz mumkin:",
        reply_markup=get_ai_chat_keyboard()
    )


# AI suhbat - Matn yuborilganda
@dp.message(BotStates.ai_chat_mode, F.text)
async def process_ai_chat_text(message: types.Message):
    if message.text in ["🔙 Bosh menyu", "🔄 Yangi suhbat", "/start", "/menu"]:
        return

    user_id = message.from_user.id
    history = user_conversations.get(user_id, [])

    # Xabarlar tarixini me'yorda saqlash (oxirgi 16 ta xabar)
    if len(history) > 16:
        history = history[-16:]

    user_part = genai_types.Part.from_text(text=message.text)
    history.append(genai_types.Content(role="user", parts=[user_part]))

    wait_msg = await message.answer("🤔 O'ylayapman...")
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        reply_text = await call_gemini(history, AI_CHAT_SYSTEM_PROMPT)
        # Model javobini tarixga qo'shish
        model_part = genai_types.Part.from_text(text=reply_text)
        history.append(genai_types.Content(role="model", parts=[model_part]))
        user_conversations[user_id] = history

        await wait_msg.delete()
        await send_smart_message(message, reply_text, reply_markup=get_ai_chat_keyboard())
    except Exception as e:
        logging.error(f"AI Chat xatosi: {e}")
        await wait_msg.delete()
        # Xatolik bo'lsa oxirgi yuborilgan xabarni tarixdan o'chirish
        if history and history[-1].role == "user":
            history.pop()
        await message.answer(
            f"Kechirasiz, xatolik yuz berdi: {e}\nIltimos, qaytadan urinib ko'ring.",
            reply_markup=get_ai_chat_keyboard()
        )


# AI suhbat - Rasm yuborilganda
@dp.message(BotStates.ai_chat_mode, F.photo)
async def process_ai_chat_photo(message: types.Message):
    user_id = message.from_user.id
    history = user_conversations.get(user_id, [])

    wait_msg = await message.answer("⏳ Rasm o'rganilmoqda...")
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        photo_stream = io.BytesIO()
        await bot.download_file(file_info.file_path, photo_stream)
        photo_bytes = photo_stream.getvalue()

        user_text = message.caption if message.caption else "Ushbu rasmni tahlil qilib, mazmunini tushuntirib bering."
        user_parts = [
            genai_types.Part.from_text(text=user_text),
            genai_types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg")
        ]

        # Tarixga qo'shish
        history.append(genai_types.Content(role="user", parts=user_parts))
        reply_text = await call_gemini(history, AI_CHAT_SYSTEM_PROMPT)

        history.append(genai_types.Content(role="model", parts=[genai_types.Part.from_text(text=reply_text)]))
        user_conversations[user_id] = history

        await wait_msg.delete()
        await send_smart_message(message, reply_text, reply_markup=get_ai_chat_keyboard())
    except Exception as e:
        logging.error(f"AI Photo xatosi: {e}")
        await wait_msg.delete()
        await message.answer(
            f"Rasm tahlilida xatolik: {e}",
            reply_markup=get_ai_chat_keyboard()
        )


# ----------------- UMUMIY XABARLAR (Foydalanuvchi tugma bosmasdan yozsa) -----------------
@dp.message(F.text)
async def process_any_text(message: types.Message, state: FSMContext):
    # Agar foydalanuvchi holatni tanlamagan bo'lsa, to'g'ridan-to'g'ri AI orqali aqlli javob qaytaradi
    wait_msg = await message.answer("🤔 O'ylayapman...")
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        contents = [
            genai_types.Content(
                role="user",
                parts=[genai_types.Part.from_text(text=message.text)]
            )
        ]
        reply_text = await call_gemini(contents, AI_CHAT_SYSTEM_PROMPT)
        await wait_msg.delete()
        await send_smart_message(message, reply_text, reply_markup=get_main_keyboard())
    except Exception as e:
        await wait_msg.delete()
        await message.answer(
            f"Xatolik yuz berdi: {e}\nIltimos, pastdagi bo'limlardan birini tanlang:",
            reply_markup=get_main_keyboard()
        )


@dp.message(F.photo)
async def process_any_photo(message: types.Message):
    # Holatsiz yuborilgan rasmni ham BSB/savol sifatida tahlil qilish
    wait_msg = await message.answer("⏳ Rasm tahlil qilinmoqda...")
    try:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        photo_stream = io.BytesIO()
        await bot.download_file(file_info.file_path, photo_stream)
        photo_bytes = photo_stream.getvalue()

        caption = message.caption if message.caption else "Ushbu rasmdagi topshiriq yoki savolga to'liq javob bering."
        contents = [
            genai_types.Content(
                role="user",
                parts=[
                    genai_types.Part.from_text(text=caption),
                    genai_types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg")
                ]
            )
        ]
        reply_text = await call_gemini(contents, BSB_SYSTEM_PROMPT)
        await wait_msg.delete()
        await send_smart_message(message, reply_text, reply_markup=get_main_keyboard())
    except Exception as e:
        await wait_msg.delete()
        await message.answer(f"Xatolik yuz berdi: {e}", reply_markup=get_main_keyboard())


# ----------------- WEB SERVER (Hosting / 24/7 ishlash uchun) -----------------
async def handle_ping(request):
    return web.Response(text="Bot faol va ishlamoqda! Status: 200 OK")


async def run_web_server():
    try:
        app = web.Application()
        app.router.add_get("/", handle_ping)
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.environ.get("PORT", 8080))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logging.info(f"Web server port {port} da ishga tushdi.")
    except Exception as e:
        logging.warning(f"Web serverni ishga tushirishda ogohlantirish (bu bot ishlashiga ta'sir qilmaydi): {e}")


# ----------------- ASOSIY ISHGA TUSHIRISH (MAIN) -----------------
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    logging.info("Bot ishga tushmoqda...")

    # Web serverni orqa fonda ishga tushirish
    asyncio.create_task(run_web_server())

    # Eski kutilmagan xabarlarni tozalash va pollingni boshlash
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi.")