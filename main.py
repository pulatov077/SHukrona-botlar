import asyncio
import os
import logging
import httpx
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    MenuButtonDefault,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

# .env yuklash
load_dotenv()

# --- KONFIGURATSIYA ---
BOT_TOKEN = os.getenv("BOT_TOKEN_ADMIN")
BACKEND_URL = os.getenv("BACKEND_URL")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- FSM (Holatlar) ---
class LoginStates(StatesGroup):
    waiting_for_password = State()
    authorized = State()

# --- BACKEND BILAN ISHLASH (HELPER FUNKSIYALAR) ---

async def get_pending_orders(admin_tg_id: int, limit: int = 5, offset: int = 0):
    """Kutilayotgan buyurtmalarni paginatsiya bilan olish"""
    url = f"{BACKEND_URL}/orders/admin/"
    params = {
        "status": "kutilmoqda",
        "limit": limit,
        "offset": offset
    }
    headers = {"X-Telegram-ID": str(admin_tg_id)}
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, headers=headers, timeout=10.0)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logger.error(f"Error fetching pending orders: {e}")
            return []

async def get_couriers_list(admin_tg_id: int):
    """Kuryerlar ro'yxatini olish"""
    url = f"{BACKEND_URL}/couriers/"
    headers = {"X-Telegram-ID": str(admin_tg_id)}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=10.0)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logger.error(f"Error fetching couriers: {e}")
            return []

async def assign_order_to_backend(order_id: int, courier_id: int, admin_tg_id: int):
    """Buyurtmani biriktirish"""
    url = f"{BACKEND_URL}/orders/{order_id}/assign/"
    headers = {"X-Telegram-ID": str(admin_tg_id)}
    payload = {"courier_id": int(courier_id)}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(url, json=payload, headers=headers, timeout=10.0)
            return response
        except Exception as e:
            logger.error(f"Assign error: {e}")
            return None

# --- KEYBOARDS ---

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 Biriktirilmagan buyurtmalar")]
        ],
        resize_keyboard=True
    )

def get_pagination_keyboard(offset: int, orders_count: int, limit: int = 5):
    buttons = []
    nav_row = []
    
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"pending_page_{offset - limit}"))
    
    if orders_count == limit: # Agar kelgan ma'lumot limitga teng bo'lsa, demak yana bo'lishi mumkin
        nav_row.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"pending_page_{offset + limit}"))
    
    if nav_row:
        buttons.append(nav_row)
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- BOT HANDLERS ---

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == LoginStates.authorized:
        await message.answer("Siz tizimga kirgansiz!", reply_markup=get_main_keyboard())
        return
    await message.answer("Xush kelibsiz! Admin parolini kiriting:")
    await state.set_state(LoginStates.waiting_for_password)

@dp.message(Command("stop"))
async def cmd_stop(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Tizimdan chiqdingiz.", reply_markup=ReplyKeyboardRemove())

@dp.message(LoginStates.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    password = message.text
    telegram_id = str(message.from_user.id)
    login_url = f"{BACKEND_URL}/admin/login/"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(login_url, json={"telegram_id": telegram_id, "password": password}, timeout=10.0)
            if response.status_code == 200:
                await state.set_state(LoginStates.authorized)
                await message.answer("Muvaffaqiyatli kirildi!", reply_markup=get_main_keyboard())
            else:
                await message.answer("Xato: Parol noto'g'ri.")
        except:
            await message.answer("Backend xatosi!")

# --- BUYURTMALARNI CHIQARISH (CARD FORMAT) ---

async def send_pending_orders(message_or_query, admin_id: int, offset: int = 0):
    orders = await get_pending_orders(admin_id, offset=offset)
    
    if not orders and offset == 0:
        text = "Hozircha biriktirilmagan buyurtmalar yo'q. ✨"
        if isinstance(message_or_query, Message):
            await message_or_query.answer(text)
        else:
            await message_or_query.message.edit_text(text)
        return

    # Agar bu yangi xabar bo'lsa
    if isinstance(message_or_query, Message):
        await message_or_query.answer("🔍 Biriktirilmagan buyurtmalar ro'yxati:")
    
    for o in orders:
        card = (
            f"📦 <b>Buyurtma #{o['id']}</b>\n"
            f"👤 Mijoz: {o.get('user_name', 'Noma\'lum')}\n"
            f"📞 Tel: {o.get('user_phone', '-')}\n"
            f"💰 Summa: {o.get('total_amount', 0):,} so'm\n"
            f"━━━━━━━━━━━━━━━"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚚 Kuryer biriktirish", callback_data=f"list_couriers_{o['id']}")]
        ])
        await bot.send_message(chat_id=admin_id, text=card, reply_markup=kb, parse_mode="HTML")

    # Paginatsiya tugmasi
    if len(orders) > 0:
        pag_kb = get_pagination_keyboard(offset, len(orders))
        if pag_kb.inline_keyboard:
            await bot.send_message(chat_id=admin_id, text="Boshqa buyurtmalar:", reply_markup=pag_kb)

@dp.message(F.text == "📦 Biriktirilmagan buyurtmalar", LoginStates.authorized)
async def handle_pending_request(message: Message):
    await send_pending_orders(message, message.from_user.id, offset=0)

@dp.callback_query(F.data.startswith("pending_page_"))
async def handle_pagination(callback: CallbackQuery):
    offset = int(callback.data.split("_")[-1])
    await callback.message.delete() # Eski paginatsiya xabarini o'chirish
    await send_pending_orders(callback, callback.from_user.id, offset=offset)
    await callback.answer()

# --- KURYER BIRIKTIRISH ---

@dp.callback_query(F.data.startswith("list_couriers_"))
async def handle_list_couriers(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_")[-1]
    couriers = await get_couriers_list(callback.from_user.id)
    
    if not couriers:
        await callback.answer("Bo'sh kuryerlar yo'q.", show_alert=True)
        return

    keyboard = []
    for c in couriers:
        btn_text = f"🛵 {c.get('name', 'Noma\'lum')} ({c.get('phone', '-')})"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"set_courier_{order_id}_{c['id']}")])
    
    keyboard.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_assign")])
    
    await callback.message.edit_text(
        text=f"📦 <b>#{order_id}</b> uchun kuryer:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("set_courier_"))
async def handle_set_courier(callback: CallbackQuery):
    parts = callback.data.split("_")
    order_id, courier_id = parts[2], parts[3]
    
    response = await assign_order_to_backend(order_id, courier_id, callback.from_user.id)
    
    if response and response.status_code in [200, 201, 204]:
        await callback.message.edit_text(f"✅ Buyurtma #{order_id} kuryerga berildi!")
    else:
        await callback.answer("Xatolik yuz berdi!", show_alert=True)

@dp.callback_query(F.data == "cancel_assign")
async def handle_cancel(callback: CallbackQuery):
    await callback.message.delete()

# --- MAIN ---
async def main():
    print("Admin Bot (Orders Mode) ishga tushmoqda...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass