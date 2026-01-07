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
from aiogram.exceptions import TelegramBadRequest

# .env yuklash
load_dotenv()

# --- KONFIGURATSIYA ---
USER_BOT_TOKEN = os.getenv("USER_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL")

# Loglarni chiroyli formatda chiqarish
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
    choosing_address_type = State()
    entering_delivery_time = State()

class RateStates(StatesGroup):
    selecting_stars = State()
    entering_comment = State()

# --- API ---
async def get_user_me(tg_id: str | int):
    url = f"{BACKEND_URL}/users/me/{tg_id}/"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, timeout=10.0)
            return res.json() if res.status_code == 200 else None
        except Exception as e:
            logger.error(f"API Error (get_user): {e}")
            return None

async def register_user_api(data: dict):
    url = f"{BACKEND_URL}/users/"
    async with httpx.AsyncClient() as client:
        try:
            return await client.post(url, json=data, timeout=10.0)
        except Exception as e:
            logger.error(f"API Error (register): {e}")
            return None

async def update_user_api(tg_id: str | int, data: dict):
    url = f"{BACKEND_URL}/users/me/{tg_id}/"
    headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            return await client.put(url, json=data, headers=headers, timeout=10.0)
        except Exception as e:
            logger.error(f"API Error (update): {e}")
            return None

async def get_products():
    url = f"{BACKEND_URL}/products/"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, timeout=10.0)
            return res.json() if res.status_code == 200 else []
        except Exception as e:
            logger.error(f"API Error (products): {e}")
            return []

async def create_order_api(payload: dict):
    url = f"{BACKEND_URL}/orders/"
    async with httpx.AsyncClient() as client:
        try:
            logger.info(f"📤 Order Payload: {payload}")
            return await client.post(url, json=payload, timeout=10.0)
        except Exception as e:
            logger.error(f"API Error (create_order): {e}")
            return None

async def get_my_orders_api(tg_id: str | int, limit: int = 5, offset: int = 0):
    url = f"{BACKEND_URL}/orders/user/"
    params = {"telegram_id": str(tg_id), "limit": limit, "offset": offset}
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, params=params, timeout=10.0)
            return res.json() if res.status_code == 200 else []
        except Exception as e:
            logger.error(f"API Error (my_orders): {e}")
            return []

async def rate_order_api(order_id: int, rating: int, comment: str):
    url = f"{BACKEND_URL}/orders/{order_id}/rate/"
    payload = {"rating": rating, "comment": comment}
    async with httpx.AsyncClient() as client:
        try:
            return await client.post(url, json=payload, timeout=10.0)
        except Exception as e:
            logger.error(f"API Error (rate): {e}")
            return None

# --- YORDAMCHI FUNKSIYALAR ---
def format_price(price):
    try: return f"{int(price):,}".replace(",", " ")
    except: return str(price)

def location_to_str(location: types.Location) -> str:
    return f"https://www.google.com/maps?q={location.latitude},{location.longitude}"

def format_date(date_str):
    if not date_str: return "-"
    try: return datetime.fromisoformat(date_str.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except: return date_str

# --- KEYBOARDS (UX/UI yaxshilangan) ---
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 Yangi buyurtma")],
            [KeyboardButton(text="📦 Mening buyurtmalarim")],
            [KeyboardButton(text="👤 Profilim"), KeyboardButton(text="⚙️ Sozlamalar")]
        ], resize_keyboard=True
    )

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Bekor qilish")]], resize_keyboard=True)

def get_phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)],
            [KeyboardButton(text="❌ Bekor qilish")]
        ], resize_keyboard=True, one_time_keyboard=True
    )

def get_location_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Lokatsiyani yuborish", request_location=True)],
            [KeyboardButton(text="❌ Bekor qilish")]
        ], resize_keyboard=True, one_time_keyboard=True
    )

def get_rating_keyboard(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i} ⭐", callback_data=f"rate_{order_id}_{i}") for i in range(1, 6)]])

# --- GLOBAL BEKOR QILISH ---
@dp.message(F.text == "❌ Bekor qilish")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Jarayon bekor qilindi. Asosiy menyudasiz.", reply_markup=get_main_menu())

@dp.callback_query(F.data == "cancel_order")
async def cancel_order_cb(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await state.clear()
    await callback.message.answer("❌ Buyurtma bekor qilindi.", reply_markup=get_main_menu())

# --- 1. START & RO'YXATDAN O'TISH ---
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user_me(message.from_user.id)
    if user:
        await message.answer(f"👋 Assalomu alaykum, <b>{user['name']}</b>!\nXush kelibsiz.", parse_mode="HTML", reply_markup=get_main_menu())
    else:
        await message.answer(
            "👋 Assalomu alaykum!\n\nBotimizdan foydalanish uchun, iltimos, ro'yxatdan o'ting.\n\n✍️ <b>Ismingizni kiriting:</b>", 
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(RegistrationStates.name)

@dp.message(RegistrationStates.name)
async def reg_name(message: Message, state: FSMContext):
    if len(message.text) < 3:
        await message.answer("⚠️ Ism juda qisqa. Iltimos, to'liq ismingizni kiriting:")
        return
    await state.update_data(name=message.text)
    await message.answer(
        "Rahmat! Endi telefon raqamingizni kiriting.\n\nPastdagi tugmani bosishingiz mumkin:", 
        reply_markup=get_phone_keyboard()
    )
    await state.set_state(RegistrationStates.phone)

@dp.message(RegistrationStates.phone, F.contact | F.text)
async def reg_phone(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await cancel_handler(message, state)
        return

    phone = message.contact.phone_number if message.contact else message.text
    phone = phone.replace(" ", "").replace("+", "").replace("-", "")
    
    if not phone.isdigit() or len(phone) < 9:
         await message.answer("⚠️ Iltimos, to'g'ri telefon raqam kiriting (masalan: 901234567).")
         return
    
    phone = "+" + phone
    await state.update_data(phone=phone)
    await message.answer(
        "📍 Endi manzilingizni kiriting.\n\nQo'lda yozishingiz yoki <b>Lokatsiya yuborish</b> tugmasini bosishingiz mumkin:", 
        parse_mode="HTML",
        reply_markup=get_location_keyboard()
    )
    await state.set_state(RegistrationStates.address)

@dp.message(RegistrationStates.address, F.text | F.location)
async def reg_address(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await cancel_handler(message, state)
        return

    address = location_to_str(message.location) if message.location else message.text
    data = await state.get_data()
    payload = {"name": data['name'], "phone": data['phone'], "address": address, "telegram_id": str(message.from_user.id)}
    
    msg = await message.answer("⏳ Ro'yxatdan o'tilmoqda...", reply_markup=ReplyKeyboardRemove())
    res = await register_user_api(payload)
    await msg.delete()

    if res and res.status_code in [200, 201]:
        await message.answer("✅ Tabriklaymiz! Siz muvaffaqiyatli ro'yxatdan o'tdingiz.", reply_markup=get_main_menu())
        await state.clear()
    else:
        await message.answer("❌ Tizimda xatolik yuz berdi. Iltimos, /start buyrug'i orqali qayta urinib ko'ring.")

# --- 2. 👤 PROFILIM ---
@dp.message(F.text == "👤 Profilim")
async def show_profile(message: Message):
    user = await get_user_me(message.from_user.id)
    if user:
        text = (
            f"👤 <b>Sizning ma'lumotlaringiz:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Ism:</b> {user['name']}\n"
            f"📞 <b>Telefon:</b> {user['phone']}\n"
            f"📍 <b>Manzil:</b> {user['address']}"
        )
        await message.answer(text, parse_mode="HTML")
    else:
        await message.answer("⚠️ Profil topilmadi. Iltimos, qaytadan ro'yxatdan o'ting: /start")

# --- 3. ⚙️ SOZLAMALAR ---
@dp.message(F.text == "⚙️ Sozlamalar")
async def settings(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Ismni o'zgartirish", callback_data="edit_name")],
        [InlineKeyboardButton(text="📱 Telefonni o'zgartirish", callback_data="edit_phone")],
        [InlineKeyboardButton(text="📍 Manzilni o'zgartirish", callback_data="edit_address")],
        [InlineKeyboardButton(text="❌ Yopish", callback_data="close_settings")]
    ])
    await m.answer("⚙️ <b>Sozlamalar bo'limi</b>\nQaysi ma'lumotni o'zgartirmoqchisiz?", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "close_settings")
async def close_s(c: CallbackQuery): await c.message.delete()

# Ism
@dp.callback_query(F.data == "edit_name")
async def edit_name_start(c: CallbackQuery, state: FSMContext):
    await c.message.delete()
    await c.message.answer("✍️ Yangi ismingizni kiriting:", reply_markup=get_cancel_keyboard())
    await state.set_state(EditStates.editing_name)

@dp.message(EditStates.editing_name)
async def save_new_name(m: Message, state: FSMContext):
    if await update_user_api(m.from_user.id, {"name": m.text}): 
        await m.answer("✅ Ismingiz muvaffaqiyatli o'zgartirildi!", reply_markup=get_main_menu())
    else:
        await m.answer("❌ Xatolik yuz berdi.", reply_markup=get_main_menu())
    await state.clear()

# Tel
@dp.callback_query(F.data == "edit_phone")
async def edit_phone_start(c: CallbackQuery, state: FSMContext):
    await c.message.delete()
    await c.message.answer("📱 Yangi telefon raqamingizni yuboring:", reply_markup=get_phone_keyboard())
    await state.set_state(EditStates.editing_phone)

@dp.message(EditStates.editing_phone)
async def save_new_phone(m: Message, state: FSMContext):
    if m.text == "❌ Bekor qilish": return await cancel_handler(m, state)
    p = m.contact.phone_number if m.contact else m.text
    # Tozalash
    p = p.replace(" ", "").replace("+", "")
    if not p.isdigit(): return await m.answer("⚠️ Noto'g'ri format.")
    p = "+" + p

    if await update_user_api(m.from_user.id, {"phone": p}): 
        await m.answer("✅ Telefon raqam yangilandi!", reply_markup=get_main_menu())
    else:
        await m.answer("❌ Xatolik yuz berdi.", reply_markup=get_main_menu())
    await state.clear()

# Manzil
@dp.callback_query(F.data == "edit_address")
async def edit_address_start(c: CallbackQuery, state: FSMContext):
    await c.message.delete()
    await c.message.answer("📍 Yangi manzilni yozing yoki lokatsiya yuboring:", reply_markup=get_location_keyboard())
    await state.set_state(EditStates.editing_address)

@dp.message(EditStates.editing_address)
async def save_new_address(m: Message, state: FSMContext):
    if m.text == "❌ Bekor qilish": return await cancel_handler(m, state)
    a = location_to_str(m.location) if m.location else m.text
    if await update_user_api(m.from_user.id, {"address": a}): 
        await m.answer("✅ Manzil yangilandi!", reply_markup=get_main_menu())
    else:
        await m.answer("❌ Xatolik yuz berdi.", reply_markup=get_main_menu())
    await state.clear()


# --- 4. 🛍 YANGI BUYURTMA ---
@dp.message(F.text == "🛍 Yangi buyurtma")
async def start_order(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(basket=[])
    
    msg = await message.answer("⏳ Mahsulotlar yuklanmoqda...", reply_markup=ReplyKeyboardRemove())
    products = await get_products()
    await msg.delete()
    
    await show_products(message, products, state)

async def show_products(message: Message, products: list, state: FSMContext):
    if not products:
        await message.answer("🤷‍♂️ Hozircha mahsulotlar mavjud emas.", reply_markup=get_main_menu())
        return
    
    data = await state.get_data()
    basket_ids = [item['product_id'] for item in data.get('basket', [])]
    available = [p for p in products if p['id'] not in basket_ids]
    
    if not available:
        await show_basket_summary(message, state)
        return
    
    kb = []
    # Mahsulotlar ro'yxatini chiroyli qilish (2 qatorli)
    row = []
    for p in available:
        btn = InlineKeyboardButton(text=f"{p['name']}", callback_data=f"product_{p['id']}")
        row.append(btn)
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    
    # Boshqaruv tugmalari
    controls = []
    if data.get('basket'):
        controls.append(InlineKeyboardButton(text=f"🛒 Savat ({len(data['basket'])})", callback_data="view_basket"))
    controls.append(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_order"))
    kb.append(controls)
    
    await message.answer(
        "🛍 <b>Quyidagi mahsulotlardan birini tanlang:</b>", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), 
        parse_mode="HTML"
    )
    await state.set_state(OrderStates.selecting_product)

@dp.callback_query(OrderStates.selecting_product, F.data.startswith("product_"))
async def product_selected(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split("_")[1])
    products = await get_products()
    product = next((p for p in products if p['id'] == pid), None)
    
    if not product: return await callback.answer("⚠️ Mahsulot topilmadi")
    
    await state.update_data(current_product=product)
    
    caption = (
        f"📦 <b>{product['name']}</b>\n"
        f"💰 <b>Narxi:</b> {format_price(product['sell_price'])} so'm\n\n"
        f"🔢 <b>Nechta buyurtma qilmoqchisiz?</b>\n"
        f"Miqdorni yozib yuboring (masalan: 1, 2, 5):"
    )
    
    await callback.message.delete()
    
    if product.get('image'):
        await callback.message.answer_photo(product['image'], caption=caption, parse_mode="HTML", reply_markup=get_cancel_keyboard())
    else:
        await callback.message.answer(caption, parse_mode="HTML", reply_markup=get_cancel_keyboard())
    
    await state.set_state(OrderStates.entering_quantity)

@dp.message(OrderStates.entering_quantity)
async def quantity_entered(message: Message, state: FSMContext):
    if not message.text.isdigit(): 
        await message.answer("⚠️ Iltimos, faqat raqam kiriting (masalan: 2).")
        return
    
    qty = int(message.text)
    if qty <= 0: 
        await message.answer("⚠️ Miqdor 1 dan kam bo'lmasligi kerak.")
        return

    data = await state.get_data()
    prod = data['current_product']
    basket = data.get('basket', [])
    
    # Savatga qo'shish
    basket.append({
        "product_id": prod['id'], 
        "product_name": prod['name'], 
        "quantity": qty, 
        "price": prod['sell_price']
    })
    await state.update_data(basket=basket)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yana mahsulot qo'shish", callback_data="add_more")],
        [InlineKeyboardButton(text="✅ Buyurtmani rasmiylashtirish", callback_data="finalize_order")]
    ])
    
    await message.answer(
        f"✅ <b>{prod['name']}</b> ({qty} dona) savatga qo'shildi.", 
        parse_mode="HTML", 
        reply_markup=kb
    )
    await state.set_state(OrderStates.confirming_basket)

@dp.callback_query(OrderStates.confirming_basket, F.data.in_({"add_more", "view_basket", "finalize_order"}))
async def basket_actions(c: CallbackQuery, state: FSMContext):
    await c.message.delete()
    if c.data == "add_more": 
        products = await get_products()
        await show_products(c.message, products, state)
    else: 
        await show_basket_summary(c.message, state)

async def show_basket_summary(message: Message, state: FSMContext):
    data = await state.get_data()
    basket = data.get('basket', [])
    if not basket:
        await message.answer("🛒 Savatingiz bo'sh.", reply_markup=get_main_menu())
        return await state.clear()

    total = sum(i['quantity'] * i['price'] for i in basket)
    items_text = ""
    for idx, x in enumerate(basket, 1):
        items_text += f"{idx}. <b>{x['product_name']}</b>\n   {x['quantity']} ta x {format_price(x['price'])} = {format_price(x['quantity']*x['price'])}\n"

    text = (
        f"🛒 <b>Sizning savatingiz:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{items_text}"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Jami summa:</b> {format_price(total)} so'm"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash va davom etish", callback_data="confirm_basket")],
        [InlineKeyboardButton(text="🗑 Savatni tozalash", callback_data="clear_basket")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "clear_basket")
async def clear_basket(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.delete()
    await c.message.answer("🗑 Savat tozalandi.", reply_markup=get_main_menu())

# --- MANZIL TANLASH (MANTIQ VA UX) ---

@dp.callback_query(F.data == "confirm_basket")
async def ask_address_type(c: CallbackQuery, state: FSMContext):
    await c.message.delete()
    
    # UX uchun: Avval foydalanuvchini joriy manzilini eslatamiz
    # Lekin API call qilmasdan tez ishlashi uchun umumiy so'raymiz
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Profilimdagi manzilga")],
            [KeyboardButton(text="📍 Yangi lokatsiya yuborish", request_location=True)],
            [KeyboardButton(text="❌ Bekor qilish")]
        ], resize_keyboard=True, one_time_keyboard=True
    )
    
    await c.message.answer(
        "📍 <b>Buyurtmani qayerga yetkazib beraylik?</b>\n\n"
        "Profilimgizdagi manzilni tanlashingiz yoki yangi manzil (lokatsiya) yuborishingiz mumkin.", 
        parse_mode="HTML", 
        reply_markup=kb
    )
    await state.set_state(OrderStates.choosing_address_type)

@dp.message(OrderStates.choosing_address_type)
async def handle_address_choice(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await cancel_handler(message, state)
        return

    # 1. Eski manzil
    if message.text == "🏠 Profilimdagi manzilga":
        await state.update_data(custom_location=None)
        await message.answer("✅ Tushunarli, profilingizdagi manzilga yetkazamiz.")
    
    # 2. Lokatsiya
    elif message.location:
        loc_str = location_to_str(message.location)
        await state.update_data(custom_location=loc_str)
        await message.answer("✅ Yangi lokatsiya qabul qilindi.")
        
    # 3. Matnli manzil (agar yozsa)
    elif message.text:
        await state.update_data(custom_location=message.text)
        await message.answer(f"✅ Yangi manzil qabul qilindi.")
        
    else:
        await message.answer("⚠️ Iltimos, manzilni tanlang yoki yuboring.")
        return

    await message.answer(
        "🕒 <b>Qachon yetkazib beraylik?</b>\n"
        "Masalan: 'Tezroq', 'Soat 18:00 da', 'Ertaga ertalab'.\n\n"
        "Iltimos, vaqtni yozib yuboring:", 
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(OrderStates.entering_delivery_time)

@dp.message(OrderStates.entering_delivery_time)
async def create_order_final(message: Message, state: FSMContext):
    if len(message.text) < 2:
        await message.answer("⚠️ Iltimos, vaqtni to'liqroq yozing.")
        return

    delivery_time = message.text
    data = await state.get_data()
    basket = data.get('basket', [])
    
    # Mantiq: Agar custom_location bo'lsa uni yuboramiz, bo'lmasa None (backend profilni oladi)
    custom_location = data.get('custom_location')
    
    items = [{"product_id": i['product_id'], "quantity": i['quantity']} for i in basket]
    
    payload = {
        "telegram_id": str(message.from_user.id),
        "items": items,
        "delivery_time": delivery_time,
        "current_location": custom_location
    }
    
    msg = await message.answer("⏳ Buyurtma rasmiylashtirilmoqda...", reply_markup=ReplyKeyboardRemove())
    res = await create_order_api(payload)
    await msg.delete()
    
    if res and res.status_code in [200, 201]:
        order_id = res.json().get('id', 'Noma\'lum')
        await message.answer(
            f"🎉 <b>Buyurtmangiz qabul qilindi!</b>\n\n"
            f"📞 Tez orada operatorlarimiz siz bilan bog'lanib, buyurtmani tasdiqlashadi.\n"
            f"Xaridingiz uchun rahmat!", 
            parse_mode="HTML", 
            reply_markup=get_main_menu()
        )
    else:
        await message.answer("❌ Kechirasiz, buyurtma yaratishda texnik xatolik yuz berdi. Iltimos, birozdan so'ng qayta urinib ko'ring.", reply_markup=get_main_menu())
    
    await state.clear()

# --- 5. 📦 MENING BUYURTMALARIM ---
@dp.message(F.text == "📦 Mening buyurtmalarim")
async def my_orders_handler(message: Message):
    await show_my_orders(message, message.from_user.id, 0)

@dp.callback_query(F.data.startswith("my_orders_"))
async def my_orders_pagination(callback: CallbackQuery):
    await callback.message.delete()
    await show_my_orders(callback, callback.from_user.id, int(callback.data.split("_")[-1]))

async def show_my_orders(msg_obj, tg_id, offset):
    orders = await get_my_orders_api(tg_id, 5, offset)
    if isinstance(msg_obj, CallbackQuery): msg_obj = msg_obj.message

    if not orders:
        if offset == 0: await msg_obj.answer("📦 Sizda hozircha buyurtmalar tarixi mavjud emas.", reply_markup=get_main_menu())
        else: await msg_obj.answer("📦 Boshqa buyurtmalar yo'q.")
        return

    for o in orders:
        txt = (
            f"🆔 <b>Buyurtma #{o['id']}</b>\n"
            f"📅 Sana: {format_date(o.get('created_at'))}\n"
            f"📊 Holati: <b>{o['status'].capitalize()}</b>\n"
            f"💰 Jami: {format_price(o.get('total_amount'))} so'm\n"
        )
        if o.get('courier_name'): txt += f"🛵 Kuryer: {o['courier_name']}\n"
        if o.get('rating'): txt += f"⭐️ Sizning bahoyingiz: {o['rating']}/5\n"
        
        kb = None
        if o['status'] == 'yetkazildi' and not o.get('rating'):
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⭐ Xizmatni baholash", callback_data=f"start_rate_{o['id']}") ]])
        
        await bot.send_message(tg_id, txt, parse_mode="HTML", reply_markup=kb)

    nav = []
    if offset > 0: nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"my_orders_{offset-5}"))
    if len(orders) == 5: nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"my_orders_{offset+5}"))
    if nav: await bot.send_message(tg_id, f"📄 Sahifa {offset//5 + 1}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[nav]))

# --- BAHOLASH ---
@dp.callback_query(F.data.startswith("start_rate_"))
async def start_rate(c: CallbackQuery, state: FSMContext):
    oid = int(c.data.split("_")[-1])
    await state.update_data(rate_oid=oid)
    await c.message.answer(
        f"🆔 <b>Buyurtma #{oid}</b>\n\n"
        "Xizmatimiz sifatini necha yulduz bilan baholaysiz?", 
        parse_mode="HTML",
        reply_markup=get_rating_keyboard(oid)
    )
    await state.set_state(RateStates.selecting_stars)
    await c.answer()

@dp.callback_query(RateStates.selecting_stars)
async def stars_sel(c: CallbackQuery, state: FSMContext):
    rating = int(c.data.split("_")[-1])
    await state.update_data(rating=rating)
    
    # Xabarni tahrirlash (try-except bilan, xavfsizlik uchun)
    try:
        await c.message.edit_text(
            f"⭐️ <b>{rating} yulduz</b> tanladingiz.\n\n"
            f"✍️ Iltimos, fikr yoki taklifingizni yozib qoldiring:",
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        # Agar rasm bo'lsa yoki edit qilib bo'lmasa yangi xabar yuboramiz
        await c.message.delete()
        await c.message.answer(f"⭐️ <b>{rating} yulduz</b> tanladingiz.\n\n✍️ Izohingizni yozib qoldiring:", parse_mode="HTML")

    await state.set_state(RateStates.entering_comment)

@dp.message(RateStates.entering_comment)
async def comment_ent(m: Message, state: FSMContext):
    d = await state.get_data()
    
    msg = await m.answer("⏳ Fikringiz saqlanmoqda...")
    res = await rate_order_api(d['rate_oid'], d['rating'], m.text)
    await msg.delete()
    
    if res and res.status_code in [200, 201]:
        await m.answer("✅ Rahmat! Sizning bahoyingiz biz uchun muhim.", reply_markup=get_main_menu())
    else: 
        await m.answer("❌ Xatolik yuz berdi, lekin bahoyingizni keyinroq yana urinib ko'rishingiz mumkin.", reply_markup=get_main_menu())
    await state.clear()

async def main():
    print("🚀 Bot ishga tushirildi! (To'xtatish uchun Ctrl+C)")
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Critical Error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⛔ Bot qo'lda to'xtatildi.")