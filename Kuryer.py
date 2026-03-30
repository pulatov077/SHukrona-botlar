import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple, Set
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.utils.markdown import html_decoration as hd
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    CallbackQuery,
    Message
)
from aiogram.fsm.storage.memory import MemoryStorage
import aiohttp
import logging
import sys
import re

# ============================================================================
# SOZLAMALAR VA LOGGER
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Kuryer")

API_BASE_URL = os.getenv("BACKEND_URL", "https://shukrona-backend-production-4169.up.railway.app")
BOT_TOKEN = "8372365010:AAHt8f69mdbHlcCY3yZP6rBvf36uMxcf9Dg"  # O'z tokeningiz bilan almashtiring

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN kiriting!")
    sys.exit(1)

# ============================================================================
# FSM HOLATLARI
# ============================================================================

class CourierStates(StatesGroup):
    main_menu = State()
    waiting_for_delivery_time = State()
    waiting_for_new_price = State()
    waiting_for_bonus_product = State()

# ============================================================================
# POLLING UCHUN GLOBAL O'ZGARUVCHILAR
# ============================================================================

active_couriers: Set[int] = set()
last_orders: Dict[int, Set[int]] = {}

# ============================================================================
# API CLIENT
# ============================================================================

class CourierClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Tuple[bool, Any]:
        try:
            url = f"{self.base_url}{endpoint}"
            timeout = aiohttp.ClientTimeout(total=30)

            headers = kwargs.pop('headers', {})
            headers.update({
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            })

            params = kwargs.pop('params', None)

            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=method,
                    url=url,
                    timeout=timeout,
                    headers=headers,
                    params=params,
                    **kwargs
                ) as response:

                    logger.info(f"📡 {method} {endpoint} - Status: {response.status}")

                    if response.status in [200, 201, 204]:
                        if response.status == 204:
                            return True, None
                        try:
                            data = await response.json()
                            return True, data
                        except:
                            text = await response.text()
                            return True, text
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ {method} {endpoint} - {response.status}: {error_text}")
                        return False, {"error": f"{response.status}: {error_text}"}

        except Exception as e:
            logger.error(f"❌ Network error: {e}")
            return False, {"error": str(e)}

    # ============ KURYER FUNKSIYALARI ============

    async def check_courier_exists(self, telegram_id: str) -> Tuple[bool, Optional[Dict]]:
        try:
            success, data = await self._make_request("GET", f"/couriers/check-messenger/{telegram_id}/")

            if success:
                if isinstance(data, dict):
                    if 'status' in data and data['status'] == 200:
                        return True, {
                            'exists': True,
                            'courier_name': data.get('courier_name', 'Kuryer'),
                            'message': data.get('message', 'Kuryer topildi')
                        }
                    elif 'detail' in data:
                        if 'Kuryer topildi' in data['detail']:
                            return True, {'exists': True, 'message': data['detail']}
                        elif 'Kuryer topilmadi' in data['detail']:
                            return True, {'exists': False, 'message': data['detail']}
                elif isinstance(data, str):
                    if 'Kuryer topildi' in data:
                        return True, {'exists': True, 'message': data}
                    elif 'Kuryer topilmadi' in data:
                        return True, {'exists': False, 'message': data}

                return True, {'exists': True, 'message': 'Kuryer mavjud'}

            return False, {'error': 'API bilan bog\'lanishda xatolik'}

        except Exception as e:
            logger.error(f"Kuryer tekshirishda xatolik: {e}")
            return False, {'error': str(e)}

    async def get_courier_report(self, telegram_id: str, days: int) -> Tuple[bool, Optional[Dict]]:
        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            endpoint = f"/couriers/me/history/?telegram_id={telegram_id}&start_date={start_date}&end_date={end_date}"
            success, data = await self._make_request("GET", endpoint)

            if success and isinstance(data, dict):
                return True, data
            return False, {"error": "Hisobot olinmadi"}

        except Exception as e:
            logger.error(f"Hisobot olishda xatolik: {e}")
            return False, {"error": str(e)}

    # ============ BUYURTMALAR FUNKSIYALARI ============

    async def get_courier_orders(self, telegram_id: str, status: str = None) -> Tuple[bool, Optional[List]]:
        try:
            success, data = await self._make_request("GET", f"/orders/courier/?telegram_id={telegram_id}")

            if success:
                if isinstance(data, list):
                    if status:
                        filtered_data = [order for order in data if order.get('status') == status]
                        return True, filtered_data
                    return True, data
                return True, []
            return False, None

        except Exception as e:
            logger.error(f"❌ Buyurtmalarni olishda xatolik: {str(e)}")
            return False, None

    async def get_order_detail(self, order_id: int) -> Tuple[bool, Optional[Dict]]:
        try:
            success, data = await self._make_request("GET", f"/orders/{order_id}/")

            if success:
                return True, data
            return False, {"error": "Buyurtma topilmadi"}

        except Exception as e:
            logger.error(f"❌ Buyurtma ma'lumotlarini olishda xatolik: {str(e)}")
            return False, {"error": str(e)}

    # ============ MIJOZ STATISTIKASI ============

    async def get_user_order_stats(self, telegram_id: str, start_date: str, end_date: str) -> Tuple[bool, Optional[Dict]]:
        try:
            endpoint = f"/users/stats/orders/by-telegram/{telegram_id}/"
            params = {"start_date": start_date, "end_date": end_date}
            success, data = await self._make_request("GET", endpoint, params=params)

            if success:
                return True, data
            return False, {"error": "Statistika olinmadi"}

        except Exception as e:
            logger.error(f"❌ Mijoz statistikasini olishda xatolik: {str(e)}")
            return False, {"error": str(e)}

    async def accept_order(self, order_id: int, telegram_id: str, delivery_time: str = "30 daqiqa") -> Tuple[bool, Optional[Dict]]:
        try:
            data = {
                "delivery_time": delivery_time,
                "courier_telegram_id": str(telegram_id)
            }

            success, result = await self._make_request("PATCH", f"/orders/{order_id}/accept/", json=data)

            if success:
                return True, result
            return False, {"error": "Qabul qilishda xatolik"}

        except Exception as e:
            logger.error(f"❌ Buyurtma qabul qilishda xatolik: {str(e)}")
            return False, {"error": str(e)}

    async def lock_order_price(self, order_id: int, telegram_id: str) -> Tuple[bool, Optional[Dict]]:
        try:
            data = {"courier_telegram_id": str(telegram_id)}
            success, result = await self._make_request("PATCH", f"/orders/{order_id}/lock-price/", json=data)

            if success:
                return True, result
            return False, {"error": "Bloklashda xatolik"}

        except Exception as e:
            logger.error(f"❌ Buyurtma narxini bloklashda xatolik: {str(e)}")
            return False, {"error": str(e)}

    async def update_order_price(self, order_id: int, telegram_id: str, new_price: float) -> Tuple[bool, Optional[Dict]]:
        try:
            data = {
                "courier_telegram_id": str(telegram_id),
                "new_price": new_price
            }

            success, result = await self._make_request("PATCH", f"/orders/{order_id}/update-price/", json=data)

            if success:
                return True, result
            return False, {"error": "Narxni o'zgartirishda xatolik"}

        except Exception as e:
            logger.error(f"❌ Buyurtma narxini o'zgartirishda xatolik: {str(e)}")
            return False, {"error": str(e)}

    async def deliver_order(self, order_id: int, telegram_id: str) -> Tuple[bool, Optional[Dict]]:
        try:
            data = {"courier_telegram_id": str(telegram_id)}
            success, result = await self._make_request("PATCH", f"/orders/{order_id}/deliver/", json=data)

            if success:
                return True, result
            return False, {"error": "Yetkazishda xatolik"}

        except Exception as e:
            logger.error(f"❌ Buyurtma yetkazishda xatolik: {str(e)}")
            return False, {"error": str(e)}

    async def add_bonus_to_order(self, order_id: int, telegram_id: str, product_id: int, quantity: int = 1) -> Tuple[bool, Optional[Dict]]:
        try:
            data = {
                "courier_telegram_id": str(telegram_id),
                "items": [{"product_id": product_id, "quantity": quantity}]
            }

            success, result = await self._make_request("POST", f"/orders/{order_id}/bonus/", json=data)

            if success:
                return True, result
            return False, {"error": "Bonus qo'shishda xatolik"}

        except Exception as e:
            logger.error(f"❌ Bonus qo'shishda xatolik: {str(e)}")
            return False, {"error": str(e)}

    async def get_products_list(self) -> Tuple[bool, Optional[List]]:
        try:
            success, data = await self._make_request("GET", "/products/")

            if success and isinstance(data, list):
                return True, data
            return False, None

        except Exception as e:
            logger.error(f"❌ Mahsulotlarni olishda xatolik: {str(e)}")
            return False, None

# ============================================================================
# KLAVIATURALAR
# ============================================================================

def get_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="📦 Buyurtmalar")],
        [KeyboardButton(text="📋 Zakazlarim tarixi"), KeyboardButton(text="💰 Balans / Hisobot")],
        [KeyboardButton(text="⭐ Mening reytingim"), KeyboardButton(text="🔄 Yangilash")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_back_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Orqaga")]], resize_keyboard=True)

def get_balance_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="💰 Balansim")],
        [KeyboardButton(text="📊 Kunlik hisobot")],
        [KeyboardButton(text="📈 Haftalik hisobot")],
        [KeyboardButton(text="📉 Oylik hisobot")],
        [KeyboardButton(text="⬅️ Orqaga")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_orders_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="🚚 Kutilmoqda buyurtmalar")],
        [KeyboardButton(text="⚡ Faol buyurtmalar")],
        [KeyboardButton(text="✅ Yetkazilganlar")],
        [KeyboardButton(text="❌ Bekor qilinganlar")],
        [KeyboardButton(text="⬅️ Orqaga")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_order_actions_keyboard(order_id: int, order_status: str, is_price_locked: bool = False) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    if order_status == "kutilmoqda":
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"accept_order_{order_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_order_{order_id}")
        ])
    elif order_status in ["qabul_qilindi", "yetkazilmoqda", "kuryerda"]:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🚚 Yetkazish", callback_data=f"deliver_order_{order_id}")
        ])

    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="📋 Batafsil", callback_data=f"detail_order_{order_id}")
    ])

    return keyboard

def get_delivery_actions_keyboard(order_id: int, is_price_locked: bool = False, order_status: str = "yetkazilmoqda") -> InlineKeyboardMarkup:
    buttons = []
    if not is_price_locked and order_status in ["kuryerda", "yetkazilmoqda"]:
        buttons.append([
            InlineKeyboardButton(text="💰 Narxni o'zgartirish", callback_data=f"update_price_{order_id}"),
            InlineKeyboardButton(text="🎁 Bonus qo'shish", callback_data=f"add_bonus_{order_id}")
        ])
        buttons.append([
            InlineKeyboardButton(text="🔒 Narxni bloklash", callback_data=f"lock_price_{order_id}")
        ])
    buttons.append([
        InlineKeyboardButton(text="✅ Yakunlash", callback_data=f"confirm_delivery_{order_id}"),
        InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"back_to_order_{order_id}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_confirmation_keyboard(action: str, order_id: int, data: Any = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ha", callback_data=f"confirm_{action}_{order_id}_{data if data else ''}"),
            InlineKeyboardButton(text="❌ Yo'q", callback_data=f"cancel_{action}_{order_id}")
        ]
    ])

def get_products_inline_keyboard(products: List[Dict], order_id: int) -> InlineKeyboardMarkup:
    """Mahsulotlar ro'yxatini inline tugmalar shaklida qaytaradi"""
    keyboard = []
    row = []
    for product in products:
        product_id = product.get('id')
        product_name = product.get('name', 'Noma\'lum')
        btn = InlineKeyboardButton(
            text=f"{product_name}",
            callback_data=f"select_bonus_product_{order_id}_{product_id}"
        )
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"cancel_bonus_{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ============================================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================================

def format_courier_welcome(check_data: Dict) -> str:
    try:
        courier_name = check_data.get('courier_name', 'Kuryer')
        return f"🚚 {hd.bold('KURYER PANELIGA XUSH KELIBSIZ!')}\n\n👤 {hd.bold('Ism:')} {courier_name}"
    except Exception as e:
        logger.error(f"Xush kelibsiz xabarini formatlashda xatolik: {e}")
        return f"🚚 {hd.bold('KURYER PANELIGA XUSH KELIBSIZ!')}"

def format_order_detail(order: Dict) -> str:
    try:
        order_id = order.get('id', 0)
        status = order.get('status', 'Noma\'lum')
        total_amount = order.get('total_amount', 0)
        customer_name = order.get('user_name', 'Noma\'lum mijoz')
        customer_phone = order.get('user_phone', 'Noma\'lum')
        user_type = order.get('user_type', 'standard')
        delivery_time = order.get('delivery_time', 'Belgilanmagan')
        user_address = order.get('user_address', 'Noma\'lum')
        created_at = order.get('created_at', 'Noma\'lum')
        is_price_locked = order.get('is_price_locked', False)
        user_telegram_id = order.get('user_telegram_id', None)

        user_type_display = {
            'standard': '👤 Standart',
            'maxsus': '👑 Maxsus',
        }.get(user_type, f'👤 {user_type.capitalize()}')

        status_colors = {
            'kutilmoqda': '🟡',
            'qabul_qilindi': '🟢',
            'yetkazilmoqda': '🔵',
            'yetkazildi': '✅',
            'bekor_qilindi': '❌',
            'kuryerda': '🚚'
        }

        status_icon = status_colors.get(status, '⚪')
        price_lock_status = "🔒 BLOKLANGAN" if is_price_locked else "🔓 BLOKLANGANMAS"

        formatted = (
            f"📦 {hd.bold(f'BUYURTMA #{order_id}')}\n\n"
            f"👤 {hd.bold('Mijoz:')} {customer_name}\n"
            f"📞 {hd.bold('Telefon:')} {customer_phone}\n"
            f"📍 {hd.bold('Manzil:')} {user_address}\n"
            f"👑 {hd.bold('Mijoz turi:')} {user_type_display}\n"
            f"💰 {hd.bold('Summa:')} {total_amount:,} so'm\n"
            f"🔐 {hd.bold('Narx holati:')} {price_lock_status}\n"
            f"⏰ {hd.bold('Yetkazish vaqti:')} {delivery_time}\n"
            f"📊 {hd.bold('Holat:')} {status_icon} {status.capitalize()}\n"
            f"📅 {hd.bold('Yaratilgan:')} {created_at}\n\n"
        )

        items = order.get('items', [])
        if items:
            formatted += f"🛍 {hd.bold('Mahsulotlar:')}\n"
            for item in items:
                product_name = item.get('product_name', 'Noma\'lum mahsulot')
                quantity = item.get('quantity', 1)
                price = item.get('price', 0)
                is_bonus = item.get('is_bonus', False)
                bonus_mark = "🎁 " if is_bonus else "  "
                formatted += f"  {bonus_mark}• {product_name} - {quantity} x {price:,} so'm\n"

        if user_telegram_id:
            formatted += f"\n🆔 {hd.bold('Mijoz Telegram ID:')} {user_telegram_id}"

        return formatted

    except Exception as e:
        logger.error(f"Buyurtma ma'lumotlarini formatlashda xatolik: {e}")
        return f"❌ Buyurtma ma'lumotlarini formatlashda xatolik"

def format_user_stats(stats: Dict) -> str:
    try:
        orders_count = stats.get('orders_count', 0)
        items_count = stats.get('items_count', 0)
        return (f"\n📊 {hd.bold('MIJOZ STATISTIKASI (SO\'NGI 30 KUN):')}\n"
                f"├ 📦 {hd.bold('Buyurtmalar soni:')} {orders_count} ta\n"
                f"└ 🛍 {hd.bold('Mahsulotlar soni:')} {items_count} ta")
    except Exception as e:
        logger.error(f"Mijoz statistikasini formatlashda xatolik: {e}")
        return ""

def format_report(report_data: Dict, report_type: str) -> str:
    try:
        courier_name = report_data.get('courier_name', 'Kuryer')
        total_deliveries = report_data.get('total_delivered_orders', 0)
        total_items_sold = report_data.get('total_items_sold', 0)
        total_money = report_data.get('total_money_collected', 0)
        rating = report_data.get('average_rating', 0)

        if report_type == "daily":
            date_str = datetime.now().strftime('%d.%m.%Y')
            title = "KUNLIK HISOBOT"
            period = f"Sana: {date_str}"
        elif report_type == "weekly":
            start_date = (datetime.now() - timedelta(days=7)).strftime('%d.%m.%Y')
            end_date = datetime.now().strftime('%d.%m.%Y')
            title = "HAFTALIK HISOBOT"
            period = f"Davr: {start_date} - {end_date}"
        elif report_type == "monthly":
            month_name = datetime.now().strftime('%B %Y')
            title = "OYLIK HISOBOT"
            period = f"Oy: {month_name}"
        else:
            title = "HISOBOT"
            period = ""

        try:
            rating_float = float(rating)
            rating_text = f"{rating_float:.1f}/5.0"
        except:
            rating_text = "0.0/5.0"

        return (f"📊 {hd.bold(title)}\n\n"
                f"👤 {hd.bold('Kuryer:')} {courier_name}\n"
                f"📅 {hd.bold(period)}\n\n"
                f"📈 {hd.bold('KO\'RSATKICHLAR:')}\n"
                f"├ 📦 Yetkazilgan buyurtmalar: {total_deliveries} ta\n"
                f"├ 🛍 Sotilgan mahsulotlar(bachok): {total_items_sold} ta\n"
                f"├ 💰 Jami daromad: {total_money:,.0f} so'm\n"
                f"└ ⭐ Mening reytingim: {rating_text}")

    except Exception as e:
        logger.error(f"Hisobot formatlashda xatolik: {e}")
        return f"❌ Hisobot formatlashda xatolik"

def format_rating_info(report_data: Dict) -> str:
    try:
        courier_name = report_data.get('courier_name', 'Kuryer')
        average_rating = report_data.get('average_rating', 0)
        total_delivered_orders = report_data.get('total_delivered_orders', 0)
        total_items_sold = report_data.get('total_items_sold', 0)
        total_money = report_data.get('total_money_collected', 0)

        try:
            rating_float = float(average_rating)
            stars = '⭐' * int(rating_float) + '☆' * (5 - int(rating_float))
            rating_text = f"{stars}\n{rating_float:.1f}/5.0"
        except:
            stars = '☆☆☆☆☆'
            rating_text = "0.0/5.0"

        return (f"⭐ {hd.bold('MENING REYTINGIM')}\n\n"
                f"👤 {hd.bold('Kuryer:')} {courier_name}\n"
                f"📊 {hd.bold('Umumiy reyting:')}\n"
                f"   {rating_text}\n\n"
                f"📦 {hd.bold('Yetkazilgan buyurtmalar:')} {total_delivered_orders} ta\n"
                f"🛍 {hd.bold('Sotilgan mahsulotlar(bachok):')} {total_items_sold} ta\n"
                f"💰 {hd.bold('Jami daromad:')} {total_money:,.0f} so'm")

    except Exception as e:
        logger.error(f"Reyting ma'lumotlarini formatlashda xatolik: {e}")
        return f"⭐ {hd.bold('MENING REYTINGIM')}\n\nMa'lumotlar yuklanmadi."

# ============================================================================
# POLLING FUNKSIYALARI
# ============================================================================

async def check_new_orders_for_courier(courier_id: int):
    """Berilgan kuryer uchun yangi buyurtmalarni tekshiradi va xabar yuboradi"""
    global last_orders

    success, orders = await client.get_courier_orders(str(courier_id))
    if not success or not orders:
        return

    current_ids = {o['id'] for o in orders}
    old_ids = last_orders.get(courier_id, set())
    new_ids = current_ids - old_ids

    if new_ids:
        last_orders[courier_id] = current_ids
        for o in orders:
            if o['id'] in new_ids:
                order_text = format_order_detail(o)
                status = o.get('status', '')
                is_price_locked = o.get('is_price_locked', False)
                keyboard = get_order_actions_keyboard(o['id'], status, is_price_locked)
                msg = f"🆕 <b>YANGI BUYURTMA BIRIKTIRILDI!</b>\n\n{order_text}"
                await bot.send_message(courier_id, msg, parse_mode="HTML", reply_markup=keyboard)
    else:
        last_orders[courier_id] = current_ids

async def polling_task():
    while True:
        try:
            for courier_id in list(active_couriers):
                await check_new_orders_for_courier(courier_id)
        except Exception as e:
            logger.error(f"Polling xatosi: {e}")
        await asyncio.sleep(30)

# ============================================================================
# ROUTER VA HANDLERLAR
# ============================================================================

courier_router = Router()
client = CourierClient(API_BASE_URL)

# ============ START HANDLER ============

@courier_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    int_id = message.from_user.id

    try:
        check_success, check_data = await client.check_courier_exists(user_id)

        if check_success:
            if check_data.get('exists'):
                active_couriers.add(int_id)
                success, orders = await client.get_courier_orders(user_id)
                if success and orders:
                    last_orders[int_id] = {o['id'] for o in orders}
                else:
                    last_orders[int_id] = set()

                welcome_message = format_courier_welcome(check_data)
                await message.answer(welcome_message, parse_mode="HTML", reply_markup=get_main_keyboard())
                await state.set_state(CourierStates.main_menu)
                await state.update_data(courier_info=check_data)
            else:
                error_message = (
                    f"⚠️ {hd.bold('KUYER RO\'YXATIDA YO\'QSIZ')}\n\n"
                    f"Uzr, siz kuryerlar ro'yxatida yo'qsiz.\n\n"
                    f"Agar kuryer bo'lishni istasangiz, admin bilan bog'laning."
                )
                await message.answer(error_message, parse_mode="HTML")
                await state.clear()
        else:
            error_message = (
                f"❌ {hd.bold('XATOLIK')}\n\n"
                f"Server bilan bog'lanishda xatolik yuz berdi.\n"
                f"Xato: {check_data.get('error', 'Noma\'lum xato')}"
            )
            await message.answer(error_message, parse_mode="HTML")
            await state.clear()
    except Exception as e:
        error_message = (
            f"❌ {hd.bold('XATOLIK')}\n\n"
            f"Server bilan bog'lanishda xatolik yuz berdi.\n"
            f"Iltimos, keyinroq qayta urinib ko'ring."
        )
        await message.answer(error_message, parse_mode="HTML")
        await state.clear()

# ============ YANGI BUYURTMA BIRIKTIRILGANDA XABAR ============
@courier_router.message(Command("new_order"))
async def cmd_new_order(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Buyurtma ID siz berilmadi.\nIshlatish: /new_order 123")
        return
    try:
        order_id = int(args[1])
    except ValueError:
        await message.answer("❌ Noto'g'ri buyurtma ID. Raqam kiriting.")
        return

    success, order_detail = await client.get_order_detail(order_id)
    if not success:
        await message.answer("❌ Buyurtma topilmadi yoki API xatosi.")
        return

    order_text = format_order_detail(order_detail)
    status = order_detail.get('status', '')
    is_price_locked = order_detail.get('is_price_locked', False)
    keyboard = get_order_actions_keyboard(order_id, status, is_price_locked)
    await message.answer(order_text, parse_mode="HTML", reply_markup=keyboard)

# ============ BUYURTMALAR BO'LIMI ============

@courier_router.message(F.text == "📦 Buyurtmalar")
async def handle_orders_menu(message: types.Message):
    info_message = (
        f"📦 {hd.bold('BUYURTMALAR BO\'LIMI')}\n\n"
        f"ℹ️ Har bir buyurtma uchun siz quyidagi amallarni bajarishingiz mumkin:\n"
        f"• ✅ Qabul qilish (kutilmoqda holatda)\n"
        f"• 🚚 Yetkazish (faol holatda)\n"
        f"• 💰 Narxni o'zgartirish\n"
        f"• 🔒 Narxni bloklash\n"
        f"• 📋 Batafsil ma'lumot"
    )
    await message.answer(info_message, parse_mode="HTML", reply_markup=get_orders_keyboard())

async def show_orders_by_status(message: types.Message, status: str, status_name: str):
    user_id = str(message.from_user.id)

    success, orders = await client.get_courier_orders(user_id, status=status)

    if success and orders:
        await message.answer(f"📦 {hd.bold(f'{status_name.upper()} BUYURTMALAR')} - {len(orders)} ta", parse_mode="HTML")

        for order in orders:
            order_id = order.get('id', 0)
            customer_name = order.get('user_name', 'Noma\'lum mijoz')
            total_amount = order.get('total_amount', 0)
            delivery_time = order.get('delivery_time', 'Belgilanmagan')
            is_price_locked = order.get('is_price_locked', False)

            order_text = (
                f"📦 {hd.bold(f'Buyurtma #{order_id}')}\n"
                f"👤 {hd.bold('Mijoz:')} {customer_name}\n"
                f"💰 {hd.bold('Summa:')} {total_amount:,} so'm\n"
                f"⏰ {hd.bold('Vaqt:')} {delivery_time}\n"
                f"―――――――――――――――――――――"
            )

            keyboard = get_order_actions_keyboard(order_id, status, is_price_locked)
            await message.answer(order_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.answer(f"📭 Hozirda {status_name} buyurtmalar mavjud emas.", reply_markup=get_orders_keyboard())

@courier_router.message(F.text == "🚚 Kutilmoqda buyurtmalar")
async def handle_pending_orders(message: types.Message):
    await show_orders_by_status(message, "kutilmoqda", "Kutilmoqda")

@courier_router.message(F.text == "⚡ Faol buyurtmalar")
async def handle_active_orders(message: types.Message):
    user_id = str(message.from_user.id)

    success, orders = await client.get_courier_orders(user_id)

    if success and orders:
        active_orders = []
        for order in orders:
            status = order.get('status', '')
            if status in ['qabul_qilindi', 'yetkazilmoqda', 'kuryerda']:
                active_orders.append(order)

        if active_orders:
            await message.answer(f"📦 {hd.bold('FAOL BUYURTMALAR')} - {len(active_orders)} ta", parse_mode="HTML")

            for order in active_orders:
                order_id = order.get('id', 0)
                customer_name = order.get('user_name', 'Noma\'lum mijoz')
                total_amount = order.get('total_amount', 0)
                status = order.get('status', '')
                is_price_locked = order.get('is_price_locked', False)

                order_text = (
                    f"📦 {hd.bold(f'Buyurtma #{order_id}')}\n"
                    f"👤 {hd.bold('Mijoz:')} {customer_name}\n"
                    f"💰 {hd.bold('Summa:')} {total_amount:,} so'm\n"
                    f"📊 {hd.bold('Holat:')} {status.capitalize()}\n"
                    f"―――――――――――――――――――――"
                )

                keyboard = get_order_actions_keyboard(order_id, status, is_price_locked)
                await message.answer(order_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await message.answer("📭 Hozirda faol buyurtmalar mavjud emas.", reply_markup=get_orders_keyboard())
    else:
        await message.answer("❌ Buyurtmalar yuklanmadi.", reply_markup=get_orders_keyboard())

@courier_router.message(F.text == "✅ Yetkazilganlar")
async def handle_delivered_orders(message: types.Message):
    await show_orders_by_status(message, "yetkazildi", "Yetkazilgan")

@courier_router.message(F.text == "❌ Bekor qilinganlar")
async def handle_cancelled_orders(message: types.Message):
    await show_orders_by_status(message, "bekor_qilindi", "Bekor qilingan")

# ============ BUYURTMA QABUL QILISH ============

@courier_router.callback_query(F.data.startswith("accept_order_"))
async def handle_accept_order(callback_query: types.CallbackQuery, state: FSMContext):
    order_id = int(callback_query.data.replace("accept_order_", ""))
    user_id = str(callback_query.from_user.id)

    await callback_query.answer()

    # Xabarni tahrirlab, yetkazish vaqtini so'raymiz
    await callback_query.message.edit_text(
        f"⏳ {hd.bold('YETKAZISH VAQTINI KIRITING')}\n\n"
        f"Buyurtma: #{order_id}\n\n"
        f"Iltimos, yetkazish vaqtini kiriting (masalan: '30 daqiqa', '1 soat'):",
        parse_mode="HTML"
    )

    await state.set_state(CourierStates.waiting_for_delivery_time)
    await state.update_data(order_id=order_id, user_id=user_id, message_id=callback_query.message.message_id)

@courier_router.message(CourierStates.waiting_for_delivery_time)
async def handle_delivery_time_input(message: types.Message, state: FSMContext):
    delivery_time = message.text
    state_data = await state.get_data()

    order_id = state_data.get('order_id')
    user_id = state_data.get('user_id')
    msg_id = state_data.get('message_id')

    if not order_id or not user_id:
        await message.answer("❌ Xatolik: Ma'lumotlar topilmadi.")
        await state.clear()
        return

    # API ga so'rov
    success, result = await client.accept_order(order_id, user_id, delivery_time)

    # Foydalanuvchi yozgan xabarni o'chirib tashlaymiz (chatni toza saqlash)
    await message.delete()

    if success:
        # Yangilangan buyurtma ma'lumotlarini olish
        order_success, order_detail = await client.get_order_detail(order_id)
        if order_success:
            order_text = format_order_detail(order_detail)
            status = order_detail.get('status', '')
            is_price_locked = order_detail.get('is_price_locked', False)
            keyboard = get_order_actions_keyboard(order_id, status, is_price_locked)
            # Xabarni tahrirlab, qabul qilingan buyurtmani ko'rsatamiz
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text=order_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text="❌ Buyurtma qabul qilindi, ammo ma'lumotlarni yuklab bo'lmadi.",
                parse_mode="HTML"
            )
    else:
        error_details = result.get('error', 'Noma\'lum xato') if isinstance(result, dict) else str(result)
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg_id,
            text=f"❌ {hd.bold('BUYURTMA QABUL QILINMADI')}\n\nXato: {error_details}",
            parse_mode="HTML"
        )

    await state.clear()

@courier_router.callback_query(F.data.startswith("reject_order_"))
async def handle_reject_order(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await callback_query.message.edit_text(
        f"ℹ️ {hd.bold('RAD ETISH')}\n\n"
        f"Hozircha buyurtmani rad etish funksiyasi mavjud emas.",
        parse_mode="HTML"
    )

# ============ YETKAZISH AMALLARI ============

@courier_router.callback_query(F.data.startswith("deliver_order_"))
async def handle_deliver_order(callback_query: types.CallbackQuery, state: FSMContext):
    order_id = int(callback_query.data.replace("deliver_order_", ""))

    await callback_query.answer()

    success, order_detail = await client.get_order_detail(order_id)

    if not success:
        await callback_query.message.edit_text("❌ Buyurtma ma'lumotlari olinmadi.", parse_mode="HTML")
        return

    is_price_locked = order_detail.get('is_price_locked', False)
    order_status = order_detail.get('status', '')

    # Xabarni tahrirlab, yetkazish amallari menyusini ko'rsatamiz
    await callback_query.message.edit_text(
        f"🔄 {hd.bold('KEYINGI AMALNI TANLANG')}\n\n"
        f"📦 Buyurtma: #{order_id}\n"
        f"📊 Holat: {order_status.capitalize()}",
        parse_mode="HTML",
        reply_markup=get_delivery_actions_keyboard(order_id, is_price_locked, order_status)
    )

    await state.update_data(order_id=order_id, message_id=callback_query.message.message_id)

# ============ NARXNI O'ZGARTIRISH ============

@courier_router.callback_query(F.data.startswith("update_price_"))
async def handle_update_price(callback_query: types.CallbackQuery, state: FSMContext):
    order_id = int(callback_query.data.replace("update_price_", ""))
    user_id = str(callback_query.from_user.id)

    await callback_query.answer()

    success, order_detail = await client.get_order_detail(order_id)

    if success:
        current_price = order_detail.get('total_amount', 0)

        await callback_query.message.edit_text(
            f"💰 {hd.bold('NARXNI O\'ZGARTIRISH')}\n\n"
            f"📦 Buyurtma: #{order_id}\n"
            f"💵 Joriy narx: {current_price:,} so'm\n\n"
            f"Iltimos, yangi narxni kiriting (so'mda):",
            parse_mode="HTML"
        )

        await state.set_state(CourierStates.waiting_for_new_price)
        await state.update_data(order_id=order_id, user_id=user_id, current_price=current_price,
                                message_id=callback_query.message.message_id)
    else:
        error_details = order_detail.get('error', 'Noma\'lum xato') if isinstance(order_detail, dict) else str(order_detail)
        await callback_query.message.edit_text(f"❌ Xato: {error_details}", parse_mode="HTML")

@courier_router.message(CourierStates.waiting_for_new_price)
async def handle_new_price_input(message: types.Message, state: FSMContext):
    try:
        new_price = float(message.text)
        state_data = await state.get_data()

        order_id = state_data.get('order_id')
        user_id = state_data.get('user_id')
        current_price = state_data.get('current_price', 0)
        msg_id = state_data.get('message_id')

        if new_price <= 0:
            await message.answer("❌ Narx 0 dan katta bo'lishi kerak.")
            return

        await message.delete()

        bot = message.bot
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg_id,
            text=(
                f"⚠️ {hd.bold('NARXNI O\'ZGARTIRISH')}\n\n"
                f"📦 Buyurtma: #{order_id}\n"
                f"💵 Oldingi narx: {current_price:,} so'm\n"
                f"💰 Yangi narx: {new_price:,} so'm\n\n"
                f"Haqiqatan ham narxni o'zgartirmoqchimisiz?"
            ),
            parse_mode="HTML",
            reply_markup=get_confirmation_keyboard("update_price", order_id, new_price)
        )

        await state.clear()

    except ValueError:
        await message.answer("❌ Iltimos, to'g'ri raqam kiriting.")

# ============ NARXNI BLOKLASH ============

@courier_router.callback_query(F.data.startswith("lock_price_"))
async def handle_lock_price(callback_query: types.CallbackQuery):
    order_id = int(callback_query.data.replace("lock_price_", ""))

    await callback_query.answer()

    await callback_query.message.edit_text(
        f"⚠️ {hd.bold('NARXNI BLOKLASH')}\n\n"
        f"📦 Buyurtma: #{order_id}\n\n"
        f"Buyurtma narxini bloklamoqchimisiz?",
        parse_mode="HTML",
        reply_markup=get_confirmation_keyboard("lock_price", order_id)
    )

# ============ BONUS QO'SHISH ============

@courier_router.callback_query(F.data.startswith("add_bonus_"))
async def handle_add_bonus(callback_query: types.CallbackQuery, state: FSMContext):
    order_id = int(callback_query.data.replace("add_bonus_", ""))
    user_id = str(callback_query.from_user.id)

    await callback_query.answer()

    success, order_detail = await client.get_order_detail(order_id)

    if not success:
        await callback_query.message.edit_text("❌ Buyurtma ma'lumotlari olinmadi.", parse_mode="HTML")
        return

    order_status = order_detail.get('status', '')

    if order_status != 'kuryerda':
        await callback_query.message.edit_text(
            f"❌ {hd.bold('BONUS QO\'SHISH MUMMKIN EMAS')}\n\n"
            f"Faqat 'kuryerda' holatidagi buyurtmalarga bonus qo'shish mumkin.",
            parse_mode="HTML"
        )
        return

    success, products = await client.get_products_list()

    if success and products:
        keyboard = get_products_inline_keyboard(products, order_id)
        await callback_query.message.edit_text(
            f"🎁 {hd.bold('BONUS MAHSULOT TANLANG')}\n\n"
            f"📦 Buyurtma: #{order_id}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await state.update_data(order_id=order_id, user_id=user_id, message_id=callback_query.message.message_id)
    else:
        await callback_query.message.edit_text(
            "❌ Mahsulotlar ro'yxati mavjud emas.",
            parse_mode="HTML"
        )

@courier_router.callback_query(F.data.startswith("select_bonus_product_"))
async def handle_select_bonus_product(callback_query: types.CallbackQuery, state: FSMContext):
    parts = callback_query.data.split("_")
    order_id = int(parts[3])
    product_id = int(parts[4])

    await callback_query.answer()

    success, products = await client.get_products_list()
    selected_product = None
    if success:
        for p in products:
            if p.get('id') == product_id:
                selected_product = p
                break

    if not selected_product:
        await callback_query.message.edit_text("❌ Mahsulot topilmadi.", parse_mode="HTML")
        return

    product_name = selected_product.get('name', 'Noma\'lum')
    product_price = selected_product.get('sell_price', 0)

    await callback_query.message.edit_text(
        f"⚠️ {hd.bold('BONUS MAHSULOT QO\'SHISH')}\n\n"
        f"📦 Buyurtma: #{order_id}\n"
        f"🎁 Mahsulot: {product_name}\n"
        f"💰 Asl narxi: {product_price:,} so'm\n\n"
        f"Haqiqatan ham bonus mahsulot qo'shmoqchimisiz?",
        parse_mode="HTML",
        reply_markup=get_confirmation_keyboard("add_bonus", order_id, product_id)
    )

@courier_router.callback_query(F.data.startswith("cancel_bonus_"))
async def handle_cancel_bonus(callback_query: types.CallbackQuery, state: FSMContext):
    order_id = int(callback_query.data.replace("cancel_bonus_", ""))
    await callback_query.answer()

    success, order_detail = await client.get_order_detail(order_id)
    if success:
        is_price_locked = order_detail.get('is_price_locked', False)
        order_status = order_detail.get('status', '')
        await callback_query.message.edit_text(
            f"🔄 {hd.bold('KEYINGI AMALNI TANLANG')}\n\n"
            f"📦 Buyurtma: #{order_id}\n"
            f"📊 Holat: {order_status.capitalize()}",
            parse_mode="HTML",
            reply_markup=get_delivery_actions_keyboard(order_id, is_price_locked, order_status)
        )
    else:
        await callback_query.message.edit_text("❌ Xatolik yuz berdi.", parse_mode="HTML")

# ============ TASDIQLASH HANDLERLARI ============

async def show_delivery_menu_after_action(callback_query: CallbackQuery, order_id: int, success_message: str):
    success, order_detail = await client.get_order_detail(order_id)
    if success:
        is_price_locked = order_detail.get('is_price_locked', False)
        order_status = order_detail.get('status', '')
        text = (
            f"✅ {success_message}\n\n"
            f"🔄 {hd.bold('KEYINGI AMALNI TANLANG')}\n\n"
            f"📦 Buyurtma: #{order_id}\n"
            f"📊 Holat: {order_status.capitalize()}"
        )
        await callback_query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=get_delivery_actions_keyboard(order_id, is_price_locked, order_status)
        )
    else:
        await callback_query.message.edit_text("❌ Buyurtma ma'lumotlari olinmadi.", parse_mode="HTML")

@courier_router.callback_query(F.data.startswith("confirm_update_price_"))
async def handle_confirm_update_price(callback_query: types.CallbackQuery):
    data_parts = callback_query.data.split("_")
    order_id = int(data_parts[3])
    new_price = float(data_parts[4])
    user_id = str(callback_query.from_user.id)

    await callback_query.answer()
    await callback_query.message.edit_text(f"⏳ Buyurtma #{order_id} narxi o'zgartirilmoqda...")

    success, result = await client.update_order_price(order_id, user_id, new_price)

    if success:
        await show_delivery_menu_after_action(
            callback_query,
            order_id,
            f"Narx muvaffaqiyatli o'zgartirildi! Yangi narx: {new_price:,} so'm"
        )
    else:
        error_details = result.get('error', 'Noma\'lum xato') if isinstance(result, dict) else str(result)
        await callback_query.message.edit_text(f"❌ Xato: {error_details}", parse_mode="HTML")

@courier_router.callback_query(F.data.startswith("confirm_add_bonus_"))
async def handle_confirm_add_bonus(callback_query: types.CallbackQuery):
    data_parts = callback_query.data.split("_")
    order_id = int(data_parts[3])
    product_id = int(data_parts[4])
    user_id = str(callback_query.from_user.id)

    await callback_query.answer()
    await callback_query.message.edit_text(f"⏳ Buyurtma #{order_id} ga bonus mahsulot qo'shilmoqda...")

    success, result = await client.add_bonus_to_order(order_id, user_id, product_id)

    if success:
        await show_delivery_menu_after_action(
            callback_query,
            order_id,
            "Bonus mahsulot muvaffaqiyatli qo'shildi!"
        )
    else:
        error_details = result.get('error', 'Noma\'lum xato') if isinstance(result, dict) else str(result)
        await callback_query.message.edit_text(f"❌ Xato: {error_details}", parse_mode="HTML")

@courier_router.callback_query(F.data.startswith("confirm_lock_price_"))
async def handle_confirm_lock_price(callback_query: types.CallbackQuery):
    order_id = int(callback_query.data.split("_")[3])
    user_id = str(callback_query.from_user.id)

    await callback_query.answer()
    await callback_query.message.edit_text(f"⏳ Buyurtma #{order_id} narxi bloklanmoqda...")

    success, result = await client.lock_order_price(order_id, user_id)

    if success:
        await show_delivery_menu_after_action(
            callback_query,
            order_id,
            "Narx muvaffaqiyatli bloklandi!"
        )
    else:
        error_details = result.get('error', 'Noma\'lum xato') if isinstance(result, dict) else str(result)
        await callback_query.message.edit_text(f"❌ Xato: {error_details}", parse_mode="HTML")

@courier_router.callback_query(F.data.startswith("cancel_"))
async def handle_cancel_action(callback_query: types.CallbackQuery, state: FSMContext):
    parts = callback_query.data.split("_")
    action = parts[1]
    order_id = int(parts[2])

    await callback_query.answer("❌ Bekor qilindi")

    success, order_detail = await client.get_order_detail(order_id)
    if success:
        is_price_locked = order_detail.get('is_price_locked', False)
        order_status = order_detail.get('status', '')
        await callback_query.message.edit_text(
            f"🔄 {hd.bold('KEYINGI AMALNI TANLANG')}\n\n"
            f"📦 Buyurtma: #{order_id}\n"
            f"📊 Holat: {order_status.capitalize()}",
            parse_mode="HTML",
            reply_markup=get_delivery_actions_keyboard(order_id, is_price_locked, order_status)
        )
    else:
        await callback_query.message.edit_text("❌ Xatolik yuz berdi.", parse_mode="HTML")

# ============ YETKAZISHNI YAKUNLASH ============

@courier_router.callback_query(F.data.startswith("confirm_delivery_"))
async def handle_confirm_delivery(callback_query: types.CallbackQuery):
    order_id = int(callback_query.data.replace("confirm_delivery_", ""))
    user_id = str(callback_query.from_user.id)

    await callback_query.answer()

    success, order_detail = await client.get_order_detail(order_id)

    if not success:
        await callback_query.message.edit_text("❌ Buyurtma ma'lumotlari olinmadi.", parse_mode="HTML")
        return

    if not order_detail.get('is_price_locked', False):
        await callback_query.message.edit_text(
            f"❌ {hd.bold('NARX BLOKLANMAGAN')}\n\n"
            f"Avval narxni bloklang.",
            parse_mode="HTML"
        )
        return

    await callback_query.message.edit_text(f"⏳ Buyurtma #{order_id} yetkazildi deb belgilanmoqda...")

    success, result = await client.deliver_order(order_id, user_id)

    if success:
        await callback_query.message.edit_text(
            f"✅ {hd.bold('BUYURTMA YETKAZILDI')}\n\n"
            f"📦 Buyurtma raqami: #{order_id}",
            parse_mode="HTML"
        )
    else:
        error_details = result.get('error', 'Noma\'lum xato') if isinstance(result, dict) else str(result)
        await callback_query.message.edit_text(f"❌ Xato: {error_details}", parse_mode="HTML")

@courier_router.callback_query(F.data.startswith("back_to_order_"))
async def handle_back_to_order(callback_query: types.CallbackQuery):
    order_id = int(callback_query.data.replace("back_to_order_", ""))
    await callback_query.answer()

    success, order_detail = await client.get_order_detail(order_id)
    if success:
        order_text = format_order_detail(order_detail)
        status = order_detail.get('status', '')
        is_price_locked = order_detail.get('is_price_locked', False)
        keyboard = get_order_actions_keyboard(order_id, status, is_price_locked)
        await callback_query.message.edit_text(order_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await callback_query.message.edit_text("❌ Xatolik yuz berdi.", parse_mode="HTML")

# ============ BATAFSIL BUYURTMA MA'LUMOTLARI ============

@courier_router.callback_query(F.data.startswith("detail_order_"))
async def handle_detail_order(callback_query: types.CallbackQuery):
    order_id = int(callback_query.data.replace("detail_order_", ""))

    await callback_query.answer()

    # Xabarni tahrirlab, yuklanayotganini ko'rsatamiz
    await callback_query.message.edit_text(
        f"⏳ {hd.bold('Buyurtma #{order_id} ma\'lumotlari yuklanmoqda...')}",
        parse_mode="HTML"
    )

    success, order_detail = await client.get_order_detail(order_id)

    if not success:
        await callback_query.message.edit_text(
            "❌ Buyurtma ma'lumotlari olinmadi.",
            parse_mode="HTML"
        )
        return

    order_text = format_order_detail(order_detail)

    user_telegram_id = order_detail.get('user_telegram_id')
    if user_telegram_id:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        stats_success, stats_data = await client.get_user_order_stats(user_telegram_id, start_date, end_date)
        if stats_success:
            stats_text = format_user_stats(stats_data)
            order_text += stats_text

    status = order_detail.get('status', '')
    is_price_locked = order_detail.get('is_price_locked', False)
    keyboard = get_order_actions_keyboard(order_id, status, is_price_locked)

    await callback_query.message.edit_text(order_text, parse_mode="HTML", reply_markup=keyboard)

# ============ QOLGAN HANDLERLAR ============

@courier_router.message(F.text == "📋 Zakazlarim tarixi")
async def handle_order_history(message: types.Message):
    user_id = str(message.from_user.id)

    success, report_data = await client.get_courier_report(user_id, 30)

    if success:
        report_text = format_report(report_data, "monthly")
        await message.answer(report_text, parse_mode="HTML", reply_markup=get_main_keyboard())
    else:
        error_details = report_data.get('error', 'Noma\'lum xato') if isinstance(report_data, dict) else str(report_data)
        await message.answer(f"❌ Xato: {error_details}", parse_mode="HTML", reply_markup=get_main_keyboard())

@courier_router.message(F.text == "💰 Balans / Hisobot")
async def handle_balance_report(message: types.Message):
    info_message = (
        f"💰 {hd.bold('BALANS VA HISOBOT BO\'LIMI')}\n\n"
        f"Bu yerda siz o'z daromadlaringizni va ish faolligingizni ko'rishingiz mumkin."
    )
    await message.answer(info_message, parse_mode="HTML", reply_markup=get_balance_keyboard())

@courier_router.message(F.text == "💰 Balansim")
async def handle_my_balance(message: types.Message):
    user_id = str(message.from_user.id)

    success, report_data = await client.get_courier_report(user_id, 30)

    if success:
        report_text = format_report(report_data, "monthly")
        await message.answer(report_text, parse_mode="HTML", reply_markup=get_balance_keyboard())
    else:
        error_details = report_data.get('error', 'Noma\'lum xato') if isinstance(report_data, dict) else str(report_data)
        await message.answer(f"❌ Xato: {error_details}", parse_mode="HTML", reply_markup=get_balance_keyboard())

@courier_router.message(F.text == "📊 Kunlik hisobot")
async def handle_daily_report(message: types.Message):
    user_id = str(message.from_user.id)

    success, report_data = await client.get_courier_report(user_id, 1)

    if success:
        report_text = format_report(report_data, "daily")
        await message.answer(report_text, parse_mode="HTML", reply_markup=get_balance_keyboard())
    else:
        error_details = report_data.get('error', 'Noma\'lum xato') if isinstance(report_data, dict) else str(report_data)
        await message.answer(f"❌ Xato: {error_details}", parse_mode="HTML", reply_markup=get_balance_keyboard())

@courier_router.message(F.text == "📈 Haftalik hisobot")
async def handle_weekly_report(message: types.Message):
    user_id = str(message.from_user.id)

    success, report_data = await client.get_courier_report(user_id, 7)

    if success:
        report_text = format_report(report_data, "weekly")
        await message.answer(report_text, parse_mode="HTML", reply_markup=get_balance_keyboard())
    else:
        error_details = report_data.get('error', 'Noma\'lum xato') if isinstance(report_data, dict) else str(report_data)
        await message.answer(f"❌ Xato: {error_details}", parse_mode="HTML", reply_markup=get_balance_keyboard())

@courier_router.message(F.text == "📉 Oylik hisobot")
async def handle_monthly_report(message: types.Message):
    user_id = str(message.from_user.id)

    success, report_data = await client.get_courier_report(user_id, 30)

    if success:
        report_text = format_report(report_data, "monthly")
        await message.answer(report_text, parse_mode="HTML", reply_markup=get_balance_keyboard())
    else:
        error_details = report_data.get('error', 'Noma\'lum xato') if isinstance(report_data, dict) else str(report_data)
        await message.answer(f"❌ Xato: {error_details}", parse_mode="HTML", reply_markup=get_balance_keyboard())

@courier_router.message(F.text == "⭐ Mening reytingim")
async def handle_my_rating(message: types.Message):
    user_id = str(message.from_user.id)

    success, report_data = await client.get_courier_report(user_id, 30)

    if success:
        rating_text = format_rating_info(report_data)
        await message.answer(rating_text, parse_mode="HTML", reply_markup=get_main_keyboard())
    else:
        error_details = report_data.get('error', 'Noma\'lum xato') if isinstance(report_data, dict) else str(report_data)
        await message.answer(f"❌ Xato: {error_details}", parse_mode="HTML", reply_markup=get_main_keyboard())

@courier_router.message(F.text == "🔄 Yangilash")
async def handle_refresh(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    int_id = message.from_user.id

    check_success, check_data = await client.check_courier_exists(user_id)

    if check_success:
        if check_data.get('exists'):
            await state.update_data(courier_info=check_data)
            active_couriers.add(int_id)
            success, orders = await client.get_courier_orders(user_id)
            if success and orders:
                last_orders[int_id] = {o['id'] for o in orders}
            else:
                last_orders[int_id] = set()
            await message.answer("✅ Ma'lumotlar yangilandi.", parse_mode="HTML", reply_markup=get_main_keyboard())
        else:
            await message.answer("❌ Kuryerlar ro'yxatida yo'qsiz.", parse_mode="HTML")
    else:
        error_details = check_data.get('error', 'Noma\'lum xato') if isinstance(check_data, dict) else str(check_data)
        await message.answer(f"❌ Xato: {error_details}", parse_mode="HTML", reply_markup=get_main_keyboard())

@courier_router.message(F.text == "⬅️ Orqaga")
async def handle_back(message: types.Message, state: FSMContext):
    await state.set_state(CourierStates.main_menu)
    await message.answer("Asosiy menyu:", reply_markup=get_main_keyboard())

# ============================================================================
# ASOSIY BOT ISHGA TUSHIRISH
# ============================================================================

async def main():
    global bot
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN topilmadi!")
        return

    logger.info(f"🤖 Bot ishga tushirilmoqda...")
    logger.info(f"📡 API URL: {API_BASE_URL}")

    try:
        bot = Bot(token=BOT_TOKEN)
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)

        dp.include_router(courier_router)

        asyncio.create_task(polling_task())

        logger.info("✅ Bot muvaffaqiyatli yaratildi")
        await dp.start_polling(bot, skip_updates=True)

    except Exception as e:
        logger.error(f"❌ Botni ishga tushirishda xatolik: {e}")
    finally:
        logger.info("👋 Bot to'xtatildi")

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🚚 SHUKRONA SUV KURYER BOTI")
    print("="*50)
    print(f"📡 API URL: {API_BASE_URL}")
    print("="*50)
    print("📊 Bot ishga tushirilmoqda...")
    print("="*50 + "\n")

    try:
        asyncio.run(main())
    except KeyboardInterrupt: 
        logger.info("👋 Bot to'xtatildi")
    except Exception as e:
        logger.error(f"❌ Xatolik: {e}")