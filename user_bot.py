import asyncio
import os
import logging
import httpx
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

# .env yuklash
load_dotenv()

# --- KONFIGURATSIYA ---
USER_BOT_TOKEN = os.getenv("USER_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=USER_BOT_TOKEN)
dp = Dispatcher()

# --- FSM (HOLATLAR) ---
class RegistrationStates(StatesGroup):
    name = State()
    phone = State()
    address = State()

class EditStates(StatesGroup):
    editing_name = State()
    editing_phone = State()
    editing_address = State()

class OrderStates(StatesGroup):
    selecting_product = State()
    entering_quantity = State()
    confirming_basket = State()
    entering_delivery_time = State()

# --- BACKEND API BILAN ISHLASH ---

async def get_user_me(tg_id: str | int):
    """Foydalanuvchi ma'lumotlarini olish"""
    url = f"{BACKEND_URL}/users/me/{tg_id}/"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, timeout=10.0)
            if res.status_code == 200:
                return res.json()
            logger.warning(f"User not found: {tg_id}, status: {res.status_code}")
            return None
        except httpx.TimeoutException:
            logger.error(f"Timeout getting user: {tg_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting user {tg_id}: {e}")
            return None

async def register_user_api(data: dict):
    """Yangi foydalanuvchini ro'yxatdan o'tkazish"""
    url = f"{BACKEND_URL}/users/"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, json=data, timeout=10.0)
            if res.status_code not in [200, 201]:
                logger.error(f"Registration failed: {res.status_code}, {res.text}")
            return res
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return None

async def update_user_api(tg_id: str | int, data: dict):
    """Foydalanuvchi ma'lumotlarini yangilash"""
    url = f"{BACKEND_URL}/users/me/{tg_id}/"
    headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            res = await client.put(url, json=data, headers=headers, timeout=10.0)
            if res.status_code not in [200, 204]:
                logger.error(f"Update failed: {res.status_code}, {res.text}")
            return res
        except Exception as e:
            logger.error(f"Update error: {e}")
            return None

async def get_products():
    """Barcha mahsulotlarni olish"""
    url = f"{BACKEND_URL}/products/"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, timeout=10.0)
            if res.status_code == 200:
                return res.json()
            logger.error(f"Failed to get products: {res.status_code}")
            return []
        except Exception as e:
            logger.error(f"Products error: {e}")
            return []

async def create_order_api(payload: dict):
    """Yangi buyurtma yaratish"""
    url = f"{BACKEND_URL}/orders/"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, json=payload, timeout=10.0)
            if res.status_code not in [200, 201]:
                logger.error(f"Order creation failed: {res.status_code}, {res.text}")
            return res
        except Exception as e:
            logger.error(f"Order creation error: {e}")
            return None

async def get_my_orders_api(tg_id: str | int, limit: int = 5, offset: int = 0):
    """Foydalanuvchi buyurtmalarini olish"""
    url = f"{BACKEND_URL}/orders/user/"
    params = {"telegram_id": str(tg_id), "limit": limit, "offset": offset}
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, params=params, timeout=10.0)
            if res.status_code == 200:
                return res.json()
            logger.error(f"Failed to get orders: {res.status_code}")
            return []
        except Exception as e:
            logger.error(f"Orders error: {e}")
            return []

# --- KEYBOARDS ---

def get_main_menu():
    """Asosiy menyu tugmalari"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 Yangi buyurtma")],
            [KeyboardButton(text="📦 Mening buyurtmalarim")],
            [KeyboardButton(text="👤 Profilim"), KeyboardButton(text="⚙️ Sozlamalar")]
        ],
        resize_keyboard=True
    )

def get_phone_keyboard():
    """Telefon raqamini yuborish tugmasi"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True, 
        one_time_keyboard=True
    )

def get_cancel_keyboard():
    """Bekor qilish tugmasi"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True
    )

def format_date(date_str):
    """Sanani formatlash"""
    if not date_str:
        return "-"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception as e:
        logger.error(f"Date formatting error: {e}")
        return date_str

def format_price(price):
    """Narxni formatlash"""
    try:
        return f"{int(price):,}".replace(",", " ")
    except:
        return str(price)

# --- CANCEL HANDLER ---

@dp.message(F.text == "❌ Bekor qilish")
async def cancel_handler(message: Message, state: FSMContext):
    """Har qanday jarayonni bekor qilish"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Hech narsa bekor qilinmadi.", reply_markup=get_main_menu())
        return
    
    await state.clear()
    await message.answer("❌ Jarayon bekor qilindi.", reply_markup=get_main_menu())

# --- 1. START VA RO'YXATDAN O'TISH ---

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Bot ishga tushganda"""
    await state.clear()  # Oldingi holatni tozalash
    
    user = await get_user_me(message.from_user.id)
    if user:
        await message.answer(
            f"👋 Xush kelibsiz, {user['name']}!\n\n"
            f"📱 Bot orqali yangi buyurtma berishingiz, buyurtmalaringizni kuzatishingiz mumkin.",
            reply_markup=get_main_menu()
        )
    else:
        await message.answer(
            "👋 Assalomu alaykum!\n\n"
            "Botdan foydalanish uchun ro'yxatdan o'ting.\n\n"
            "✍️ Iltimos, to'liq ismingizni kiriting:",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(RegistrationStates.name)

@dp.message(RegistrationStates.name)
async def reg_name(message: Message, state: FSMContext):
    """Ism kiritish"""
    name = message.text.strip()
    
    if len(name) < 3:
        await message.answer("❌ Ism juda qisqa. Kamida 3 ta harf kiriting:")
        return
    
    if len(name) > 100:
        await message.answer("❌ Ism juda uzun. Qisqaroq kiriting:")
        return
    
    await state.update_data(name=name)
    await message.answer(
        "📱 Endi telefon raqamingizni yuboring:\n\n"
        "Raqamni qo'lda yozishingiz yoki pastdagi tugmani bosishingiz mumkin.",
        reply_markup=get_phone_keyboard()
    )
    await state.set_state(RegistrationStates.phone)

@dp.message(RegistrationStates.phone, F.contact | F.text)
async def reg_phone(message: Message, state: FSMContext):
    """Telefon raqam kiritish"""
    if message.contact:
        phone = message.contact.phone_number
    else:
        phone = message.text.strip()
        # Telefon raqam validatsiyasi
        phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not phone.startswith("+"):
            if phone.startswith("998"):
                phone = "+" + phone
            else:
                phone = "+998" + phone
        
        if len(phone) < 12:
            await message.answer(
                "❌ Noto'g'ri telefon raqam formati.\n\n"
                "Namuna: +998901234567 yoki 901234567",
                reply_markup=get_phone_keyboard()
            )
            return
    
    await state.update_data(phone=phone)
    await message.answer(
        "📍 Yashash manzilingizni kiriting:\n\n"
        "Masalan: Toshkent shahar, Chilonzor tumani, 12-kvartal",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(RegistrationStates.address)

@dp.message(RegistrationStates.address)
async def reg_address(message: Message, state: FSMContext):
    """Manzil kiritish va ro'yxatdan o'tishni yakunlash"""
    address = message.text.strip()
    
    if len(address) < 10:
        await message.answer("❌ Manzil juda qisqa. To'liqroq kiriting:")
        return
    
    data = await state.get_data()
    payload = {
        "name": data['name'],
        "phone": data['phone'],
        "address": address,
        "telegram_id": str(message.from_user.id)
    }
    
    await message.answer("⏳ Ro'yxatdan o'tkazilmoqda...", reply_markup=ReplyKeyboardRemove())
    
    res = await register_user_api(payload)
    if res and res.status_code in [200, 201]:
        await message.answer(
            "✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\n"
            "Endi siz buyurtma berishingiz mumkin.",
            reply_markup=get_main_menu()
        )
        await state.clear()
    else:
        error_msg = "❌ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.\n\n"
        if res:
            try:
                error_data = res.json()
                if isinstance(error_data, dict):
                    for key, value in error_data.items():
                        if isinstance(value, list):
                            error_msg += f"{key}: {', '.join(map(str, value))}\n"
            except:
                pass
        
        await message.answer(error_msg)
        await message.answer("Qayta boshlash uchun /start ni bosing.")
        await state.clear()

# --- 2. MENING BUYURTMALARIM (PAGINATSIYA BILAN) ---

async def show_my_orders(message_or_query, tg_id: int, offset: int = 0):
    """Buyurtmalarni ko'rsatish"""
    limit = 5
    
    # Loading animation
    if isinstance(message_or_query, Message):
        loading_msg = await message_or_query.answer("⏳ Buyurtmalar yuklanmoqda...")
    
    orders = await get_my_orders_api(tg_id, limit, offset)
    
    if isinstance(message_or_query, Message):
        await loading_msg.delete()
    
    if not orders and offset == 0:
        text = "📦 Sizda hali buyurtmalar yo'q.\n\n🛍 Yangi buyurtma berish uchun asosiy menyudan tugmani bosing."
        if isinstance(message_or_query, Message):
            await message_or_query.answer(text, reply_markup=get_main_menu())
        else:
            await message_or_query.message.answer(text, reply_markup=get_main_menu())
        return
    
    if not orders:
        text = "📦 Boshqa buyurtmalar yo'q."
        if isinstance(message_or_query, Message):
            await message_or_query.answer(text)
        else:
            await message_or_query.message.answer(text)
        return

    # Har bir buyurtmani alohida xabar sifatida yuborish
    for idx, o in enumerate(orders, start=offset+1):
        # Status emoji va nomi
        status_map = {
            'kutilmoqda': ('⌛', 'Kutilmoqda'),
            'tayyorlanmoqda': ('👨‍🍳', 'Tayyorlanmoqda'),
            'yetkazilmoqda': ('🛵', 'Yetkazilmoqda'),
            'yetkazildi': ('✅', 'Yetkazildi'),
            'bekor_qilindi': ('❌', 'Bekor qilindi')
        }
        status_emoji, status_text = status_map.get(o['status'], ('❓', o['status'].capitalize()))
        
        # Mahsulotlar ro'yxati
        items_text = ""
        for item in o.get('items', []):
            bonus = " 🎁" if item.get('is_bonus') else ""
            items_text += f"   • {item['product_name']}: {item['quantity']} dona{bonus}\n"

        # Asosiy ma'lumot
        text = (
            f"🆔 <b>Buyurtma #{o['id']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{status_emoji} <b>Status:</b> {status_text}\n"
            f"📅 <b>Sana:</b> {format_date(o.get('created_at'))}\n"
            f"💰 <b>Summa:</b> {format_price(o.get('total_amount', 0))} so'm\n\n"
            f"📦 <b>Mahsulotlar:</b>\n{items_text}"
        )

        # Kuryer ma'lumoti
        if o.get('courier_name'):
            text += f"\n🛵 <b>Kuryer:</b> {o['courier_name']}"
            if o.get('courier_phone'):
                text += f" ({o['courier_phone']})"
            text += "\n"
        
        # Yetkazilgan buyurtmalar uchun qo'shimcha ma'lumot
        if o['status'] == 'yetkazildi':
            if o.get('delivered_at'):
                text += f"🏁 <b>Yetkazildi:</b> {format_date(o['delivered_at'])}\n"
            if o.get('rating'):
                stars = "⭐" * o['rating']
                text += f"📊 <b>Reyting:</b> {stars} ({o['rating']}/5)\n"
            if o.get('rating_comment'):
                text += f"💬 <b>Izoh:</b> {o['rating_comment']}\n"
        
        # Yetkazib berish vaqti
        if o.get('delivery_time'):
            text += f"\n🕒 <b>Yetkazish vaqti:</b> {o['delivery_time']}"
        
        await bot.send_message(tg_id, text, parse_mode="HTML")

    # Pagination tugmalari
    nav_btns = []
    if offset > 0:
        nav_btns.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"my_orders_{offset-limit}"))
    if len(orders) == limit:
        nav_btns.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"my_orders_{offset+limit}"))
    
    if nav_btns:
        kb = InlineKeyboardMarkup(inline_keyboard=[nav_btns])
        page_info = f"📄 Sahifa {(offset//limit)+1}"
        await bot.send_message(tg_id, page_info, reply_markup=kb)

@dp.message(F.text == "📦 Mening buyurtmalarim")
async def my_orders_handler(message: Message):
    """Buyurtmalarni ko'rish"""
    await show_my_orders(message, message.from_user.id, 0)

@dp.callback_query(F.data.startswith("my_orders_"))
async def my_orders_pagination(callback: CallbackQuery):
    """Buyurtmalar sahifalari"""
    offset = int(callback.data.split("_")[-1])
    await callback.message.delete()
    await show_my_orders(callback, callback.from_user.id, offset)
    await callback.answer()

# --- 3. PROFIL VA SOZLAMALAR ---

@dp.message(F.text == "👤 Profilim")
async def show_profile(message: Message):
    """Profil ma'lumotlarini ko'rsatish"""
    u = await get_user_me(message.from_user.id)
    if u:
        text = (
            "👤 <b>Sizning profilingiz</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"👨‍💼 <b>Ism:</b> {u['name']}\n"
            f"📞 <b>Telefon:</b> {u['phone']}\n"
            f"📍 <b>Manzil:</b> {u['address']}\n\n"
            f"💬 Ma'lumotlarni o'zgartirish uchun <b>⚙️ Sozlamalar</b> tugmasini bosing."
        )
        await message.answer(text, parse_mode="HTML")
    else:
        await message.answer("❌ Profil topilmadi. Iltimos, qaytadan ro'yxatdan o'ting.\n\n/start")

@dp.message(F.text == "⚙️ Sozlamalar")
async def settings_menu(message: Message):
    """Sozlamalar menyusi"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Ismni o'zgartirish", callback_data="edit_name")],
        [InlineKeyboardButton(text="📱 Telefon raqamni o'zgartirish", callback_data="edit_phone")],
        [InlineKeyboardButton(text="📍 Manzilni o'zgartirish", callback_data="edit_address")],
        [InlineKeyboardButton(text="❌ Yopish", callback_data="close_settings")]
    ])
    await message.answer(
        "⚙️ <b>Sozlamalar</b>\n\n"
        "O'zgartirmoqchi bo'lgan ma'lumotni tanlang:",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "close_settings")
async def close_settings(callback: CallbackQuery):
    """Sozlamalarni yopish"""
    await callback.message.delete()
    await callback.answer("✅ Yopildi")

@dp.callback_query(F.data.startswith("edit_"))
async def edit_callback(callback: CallbackQuery, state: FSMContext):
    """Tahrirlash callback"""
    field = callback.data.split("_")[1]
    
    field_names = {
        'name': ('ism', '✍️ Yangi ismingizni kiriting:'),
        'phone': ('telefon raqam', '📱 Yangi telefon raqamingizni kiriting yoki yuborishingiz mumkin:'),
        'address': ('manzil', '📍 Yangi manzilingizni kiriting:')
    }
    
    field_name, prompt = field_names.get(field, ('', ''))
    
    await callback.message.delete()
    
    if field == 'phone':
        await callback.message.answer(prompt, reply_markup=get_phone_keyboard())
    else:
        await callback.message.answer(prompt, reply_markup=get_cancel_keyboard())
    
    if field == 'name':
        await state.set_state(EditStates.editing_name)
    elif field == 'phone':
        await state.set_state(EditStates.editing_phone)
    else:
        await state.set_state(EditStates.editing_address)
    
    await callback.answer()

@dp.message(EditStates.editing_name)
async def edit_name_handler(message: Message, state: FSMContext):
    """Ismni tahrirlash"""
    name = message.text.strip()
    
    if len(name) < 3:
        await message.answer("❌ Ism juda qisqa. Kamida 3 ta harf kiriting:")
        return
    
    await message.answer("⏳ Saqlanmoqda...", reply_markup=ReplyKeyboardRemove())
    
    res = await update_user_api(message.from_user.id, {"name": name})
    if res and res.status_code in [200, 204]:
        await message.answer("✅ Ism muvaffaqiyatli yangilandi!", reply_markup=get_main_menu())
    else:
        await message.answer("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.", reply_markup=get_main_menu())
    
    await state.clear()

@dp.message(EditStates.editing_phone, F.contact | F.text)
async def edit_phone_handler(message: Message, state: FSMContext):
    """Telefon raqamni tahrirlash"""
    if message.contact:
        phone = message.contact.phone_number
    else:
        phone = message.text.strip()
        phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not phone.startswith("+"):
            if phone.startswith("998"):
                phone = "+" + phone
            else:
                phone = "+998" + phone
        
        if len(phone) < 12:
            await message.answer(
                "❌ Noto'g'ri telefon raqam formati.\n\n"
                "Namuna: +998901234567 yoki 901234567",
                reply_markup=get_phone_keyboard()
            )
            return
    
    await message.answer("⏳ Saqlanmoqda...", reply_markup=ReplyKeyboardRemove())
    
    res = await update_user_api(message.from_user.id, {"phone": phone})
    if res and res.status_code in [200, 204]:
        await message.answer("✅ Telefon raqam muvaffaqiyatli yangilandi!", reply_markup=get_main_menu())
    else:
        await message.answer("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.", reply_markup=get_main_menu())
    
    await state.clear()

@dp.message(EditStates.editing_address)
async def edit_address_handler(message: Message, state: FSMContext):
    """Manzilni tahrirlash"""
    address = message.text.strip()
    
    if len(address) < 10:
        await message.answer("❌ Manzil juda qisqa. To'liqroq kiriting:")
        return
    
    await message.answer("⏳ Saqlanmoqda...", reply_markup=ReplyKeyboardRemove())
    
    res = await update_user_api(message.from_user.id, {"address": address})
    if res and res.status_code in [200, 204]:
        await message.answer("✅ Manzil muvaffaqiyatli yangilandi!", reply_markup=get_main_menu())
    else:
        await message.answer("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.", reply_markup=get_main_menu())
    
    await state.clear()

# --- 4. YANGI BUYURTMA BERISH ---

@dp.message(F.text == "🛍 Yangi buyurtma")
async def start_order(message: Message, state: FSMContext):
    """Yangi buyurtma boshlash"""
    await state.clear()
    await state.update_data(basket=[])
    
    await message.answer("⏳ Mahsulotlar yuklanmoqda...", reply_markup=ReplyKeyboardRemove())
    await show_products(message, state)

async def show_products(message: Message, state: FSMContext):
    """Mahsulotlarni ko'rsatish"""
    products = await get_products()
    
    if not products:
        await message.answer(
            "❌ Hozirda mahsulotlar mavjud emas.\n\n"
            "Iltimos, keyinroq qaytadan urinib ko'ring.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        return
    
    data = await state.get_data()
    basket_ids = [item['product_id'] for item in data.get('basket', [])]
    
    # Hali savatga qo'shilmagan mahsulotlar
    available_products = [p for p in products if p['id'] not in basket_ids]
    
    if not available_products:
        await show_basket_summary(message, state)
        return
    
    kb = []
    for product in available_products:
        price_text = f"{format_price(product['sell_price'])} so'm"
        kb.append([InlineKeyboardButton(
            text=f"{product['name']} - {price_text}",
            callback_data=f"product_{product['id']}"
        )])
    
    # Savat tugmasi (agar savat bo'sh bo'lmasa)
    basket = data.get('basket', [])
    if basket:
        kb.append([InlineKeyboardButton(
            text=f"🛒 Savatni ko'rish ({len(basket)})",
            callback_data="view_basket"
        )])
    
    kb.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_order")])
    
    await message.answer(
        "🛍 <b>Mahsulotlar</b>\n\n"
        "Buyurtma qilmoqchi bo'lgan mahsulotni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )
    await state.set_state(OrderStates.selecting_product)

@dp.callback_query(F.data == "cancel_order")
async def cancel_order(callback: CallbackQuery, state: FSMContext):
    """Buyurtmani bekor qilish"""
    await callback.message.delete()
    await state.clear()
    await callback.message.answer("❌ Buyurtma bekor qilindi.", reply_markup=get_main_menu())
    await callback.answer()

@dp.callback_query(F.data == "view_basket")
async def view_basket_callback(callback: CallbackQuery, state: FSMContext):
    """Savatni ko'rish"""
    await callback.message.delete()
    await show_basket_summary(callback.message, state)
    await callback.answer()

@dp.callback_query(OrderStates.selecting_product, F.data.startswith("product_"))
async def product_selected(callback: CallbackQuery, state: FSMContext):
    """Mahsulot tanlanganda"""
    product_id = int(callback.data.split("_")[1])
    products = await get_products()
    product = next((p for p in products if p['id'] == product_id), None)
    
    if not product:
        await callback.answer("❌ Mahsulot topilmadi", show_alert=True)
        return
    
    await state.update_data(current_product=product)
    
    text = (
        f"📦 <b>{product['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Narxi:</b> {format_price(product['sell_price'])} so'm\n\n"
        f"✍️ Nechta buyurtma qilasiz?\n"
        f"(Masalan: 1, 2, 3...)"
    )
    
    await callback.message.delete()
    
    # Agar rasm bo'lsa
    if product.get('image'):
        await callback.message.answer_photo(
            photo=product['image'],
            caption=text,
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
    else:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
    
    await state.set_state(OrderStates.entering_quantity)
    await callback.answer()

@dp.message(OrderStates.entering_quantity)
async def quantity_entered(message: Message, state: FSMContext):
    """Miqdor kiritilganda"""
    if not message.text.isdigit():
        await message.answer("❌ Iltimos, faqat son kiriting (masalan: 1, 2, 3):")
        return
    
    quantity = int(message.text)
    
    if quantity <= 0:
        await message.answer("❌ Miqdor kamida 1 bo'lishi kerak:")
        return
    
    if quantity > 100:
        await message.answer("❌ Bir vaqtning o'zida 100 tadan ko'p buyurtma berib bo'lmaydi:")
        return
    
    data = await state.get_data()
    product = data['current_product']
    basket = data.get('basket', [])
    
    # Savatga qo'shish
    basket.append({
        "product_id": product['id'],
        "product_name": product['name'],
        "quantity": quantity,
        "price": product['sell_price']
    })
    
    await state.update_data(basket=basket)
    
    # Davom etish tugmalari
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yana mahsulot qo'shish", callback_data="add_more")],
        [InlineKeyboardButton(text="✅ Buyurtmani rasmiylashtirish", callback_data="finalize_order")]
    ])
    
    total_items = sum(item['quantity'] for item in basket)
    await message.answer(
        f"✅ Savatga qo'shildi!\n\n"
        f"📦 Savatingizda: {len(basket)} xil mahsulot, jami {total_items} dona",
        reply_markup=kb
    )
    await state.set_state(OrderStates.confirming_basket)

@dp.callback_query(OrderStates.confirming_basket, F.data == "add_more")
async def add_more_products(callback: CallbackQuery, state: FSMContext):
    """Yana mahsulot qo'shish"""
    await callback.message.delete()
    await show_products(callback.message, state)
    await callback.answer()

@dp.callback_query(OrderStates.confirming_basket, F.data == "finalize_order")
async def finalize_order_callback(callback: CallbackQuery, state: FSMContext):
    """Buyurtmani rasmiylashtirish"""
    await callback.message.delete()
    await show_basket_summary(callback.message, state)
    await callback.answer()

async def show_basket_summary(message: Message, state: FSMContext):
    """Savat xulasasini ko'rsatish"""
    data = await state.get_data()
    basket = data.get('basket', [])
    
    if not basket:
        await message.answer(
            "🛒 Savatingiz bo'sh.\n\n"
            "Mahsulot qo'shish uchun /start ni bosing.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        return
    
    # Jami summa hisoblash
    total_amount = sum(item['quantity'] * item['price'] for item in basket)
    total_items = sum(item['quantity'] for item in basket)
    
    # Savatdagi mahsulotlar
    items_text = ""
    for idx, item in enumerate(basket, 1):
        item_total = item['quantity'] * item['price']
        items_text += (
            f"{idx}. <b>{item['product_name']}</b>\n"
            f"   {item['quantity']} dona × {format_price(item['price'])} = "
            f"{format_price(item_total)} so'm\n\n"
        )
    
    text = (
        f"🛒 <b>Sizning savatchangiz</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{items_text}"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Jami:</b> {total_items} dona mahsulot\n"
        f"💰 <b>To'lov summasi:</b> {format_price(total_amount)} so'm"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash va davom etish", callback_data="confirm_basket")],
        [InlineKeyboardButton(text="🗑 Savatni tozalash", callback_data="clear_basket")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_order")]
    ])
    
    await message.answer(text, parse_mode="HTML", reply_markup=kb)
    await state.set_state(OrderStates.confirming_basket)

@dp.callback_query(F.data == "clear_basket")
async def clear_basket(callback: CallbackQuery, state: FSMContext):
    """Savatni tozalash"""
    await state.update_data(basket=[])
    await callback.message.delete()
    await callback.message.answer(
        "🗑 Savat tozalandi.\n\n"
        "Yangi buyurtma uchun /start ni bosing.",
        reply_markup=get_main_menu()
    )
    await state.clear()
    await callback.answer("✅ Savat tozalandi")

@dp.callback_query(F.data == "confirm_basket")
async def confirm_basket(callback: CallbackQuery, state: FSMContext):
    """Savatni tasdiqlash va yetkazish vaqtini so'rash"""
    await callback.message.delete()
    await callback.message.answer(
        "🕒 <b>Yetkazib berish vaqti</b>\n\n"
        "Qachon yetkazib berish kerak?\n\n"
        "Masalan:\n"
        "• Tezroq\n"
        "• 1 soatdan keyin\n"
        "• Bugun kechqurun\n"
        "• Ertaga ertalab 10:00\n\n"
        "Yoki qo'shimcha izoh qoldiring:",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(OrderStates.entering_delivery_time)
    await callback.answer()

@dp.message(OrderStates.entering_delivery_time)
async def delivery_time_entered(message: Message, state: FSMContext):
    """Yetkazish vaqti kiritilganda"""
    delivery_time = message.text.strip()
    
    if len(delivery_time) < 2:
        await message.answer("❌ Iltimos, yetkazish vaqtini kiriting:")
        return
    
    data = await state.get_data()
    basket = data.get('basket', [])
    
    # Buyurtma yaratish
    order_items = [
        {
            "product_id": item['product_id'],
            "quantity": item['quantity']
        }
        for item in basket
    ]
    
    payload = {
        "telegram_id": str(message.from_user.id),
        "items": order_items,
        "delivery_time": delivery_time
    }
    
    await message.answer("⏳ Buyurtma rasmiylashtirilmoqda...", reply_markup=ReplyKeyboardRemove())
    
    res = await create_order_api(payload)
    
    if res and res.status_code in [200, 201]:
        try:
            order_data = res.json()
            order_id = order_data.get('id', '???')
            
            await message.answer(
                f"✅ <b>Buyurtma muvaffaqiyatli yaratildi!</b>\n\n"
                f"🆔 Buyurtma raqami: #{order_id}\n\n"
                f"📞 Tez orada operatorlarimiz siz bilan bog'lanadi.\n\n"
                f"📦 Buyurtma holatini <b>\"Mening buyurtmalarim\"</b> bo'limidan kuzatishingiz mumkin.",
                parse_mode="HTML",
                reply_markup=get_main_menu()
            )
        except:
            await message.answer(
                "✅ Buyurtma muvaffaqiyatli yaratildi!\n\n"
                "Tez orada operatorlarimiz siz bilan bog'lanadi.",
                reply_markup=get_main_menu()
            )
        
        await state.clear()
    else:
        error_msg = "❌ Buyurtma yaratishda xatolik yuz berdi.\n\n"
        
        if res:
            try:
                error_data = res.json()
                if isinstance(error_data, dict):
                    for key, value in error_data.items():
                        if isinstance(value, list):
                            error_msg += f"{key}: {', '.join(map(str, value))}\n"
                        else:
                            error_msg += f"{key}: {value}\n"
            except:
                error_msg += "Iltimos, qaytadan urinib ko'ring."
        
        await message.answer(error_msg, reply_markup=get_main_menu())
        await state.clear()

# --- BOSHQA XABARLAR ---

@dp.message()
async def unknown_message(message: Message):
    """Noma'lum xabarlar uchun"""
    await message.answer(
        "🤔 Kechirasiz, tushunmadim.\n\n"
        "Iltimos, pastdagi tugmalardan foydalaning yoki /start ni bosing.",
        reply_markup=get_main_menu()
    )

# --- MAIN ---
async def main():
    """Botni ishga tushirish"""
    print("🤖 User Bot ishga tushmoqda...")
    print(f"📡 Backend URL: {BACKEND_URL}")
    
    # Webhook ni o'chirish va polling boshlash
    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Bot tayyor!")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⛔ Bot to'xtatildi")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"❌ Xatolik: {e}")