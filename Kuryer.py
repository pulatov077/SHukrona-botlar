import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
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
    CallbackQuery
)
from aiogram.fsm.storage.memory import MemoryStorage
import aiohttp
import json
import logging
import sys

# ============================================================================
# SOZLAMALAR VA LOGGER
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Kuryer")
logger.info("🚚 Kuryer moduli yuklandi")

# ASOSIY API URL
API_BASE_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
logger.info(f"🔧 Kuryer moduli uchun API URL: {API_BASE_URL}")

# Bot tokenini environment variable dan olamiz yoki to'g'ridan yozamiz
BOT_TOKEN = "8372693619:AAEiSlEnmkUBpXu958yb9KmuSYs-jt3ZstU"

if not BOT_TOKEN:
    logger.error("❌ Iltimos, haqiqiy BOT_TOKEN ni kiriting!")
    logger.error("1. Environment variable o'rnating: export BOT_TOKEN_KURYER='sizning_token'")
    logger.error("2. Yoki yuqoridagi BOT_TOKEN o'rniga to'g'ri token yozing")
    sys.exit(1)

# ============================================================================
# FSM HOLATLARI
# ============================================================================

class CourierStates(StatesGroup):
    """Kuryer holatlari"""
    main_menu = State()                   # Asosiy menyu
    waiting_for_delivery_time = State()   # Yetkazish vaqti kutilmoqda
    waiting_for_new_price = State()       # Yangi narx kutilmoqda
    waiting_for_bonus_product = State()   # Bonus mahsulot kutilmoqda

# ============================================================================
# API CLIENT
# ============================================================================

class CourierClient:
    """API client"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Tuple[bool, Any]:
        """Umumiy so'rov yuborish"""
        try:
            url = f"{self.base_url}{endpoint}"
            timeout = aiohttp.ClientTimeout(total=60)
            
            headers = kwargs.pop('headers', {})
            headers.update({
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            })
            
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=method,
                    url=url,
                    timeout=timeout,
                    headers=headers,
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
                        return False, error_text
                        
        except Exception as e:
            logger.error(f"❌ Network error: {e}")
            return False, str(e)
    
    # ============ KURYER FUNKSIYALARI ============
    
    async def check_courier_exists(self, telegram_id: str) -> Tuple[bool, Optional[Dict]]:
        """Kuryer mavjudligini tekshirish"""
        try:
            success, data = await self._make_request("GET", f"/couriers/check-messenger/{telegram_id}/")
            
            if success:
                if isinstance(data, dict):
                    # Backenddan kelayotgan formatni tekshirish
                    if 'status' in data and data['status'] == 200:
                        return True, {
                            'exists': True,
                            'courier_name': data.get('courier_name', 'Kuryer'),
                            'message': data.get('message', 'Kuryer topildi'),
                            'is_active': True
                        }
                    elif 'detail' in data and 'Kuryer topildi' in data['detail']:
                        return True, {
                            'exists': True,
                            'courier_name': 'Kuryer',
                            'message': data.get('detail', 'Kuryer topildi'),
                            'is_active': True
                        }
                    elif 'detail' in data and 'Kuryer topilmadi' in data['detail']:
                        return True, {'exists': False, 'message': data['detail']}
                
                # Agar ma'lumot topilgan bo'lsa, mavjud deb hisoblaymiz
                return True, {'exists': True, 'courier_name': 'Kuryer', 'message': 'Kuryer mavjud'}
            
            return False, {'error': 'API bilan bog\'lanishda xatolik'}
                
        except Exception as e:
            logger.error(f"Kuryer tekshirishda xatolik: {e}")
            return False, {'error': str(e)}
    
    async def get_courier_info(self, telegram_id: str) -> Tuple[bool, Optional[Dict]]:
        """Kuryer ma'lumotlarini olish"""
        try:
            # Avval kuryer mavjudligini tekshirish
            check_success, check_data = await self.check_courier_exists(telegram_id)
            
            if check_success and check_data.get('exists'):
                # Bugungi kun uchun hisobot olish
                today = datetime.now().strftime('%Y-%m-%d')
                history_endpoint = f"/couriers/me/history/?telegram_id={telegram_id}&start_date={today}&end_date={today}"
                
                history_success, history_data = await self._make_request("GET", history_endpoint)
                
                if history_success and isinstance(history_data, dict):
                    # Tarixdan ma'lumotlarni olamiz
                    total_items_sold = history_data.get('total_items_sold', 0)
                    total_deliveries = history_data.get('total_delivered_orders', 0)
                    total_money = history_data.get('total_money_collected', 0)
                    rating = history_data.get('average_rating', 0)
                    
                    return True, {
                        'id': telegram_id,
                        'name': check_data.get('courier_name', 'Kuryer'),
                        'telegram_id': telegram_id,
                        'status': 'active',
                        'rating': rating,
                        'total_deliveries': total_deliveries,
                        'total_items_sold': total_items_sold,
                        'total_money': total_money,
                        'phone': check_data.get('phone', 'Noma\'lum')
                    }
                
                # Agar tarix API ishlamasa, oddiy ma'lumotlar bilan qaytaramiz
                return True, {
                    'id': telegram_id,
                    'name': check_data.get('courier_name', 'Kuryer'),
                    'telegram_id': telegram_id,
                    'status': 'active',
                    'rating': 0,
                    'total_deliveries': 0,
                    'total_items_sold': 0,
                    'total_money': 0,
                    'phone': check_data.get('phone', 'Noma\'lum')
                }
            
            return True, None
                
        except Exception as e:
            logger.error(f"Kuryer ma'lumotlarini olishda xatolik: {e}")
            return False, None
    
    async def get_courier_daily_report(self, telegram_id: str, date: str = None) -> Tuple[bool, Optional[Dict]]:
        """Kuryer kunlik hisobotini olish"""
        try:
            if not date:
                date = datetime.now().strftime('%Y-%m-%d')
            
            endpoint = f"/couriers/me/history/?telegram_id={telegram_id}&start_date={date}&end_date={date}"
            success, data = await self._make_request("GET", endpoint)
            
            if success and isinstance(data, dict):
                return True, data
            return False, {"error": "Hisobot olinmadi"}
            
        except Exception as e:
            logger.error(f"Kunlik hisobot olishda xatolik: {e}")
            return False, {"error": f"Ulanish xatosi: {str(e)}"}
    
    async def get_courier_weekly_report(self, telegram_id: str) -> Tuple[bool, Optional[Dict]]:
        """Kuryer haftalik hisobotini olish"""
        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            
            endpoint = f"/couriers/me/history/?telegram_id={telegram_id}&start_date={start_date}&end_date={end_date}"
            success, data = await self._make_request("GET", endpoint)
            
            if success and isinstance(data, dict):
                return True, data
            return False, {"error": "Hisobot olinmadi"}
            
        except Exception as e:
            logger.error(f"Haftalik hisobot olishda xatolik: {e}")
            return False, {"error": f"Ulanish xatosi: {str(e)}"}
    
    async def get_courier_monthly_report(self, telegram_id: str) -> Tuple[bool, Optional[Dict]]:
        """Kuryer oylik hisobotini olish"""
        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            
            endpoint = f"/couriers/me/history/?telegram_id={telegram_id}&start_date={start_date}&end_date={end_date}"
            success, data = await self._make_request("GET", endpoint)
            
            if success and isinstance(data, dict):
                return True, data
            return False, {"error": "Hisobot olinmadi"}
            
        except Exception as e:
            logger.error(f"Oylik hisobot olishda xatolik: {e}")
            return False, {"error": f"Ulanish xatosi: {str(e)}"}
    
    # ============ BUYURTMALAR FUNKSIYALARI ============
    
    async def get_courier_orders(self, telegram_id: str, status: str = None, limit: int = 20, offset: int = 0) -> Tuple[bool, Optional[List]]:
        """Kuryerning buyurtmalarini olish"""
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
        """Bitta buyurtma haqida ma'lumot olish"""
        try:
            success, data = await self._make_request("GET", f"/orders/{order_id}/")
            
            if success:
                return True, data
            return False, {"error": "Buyurtma topilmadi"}
            
        except Exception as e:
            logger.error(f"❌ Buyurtma ma'lumotlarini olishda xatolik: {str(e)}")
            return False, {"error": f"Ulanish xatosi: {str(e)}"}
    
    async def accept_order(self, order_id: int, telegram_id: str, delivery_time: str = "30 daqiqa") -> Tuple[bool, Optional[Dict]]:
        """Buyurtmani qabul qilish"""
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
            return False, {"error": f"Ulanish xatosi: {str(e)}"}
    
    async def lock_order_price(self, order_id: int, telegram_id: str) -> Tuple[bool, Optional[Dict]]:
        """Buyurtma narxini bloklash"""
        try:
            data = {
                "courier_telegram_id": str(telegram_id)
            }
            
            success, result = await self._make_request("PATCH", f"/orders/{order_id}/lock-price/", json=data)
            
            if success:
                return True, result
            return False, {"error": "Bloklashda xatolik"}
            
        except Exception as e:
            logger.error(f"❌ Buyurtma narxini bloklashda xatolik: {str(e)}")
            return False, {"error": f"Ulanish xatosi: {str(e)}"}
    
    async def update_order_price(self, order_id: int, telegram_id: str, new_price: float) -> Tuple[bool, Optional[Dict]]:
        """Buyurtma narxini o'zgartirish"""
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
            return False, {"error": f"Ulanish xatosi: {str(e)}"}
    
    async def deliver_order(self, order_id: int, telegram_id: str) -> Tuple[bool, Optional[Dict]]:
        """Buyurtmani yetkazildi deb belgilash"""
        try:
            data = {
                "courier_telegram_id": str(telegram_id)
            }
            
            success, result = await self._make_request("PATCH", f"/orders/{order_id}/deliver/", json=data)
            
            if success:
                return True, result
            return False, {"error": "Yetkazishda xatolik"}
            
        except Exception as e:
            logger.error(f"❌ Buyurtma yetkazishda xatolik: {str(e)}")
            return False, {"error": f"Ulanish xatosi: {str(e)}"}
    
    async def add_bonus_to_order(self, order_id: int, telegram_id: str, product_id: int, quantity: int = 1) -> Tuple[bool, Optional[Dict]]:
        """Buyurtmaga bonus mahsulot qo'shish"""
        try:
            data = {
                "courier_telegram_id": str(telegram_id),
                "items": [
                    {
                        "product_id": product_id,
                        "quantity": quantity
                    }
                ]
            }
            
            success, result = await self._make_request("POST", f"/orders/{order_id}/bonus/", json=data)
            
            if success:
                return True, result
            return False, {"error": "Bonus qo'shishda xatolik"}
            
        except Exception as e:
            logger.error(f"❌ Bonus qo'shishda xatolik: {str(e)}")
            return False, {"error": f"Ulanish xatosi: {str(e)}"}

# ============================================================================
# KLAVIATURALAR
# ============================================================================

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Asosiy kuryer klaviaturasi"""
    keyboard = [
        [KeyboardButton(text="📦 Buyurtmalar")],
        [
            KeyboardButton(text="📋 Zakazlarim tarixi"),
            KeyboardButton(text="💰 Balans / Hisobot")
        ],
        [
            KeyboardButton(text="⭐ Mening reytingim")
        ],
        [
            KeyboardButton(text="🔄 Yangilash")
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Kuryer buyrug'ini tanlang..."
    )

def get_back_keyboard() -> ReplyKeyboardMarkup:
    """Orqaga qaytish klaviaturasi"""
    keyboard = [[KeyboardButton(text="⬅️ Orqaga")]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_balance_keyboard() -> ReplyKeyboardMarkup:
    """Balans va hisobot klaviaturasi"""
    keyboard = [
        [KeyboardButton(text="💰 Balansim")],
        [KeyboardButton(text="📊 Kunlik hisobot")],
        [KeyboardButton(text="📈 Haftalik hisobot")],
        [KeyboardButton(text="📉 Oylik hisobot")],
        [KeyboardButton(text="⬅️ Orqaga")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_orders_keyboard() -> ReplyKeyboardMarkup:
    """Buyurtmalar klaviaturasi"""
    keyboard = [
        [KeyboardButton(text="🚚 Kutilmoqda buyurtmalar")],
        [KeyboardButton(text="⚡ Faol buyurtmalar")],
        [KeyboardButton(text="✅ Yetkazilganlar")],
        [KeyboardButton(text="❌ Bekor qilinganlar")],
        [KeyboardButton(text="⬅️ Orqaga")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_bonus_products_keyboard() -> ReplyKeyboardMarkup:
    """Bonus mahsulotlar klaviaturasi"""
    keyboard = [
        [KeyboardButton(text="🍏 Olma (ID: 1)")],
        [KeyboardButton(text="🍌 Banan (ID: 2)")],
        [KeyboardButton(text="🥕 Sabzi (ID: 3)")],
        [KeyboardButton(text="🧃 Sharbat (ID: 4)")],
        [KeyboardButton(text="🍬 Konfet (ID: 5)")],
        [KeyboardButton(text="⬅️ Orqaga")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_order_actions_keyboard(order_id: int, order_status: str, is_price_locked: bool = False) -> InlineKeyboardMarkup:
    """Buyurtma uchun amallar klaviaturasi"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    if order_status == "kutilmoqda":
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"accept_order_{order_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_order_{order_id}")
        ])
    elif order_status in ["qabul_qilindi", "yetkazilmoqda", "kuryerda"]:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🚚 Yetkazildi", callback_data=f"deliver_order_{order_id}")
        ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="📋 Batafsil", callback_data=f"detail_order_{order_id}")
    ])
    
    return keyboard

def get_delivery_actions_keyboard(order_id: int, is_price_locked: bool = False, order_status: str = "yetkazilmoqda") -> InlineKeyboardMarkup:
    """Yetkazishdan keyingi amallar klaviaturasi"""
    if is_price_locked:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yakunlash", callback_data=f"confirm_delivery_{order_id}"),
                InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"back_to_orders_{order_id}")
            ]
        ])
    else:
        # Faqat kuryerda yoki yetkazilmoqda holatlarida narxni o'zgartirish mumkin
        if order_status in ["kuryerda", "yetkazilmoqda"]:
            return InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="💰 Narxni o'zgartirish", callback_data=f"update_price_{order_id}"),
                    InlineKeyboardButton(text="🎁 Bonus qo'shish", callback_data=f"add_bonus_{order_id}")
                ],
                [
                    InlineKeyboardButton(text="🔒 Narxni bloklash", callback_data=f"lock_price_{order_id}")
                ],
                [
                    InlineKeyboardButton(text="✅ Yakunlash", callback_data=f"confirm_delivery_{order_id}"),
                    InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"back_to_orders_{order_id}")
                ]
            ])
        else:
            return InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Yakunlash", callback_data=f"confirm_delivery_{order_id}"),
                    InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"back_to_orders_{order_id}")
                ]
            ])

def get_confirmation_keyboard(action: str, order_id: int, data: Any = None) -> InlineKeyboardMarkup:
    """Tasdiqlash klaviaturasi"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ha, tasdiqlash", callback_data=f"confirm_{action}_{order_id}_{data if data else ''}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"cancel_{action}_{order_id}")
        ]
    ])

# ============================================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================================

def format_courier_welcome(courier_data: Dict) -> str:
    """Kuryer uchun xush kelibsiz xabarini formatlash"""
    try:
        courier_name = courier_data.get('name', 'Kuryer')
        courier_id = courier_data.get('telegram_id', 'Noma\'lum')
        rating = courier_data.get('rating', 0)
        total_deliveries = courier_data.get('total_deliveries', 0)
        total_items_sold = courier_data.get('total_items_sold', 0)
        total_money = courier_data.get('total_money', 0)
        phone = courier_data.get('phone', 'Noma\'lum')
        
        stars = '⭐' * int(rating) + '☆' * (5 - int(rating))
        
        formatted = (
            f"🚚 {hd.bold('KURYER PANELIGA XUSH KELIBSIZ!')}\n\n"
            f"👤 {hd.bold('Ism:')} {courier_name}\n"
            f"📱 {hd.bold('Telefon:')} {phone}\n"
            f"🆔 {hd.bold('Telegram ID:')} {courier_id}\n"
            f"⭐ {hd.bold('Reyting:')} {stars} ({rating:.1f}/5.0)\n"
            f"📦 {hd.bold('Yetkazilgan:')} {total_deliveries} ta\n"
            f"🛍 {hd.bold('Sotilgan mahsulotlar:')} {total_items_sold} ta\n"
            f"💰 {hd.bold('Jami daromad:')} {total_money:,.0f} so'm\n\n"
            f"―――――――――――――――――――――\n"
            f"Bu yerda siz o'zingizning barcha buyurtmalaringizni ko'rishingiz mumkin."
        )
        
        return formatted
        
    except Exception as e:
        logger.error(f"Xush kelibsiz xabarini formatlashda xatolik: {e}")
        return f"🚚 {hd.bold('KURYER PANELIGA XUSH KELIBSIZ!')}"

def format_order_detail(order: Dict) -> str:
    """Buyurtma batafsil ma'lumotlarini formatlash"""
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
        
        # User type uchun emoji va ma'no
        user_type_display = {
            'standard': '👤 Standart',
            'maxsus': '👑 Maxsus',
            'vip': '⭐ VIP'
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
        
        bonus_items = order.get('bonus_items', [])
        if bonus_items:
            formatted += f"\n🎁 {hd.bold('Bonus mahsulotlar:')}\n"
            for item in bonus_items:
                product_name = item.get('product_name', 'Noma\'lum mahsulot')
                quantity = item.get('quantity', 1)
                formatted += f"  • {product_name} - {quantity} ta (Tekin)\n"
        
        return formatted
        
    except Exception as e:
        logger.error(f"Buyurtma ma'lumotlarini formatlashda xatolik: {e}")
        return f"❌ Buyurtma ma'lumotlarini formatlashda xatolik"

def format_balance_info(courier_data: Dict) -> str:
    """Balans ma'lumotlarini formatlash"""
    try:
        courier_name = courier_data.get('name', 'Kuryer')
        total_money = courier_data.get('total_money', 0)
        total_deliveries = courier_data.get('total_deliveries', 0)
        total_items_sold = courier_data.get('total_items_sold', 0)
        rating = courier_data.get('rating', 0)
        
        stars = '⭐' * int(rating) + '☆' * (5 - int(rating))
        
        formatted = (
            f"💰 {hd.bold('BALANS VA HISOBOT')}\n\n"
            f"👤 {hd.bold('Kuryer:')} {courier_name}\n\n"
            f"📊 {hd.bold('STATISTIKA:')}\n"
            f"├ 📦 Yetkazilgan buyurtmalar: {total_deliveries} ta\n"
            f"├ 🛍 Sotilgan mahsulotlar: {total_items_sold} ta\n"
            f"├ 💰 Jami to'plangan summa: {total_money:,.0f} so'm\n"
            f"└ ⭐ O'rtacha reyting: {stars} ({rating:.1f}/5.0)\n\n"
            f"💰 {hd.bold('HOZIRGI BALANS:')} 0 so'm\n"
            f"ℹ️ *Balans to'ldirish uchun admin bilan bog'laning*\n\n"
            f"―――――――――――――――――――――\n"
            f"ℹ️ Eslatma: Hozircha mayjud balans yo'q"
        )
        
        return formatted
        
    except Exception as e:
        logger.error(f"Balans formatlashda xatolik: {e}")
        return f"❌ Balans ma'lumotlarini formatlashda xatolik"

def format_daily_report(report_data: Dict) -> str:
    """Kunlik hisobotni formatlash"""
    try:
        courier_name = report_data.get('courier_name', 'Kuryer')
        total_deliveries = report_data.get('total_delivered_orders', 0)
        total_items_sold = report_data.get('total_items_sold', 0)
        total_money = report_data.get('total_money_collected', 0)
        rating = report_data.get('average_rating', 0)
        
        formatted = (
            f"📊 {hd.bold('KUNLIK HISOBOT')}\n\n"
            f"👤 {hd.bold('Kuryer:')} {courier_name}\n"
            f"📅 {hd.bold('Sana:')} {datetime.now().strftime('%d.%m.%Y')}\n\n"
            f"📈 {hd.bold('BUGUNGI KO\'RSATKICHLAR:')}\n"
            f"├ 📦 Yetkazilgan buyurtmalar: {total_deliveries} ta\n"
            f"├ 🛍 Sotilgan mahsulotlar: {total_items_sold} ta\n"
            f"├ 💰 Bugungi daromad: {total_money:,.0f} so'm\n"
            f"└ ⭐ Bugungi reyting: {rating:.1f}/5.0\n\n"
            f"―――――――――――――――――――――\n"
            f"ℹ️ Ma'lumotlar bugungi kun uchun"
        )
        
        return formatted
        
    except Exception as e:
        logger.error(f"Kunlik hisobot formatlashda xatolik: {e}")
        return f"❌ Kunlik hisobot formatlashda xatolik"

def format_weekly_report(report_data: Dict) -> str:
    """Haftalik hisobotni formatlash"""
    try:
        courier_name = report_data.get('courier_name', 'Kuryer')
        total_deliveries = report_data.get('total_delivered_orders', 0)
        total_items_sold = report_data.get('total_items_sold', 0)
        total_money = report_data.get('total_money_collected', 0)
        rating = report_data.get('average_rating', 0)
        
        start_date = (datetime.now() - timedelta(days=7)).strftime('%d.%m.%Y')
        end_date = datetime.now().strftime('%d.%m.%Y')
        
        formatted = (
            f"📈 {hd.bold('HAFTALIK HISOBOT')}\n\n"
            f"👤 {hd.bold('Kuryer:')} {courier_name}\n"
            f"📅 {hd.bold('Davr:')} {start_date} - {end_date}\n\n"
            f"📊 {hd.bold('HAFTALIK KO\'RSATKICHLAR:')}\n"
            f"├ 📦 Jami buyurtmalar: {total_deliveries} ta\n"
            f"├ 🛍 Jami sotilganlar: {total_items_sold} ta\n"
            f"├ 💰 Jami daromad: {total_money:,.0f} so'm\n"
            f"├ 📆 O'rtacha kunlik: {total_deliveries/7:.1f} ta\n"
            f"└ ⭐ O'rtacha reyting: {rating:.1f}/5.0\n\n"
            f"―――――――――――――――――――――\n"
            f"ℹ️ Ma'lumotlar oxirgi 7 kun uchun"
        )
        
        return formatted
        
    except Exception as e:
        logger.error(f"Haftalik hisobot formatlashda xatolik: {e}")
        return f"❌ Haftalik hisobot formatlashda xatolik"

def format_monthly_report(report_data: Dict) -> str:
    """Oylik hisobotni formatlash"""
    try:
        courier_name = report_data.get('courier_name', 'Kuryer')
        total_deliveries = report_data.get('total_delivered_orders', 0)
        total_items_sold = report_data.get('total_items_sold', 0)
        total_money = report_data.get('total_money_collected', 0)
        rating = report_data.get('average_rating', 0)
        
        month_name = datetime.now().strftime('%B %Y')
        
        formatted = (
            f"📉 {hd.bold('OYLIK HISOBOT')}\n\n"
            f"👤 {hd.bold('Kuryer:')} {courier_name}\n"
            f"📅 {hd.bold('Oy:')} {month_name}\n\n"
            f"📊 {hd.bold('OYLIK KO\'RSATKICHLAR:')}\n"
            f"├ 📦 Jami buyurtmalar: {total_deliveries} ta\n"
            f"├ 🛍 Jami sotilganlar: {total_items_sold} ta\n"
            f"├ 💰 Jami daromad: {total_money:,.0f} so'm\n"
            f"├ 📆 O'rtacha kunlik: {total_deliveries/30:.1f} ta\n"
            f"└ ⭐ O'rtacha reyting: {rating:.1f}/5.0\n\n"
            f"―――――――――――――――――――――\n"
            f"ℹ️ Ma'lumotlar oxirgi 30 kun uchun"
        )
        
        return formatted
        
    except Exception as e:
        logger.error(f"Oylik hisobot formatlashda xatolik: {e}")
        return f"❌ Oylik hisobot formatlashda xatolik"

# ============================================================================
# ROUTER VA HANDLERLAR
# ============================================================================

courier_router = Router()
client = CourierClient(API_BASE_URL)

# ============ START HANDLER ============

@courier_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    """Start bosilganda kuryerni tekshirish"""
    user_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.full_name
    
    logger.info(f"🔍 /start - User: {user_id} (@{username})")
    
    await message.answer("⏳ Kuryer ma'lumotlari tekshirilmoqda...")
    
    try:
        # Kuryer mavjudligini tekshirish
        check_success, check_data = await client.check_courier_exists(user_id)
        
        if check_success:
            if check_data.get('exists'):
                # Kuryer to'liq ma'lumotlarini olish
                courier_success, courier_data = await client.get_courier_info(user_id)
                
                if courier_success and courier_data:
                    welcome_message = format_courier_welcome(courier_data)
                    await message.answer(welcome_message, parse_mode="HTML", reply_markup=get_main_keyboard())
                    await state.set_state(CourierStates.main_menu)
                    await state.update_data(courier_info=courier_data)
                    
                    logger.info(f"✅ Kuryer paneli ochildi: {user_id}")
                else:
                    # Agar to'liq ma'lumotlar bo'lmasa ham, asosiy ma'lumotlar bilan ishlash
                    simple_welcome = (
                        f"🚚 {hd.bold('KURYER PANELIGA XUSH KELIBSIZ!')}\n\n"
                        f"👤 {hd.bold('Kuryer:')} {check_data.get('courier_name', 'Kuryer')}\n"
                        f"🆔 {hd.bold('Telegram ID:')} {user_id}\n\n"
                        f"―――――――――――――――――――――\n"
                        f"Bu yerda siz o'zingizning barcha buyurtmalaringizni ko'rishingiz mumkin."
                    )
                    await message.answer(simple_welcome, parse_mode="HTML", reply_markup=get_main_keyboard())
                    await state.set_state(CourierStates.main_menu)
                    await state.update_data(courier_info={'id': user_id, 'name': check_data.get('courier_name', 'Kuryer')})
            else:
                # Kuryer topilmadi
                error_message = (
                    f"⚠️ {hd.bold('KUYER RO\'YXATIDA YO\'QSIZ')}\n\n"
                    f"Uzr, siz kuryerlar ro'yxatida yo'qsiz.\n\n"
                    f"Agar kuryer bo'lishni istasangiz, quyidagi ma'lumotlarni yuboring:\n"
                    f"• Ism familiyangiz\n"
                    f"• Telefon raqamingiz\n"
                    f"• Ish tajribangiz\n\n"
                    f"Administratsiya bilan bog'laning: @admin_username"
                )
                await message.answer(error_message, parse_mode="HTML")
                await state.clear()
        else:
            error_message = (
                f"❌ {hd.bold('XATOLIK')}\n\n"
                f"Server bilan bog'lanishda xatolik yuz berdi.\n"
                f"Xato: {check_data.get('error', 'Noma\'lum xato')}\n\n"
                f"Iltimos, keyinroq qayta urinib ko'ring."
            )
            await message.answer(error_message, parse_mode="HTML")
            await state.clear()
    except Exception as e:
        logger.error(f"Start handlerida xatolik: {e}")
        error_message = (
            f"❌ {hd.bold('XATOLIK')}\n\n"
            f"Server bilan bog'lanishda xatolik yuz berdi.\n"
            f"Iltimos, keyinroq qayta urinib ko'ring."
        )
        await message.answer(error_message, parse_mode="HTML")
        await state.clear()

# ============ BUYURTMALAR BO'LIMI ============

@courier_router.message(F.text == "📦 Buyurtmalar")
async def handle_orders_menu(message: types.Message):
    """Buyurtmalar bo'limi"""
    user_id = str(message.from_user.id)
    logger.info(f"📦 'Buyurtmalar' - User: {user_id}")
    
    info_message = (
        f"📦 {hd.bold('BUYURTMALAR BO\'LIMI')}\n\n"
        f"Bu yerda siz o'zingizning barcha buyurtmalaringizni ko'rishingiz mumkin.\n\n"
        f"—— Tugmalar ——\n"
        f"🚚 Kutilmoqda buyurtmalar - Yangi buyurtmalar\n"
        f"⚡ Faol buyurtmalar - Davom etayotgan buyurtmalar\n"
        f"✅ Yetkazilganlar - Muvaffaqiyatli yakunlanganlar\n"
        f"❌ Bekor qilinganlar - Bekor qilingan buyurtmalar\n\n"
        f"ℹ️ Har bir buyurtma uchun siz quyidagi amallarni bajarishingiz mumkin:\n"
        f"• ✅ Qabul qilish (kutilmoqda holatda)\n"
        f"• ❌ Rad etish (kutilmoqda holatda)\n"
        f"• 🚚 Yetkazildi (faol holatda)\n"
        f"• 💰 Narxni o'zgartirish (narx bloklanmagan bo'lsa)\n"
        f"• 🔒 Narxni bloklash (narx bloklanmagan bo'lsa)\n"
        f"• 📋 Batafsil ma'lumot"
    )
    await message.answer(info_message, parse_mode="HTML", reply_markup=get_orders_keyboard())

async def show_orders_by_status(message: types.Message, status: str, status_name: str):
    """Berilgan statusdagi buyurtmalarni ko'rsatish"""
    user_id = str(message.from_user.id)
    
    await message.answer(f"⏳ {status_name} buyurtmalar yuklanmoqda...")
    
    success, orders = await client.get_courier_orders(user_id, status=status, limit=20)
    
    if success and orders:
        await message.answer(f"📦 {hd.bold(f'{status_name.upper()} BUYURTMALAR')} - {len(orders)} ta\n\n"
                           f"ℹ️ Quyida sizning {status_name} buyurtmalaringiz ro'yxati:", parse_mode="HTML")
        
        for order in orders:
            order_id = order.get('id', 0)
            customer_name = order.get('user_name', 'Noma\'lum mijoz')
            user_type = order.get('user_type', 'standard')
            total_amount = order.get('total_amount', 0)
            delivery_time = order.get('delivery_time', 'Belgilanmagan')
            is_price_locked = order.get('is_price_locked', False)
            
            # User type uchun emoji
            user_type_icon = {
                'standard': '👤',
                'maxsus': '👑',
                'vip': '⭐'
            }.get(user_type, '👤')
            
            status_colors = {
                'kutilmoqda': '🟡',
                'qabul_qilindi': '🟢',
                'yetkazilmoqda': '🔵',
                'yetkazildi': '✅',
                'bekor_qilindi': '❌',
                'kuryerda': '🚚'
            }
            
            status_icon = status_colors.get(status, '⚪')
            price_status = "🔒" if is_price_locked else "🔓"
            
            order_text = (
                f"📦 {hd.bold(f'Buyurtma #{order_id}')}\n"
                f"{user_type_icon} {hd.bold('Mijoz:')} {customer_name}\n"
                f"💰 {hd.bold('Summa:')} {total_amount:,} so'm\n"
                f"⏰ {hd.bold('Vaqt:')} {delivery_time}\n"
                f"📊 {hd.bold('Holat:')} {status_icon} {status.capitalize()}\n"
                f"🔐 {hd.bold('Narx:')} {price_status} {'Bloklangan' if is_price_locked else 'Bloklanmagan'}\n"
                f"―――――――――――――――――――――"
            )
            
            keyboard = get_order_actions_keyboard(order_id, status, is_price_locked)
            
            await message.answer(order_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.answer(
            f"📭 Hozirda {status_name} buyurtmalar mavjud emas.",
            reply_markup=get_orders_keyboard()
        )

@courier_router.message(F.text == "🚚 Kutilmoqda buyurtmalar")
async def handle_pending_orders(message: types.Message):
    """Kutilmoqda buyurtmalarni ko'rsatish"""
    logger.info(f"🚚 'Kutilmoqda buyurtmalar' - User: {message.from_user.id}")
    await show_orders_by_status(message, "kutilmoqda", "Kutilmoqda")

@courier_router.message(F.text == "⚡ Faol buyurtmalar")
async def handle_active_orders(message: types.Message):
    """Faol buyurtmalarni ko'rsatish"""
    logger.info(f"⚡ 'Faol buyurtmalar' - User: {message.from_user.id}")
    
    user_id = str(message.from_user.id)
    
    await message.answer("⏳ Faol buyurtmalar yuklanmoqda...")
    
    success, orders = await client.get_courier_orders(user_id, limit=20)
    
    if success and orders:
        active_orders = []
        for order in orders:
            status = order.get('status', '')
            if status in ['qabul_qilindi', 'yetkazilmoqda', 'kuryerda']:
                active_orders.append(order)
        
        if active_orders:
            await message.answer(f"📦 {hd.bold('FAOL BUYURTMALAR')} - {len(active_orders)} ta\n\n"
                               f"ℹ️ Quyida sizning faol buyurtmalaringiz ro'yxati:", parse_mode="HTML")
            
            for order in active_orders:
                order_id = order.get('id', 0)
                customer_name = order.get('user_name', 'Noma\'lum mijoz')
                user_type = order.get('user_type', 'standard')
                total_amount = order.get('total_amount', 0)
                delivery_time = order.get('delivery_time', 'Belgilanmagan')
                status = order.get('status', '')
                is_price_locked = order.get('is_price_locked', False)
                
                # User type uchun emoji
                user_type_icon = {
                    'standard': '👤',
                    'maxsus': '👑',
                    'vip': '⭐'
                }.get(user_type, '👤')
                
                status_colors = {
                    'qabul_qilindi': '🟢',
                    'yetkazilmoqda': '🔵',
                    'kuryerda': '🚚'
                }
                
                status_icon = status_colors.get(status, '⚪')
                price_status = "🔒" if is_price_locked else "🔓"
                
                order_text = (
                    f"📦 {hd.bold(f'Buyurtma #{order_id}')}\n"
                    f"{user_type_icon} {hd.bold('Mijoz:')} {customer_name}\n"
                    f"💰 {hd.bold('Summa:')} {total_amount:,} so'm\n"
                    f"⏰ {hd.bold('Vaqt:')} {delivery_time}\n"
                    f"📊 {hd.bold('Holat:')} {status_icon} {status.capitalize()}\n"
                    f"🔐 {hd.bold('Narx:')} {price_status} {'Bloklangan' if is_price_locked else 'Bloklanmagan'}\n"
                    f"―――――――――――――――――――――"
                )
                
                keyboard = get_order_actions_keyboard(order_id, status, is_price_locked)
                
                await message.answer(order_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await message.answer(
                "📭 Hozirda faol buyurtmalar mavjud emas.",
                reply_markup=get_orders_keyboard()
            )
    else:
        await message.answer(
            "❌ Buyurtmalar yuklanmadi. Iltimos, keyinroq urinib ko'ring.",
            reply_markup=get_orders_keyboard()
        )

@courier_router.message(F.text == "✅ Yetkazilganlar")
async def handle_delivered_orders(message: types.Message):
    """Yetkazilgan buyurtmalarni ko'rsatish"""
    logger.info(f"✅ 'Yetkazilganlar' - User: {message.from_user.id}")
    await show_orders_by_status(message, "yetkazildi", "Yetkazilgan")

@courier_router.message(F.text == "❌ Bekor qilinganlar")
async def handle_cancelled_orders(message: types.Message):
    """Bekor qilingan buyurtmalarni ko'rsatish"""
    logger.info(f"❌ 'Bekor qilinganlar' - User: {message.from_user.id}")
    await show_orders_by_status(message, "bekor_qilindi", "Bekor qilingan")

# ============ BUYURTMA AMALLARI ============

@courier_router.callback_query(F.data.startswith("accept_order_"))
async def handle_accept_order(callback_query: types.CallbackQuery, state: FSMContext):
    """Buyurtmani qabul qilish"""
    order_id = int(callback_query.data.replace("accept_order_", ""))
    user_id = str(callback_query.from_user.id)
    
    await callback_query.answer()
    
    logger.info(f"✅ Buyurtma qabul qilinmoqda: Order #{order_id}, User: {user_id}")
    
    await callback_query.message.answer(
        f"⏳ {hd.bold('YETKAZISH VAQTINI KIRITING')}\n\n"
        f"Buyurtma: #{order_id}\n\n"
        f"Iltimos, yetkazish vaqtini kiriting (masalan: '30 daqiqa', '1 soat', '2 soat'):",
        parse_mode="HTML"
    )
    
    await state.set_state(CourierStates.waiting_for_delivery_time)
    await state.update_data(
        order_id=order_id,
        user_id=user_id,
        message_id=callback_query.message.message_id
    )

@courier_router.message(CourierStates.waiting_for_delivery_time)
async def handle_delivery_time_input(message: types.Message, state: FSMContext):
    """Yetkazish vaqtini qabul qilish va buyurtmani qabul qilish"""
    delivery_time = message.text
    state_data = await state.get_data()
    
    order_id = state_data.get('order_id')
    user_id = state_data.get('user_id')
    message_id = state_data.get('message_id')
    
    if not order_id or not user_id:
        await message.answer("❌ Xatolik: Ma'lumotlar topilmadi. Iltimos, qaytadan urinib ko'ring.")
        await state.clear()
        return
    
    await message.answer(f"⏳ Buyurtma #{order_id} qabul qilinmoqda...")
    
    success, result = await client.accept_order(order_id, user_id, delivery_time)
    
    if success:
        success_message = (
            f"✅ {hd.bold('BUYURTMA QABUL QILINDI')}\n\n"
            f"📦 Buyurtma raqami: #{order_id}\n"
            f"⏰ Yetkazish vaqti: {delivery_time}\n\n"
            f"🎉 Endi siz buyurtmani yetkazishingiz mumkin!"
        )
        
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=message_id,
                text=success_message,
                parse_mode="HTML"
            )
        except:
            await message.answer(success_message, parse_mode="HTML")
        
        await message.answer(
            f"🔄 Buyurtma holati yangilandi. Endi quyidagi amallarni bajarishingiz mumkin:",
            reply_markup=get_order_actions_keyboard(order_id, "qabul_qilindi", False)
        )
    else:
        error_details = result.get('error', 'Noma\'lum xato') if isinstance(result, dict) else str(result)
        error_message = (
            f"❌ {hd.bold('BUYURTMA QABUL QILINMADI')}\n\n"
            f"📦 Buyurtma raqami: #{order_id}\n\n"
            f"Xato: {error_details}\n\n"
            f"ℹ️ Iltimos, qayta urinib ko'ring yoki admin bilan bog'lanishingiz kerak."
        )
        await message.answer(error_message, parse_mode="HTML")
    
    await state.clear()

@courier_router.callback_query(F.data.startswith("reject_order_"))
async def handle_reject_order(callback_query: types.CallbackQuery):
    """Buyurtmani rad etish"""
    order_id = int(callback_query.data.replace("reject_order_", ""))
    
    await callback_query.answer()
    
    await callback_query.message.edit_text(
        f"ℹ️ {hd.bold('RAD ETISH')}\n\n"
        f"📦 Buyurtma: #{order_id}\n\n"
        f"Hozircha buyurtmani rad etish funksiyasi mavjud emas.\n"
        f"Agar buyurtmani rad etish zarur bo'lsa, admin bilan bog'lanishingiz kerak.",
        parse_mode="HTML"
    )

# ============ NARXNI O'ZGARTIRISH ============

@courier_router.callback_query(F.data.startswith("update_price_"))
async def handle_update_price(callback_query: types.CallbackQuery, state: FSMContext):
    """Narxni o'zgartirish"""
    order_id = int(callback_query.data.replace("update_price_", ""))
    user_id = str(callback_query.from_user.id)
    
    await callback_query.answer()
    
    logger.info(f"💰 Narx o'zgartirilmoqda: Order #{order_id}, User: {user_id}")
    
    success, order_detail = await client.get_order_detail(order_id)
    
    if success:
        current_price = order_detail.get('total_amount', 0)
        
        await callback_query.message.answer(
            f"💰 {hd.bold('NARXNI O\'ZGARTIRISH')}\n\n"
            f"📦 Buyurtma: #{order_id}\n"
            f"💵 Joriy narx: {current_price:,} so'm\n\n"
            f"Iltimos, yangi narxni kiriting (so'mda):",
            parse_mode="HTML"
        )
        
        await state.set_state(CourierStates.waiting_for_new_price)
        await state.update_data(
            order_id=order_id,
            user_id=user_id,
            current_price=current_price
        )
    else:
        error_details = order_detail.get('error', 'Noma\'lum xato') if isinstance(order_detail, dict) else str(order_detail)
        error_message = (
            f"❌ {hd.bold('MA\'LUMOTLAR OLINMADI')}\n\n"
            f"📦 Buyurtma raqami: #{order_id}\n\n"
            f"Xato: {error_details}"
        )
        await callback_query.message.answer(error_message, parse_mode="HTML")

@courier_router.message(CourierStates.waiting_for_new_price)
async def handle_new_price_input(message: types.Message, state: FSMContext):
    """Yangi narxni qabul qilish"""
    try:
        new_price = float(message.text)
        state_data = await state.get_data()
        
        order_id = state_data.get('order_id')
        user_id = state_data.get('user_id')
        current_price = state_data.get('current_price', 0)
        
        if new_price <= 0:
            await message.answer("❌ Narx 0 dan katta bo'lishi kerak. Iltimos, qaytadan kiriting:")
            return
        
        # Tasdiqlash so'rash
        await message.answer(
            f"⚠️ {hd.bold('NARXNI O\'ZGARTIRISH')}\n\n"
            f"📦 Buyurtma: #{order_id}\n"
            f"💵 Oldingi narx: {current_price:,} so'm\n"
            f"💰 Yangi narx: {new_price:,} so'm\n\n"
            f"Haqiqatan ham narxni o'zgartirmoqchimisiz?",
            parse_mode="HTML",
            reply_markup=get_confirmation_keyboard("update_price", order_id, new_price)
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Iltimos, to'g'ri raqam kiriting (masalan: 50000):")

# ============ BONUS QO'SHISH ============

@courier_router.callback_query(F.data.startswith("add_bonus_"))
async def handle_add_bonus(callback_query: types.CallbackQuery, state: FSMContext):
    """Bonus mahsulot qo'shish"""
    order_id = int(callback_query.data.replace("add_bonus_", ""))
    
    await callback_query.answer()
    
    await callback_query.message.answer(
        f"🎁 {hd.bold('BONUS MAHSULOT QO\'SHISH')}\n\n"
        f"📦 Buyurtma: #{order_id}\n\n"
        f"Bonus mahsulot tanlang:",
        reply_markup=get_bonus_products_keyboard()
    )
    
    await state.set_state(CourierStates.waiting_for_bonus_product)
    await state.update_data(order_id=order_id)

@courier_router.message(CourierStates.waiting_for_bonus_product)
async def handle_bonus_product_selection(message: types.Message, state: FSMContext):
    """Bonus mahsulot tanlash"""
    product_text = message.text
    
    state_data = await state.get_data()
    order_id = state_data.get('order_id')
    
    if not order_id:
        await message.answer(
            "❌ Xatolik: Buyurtma ma'lumotlari topilmadi.",
            reply_markup=get_main_keyboard()
        )
        await state.set_state(CourierStates.main_menu)
        return
    
    product_mapping = {
        "🍏 Olma (ID: 1)": {"id": 1, "name": "Olma"},
        "🍌 Banan (ID: 2)": {"id": 2, "name": "Banan"},
        "🥕 Sabzi (ID: 3)": {"id": 3, "name": "Sabzi"},
        "🧃 Sharbat (ID: 4)": {"id": 4, "name": "Sharbat"},
        "🍬 Konfet (ID: 5)": {"id": 5, "name": "Konfet"}
    }
    
    if product_text not in product_mapping:
        await message.answer(
            "❌ Iltimos, ro'yxatdagi mahsulotlardan birini tanlang.",
            reply_markup=get_bonus_products_keyboard()
        )
        return
    
    product_info = product_mapping[product_text]
    
    # Tasdiqlash so'rash
    await message.answer(
        f"⚠️ {hd.bold('BONUS MAHSULOT QO\'SHISH')}\n\n"
        f"📦 Buyurtma: #{order_id}\n"
        f"🎁 Mahsulot: {product_info['name']}\n"
        f"🆔 Mahsulot ID: {product_info['id']}\n"
        f"📦 Miqdor: 1 ta\n"
        f"💰 Status: Tekin (0 so'm)\n\n"
        f"Haqiqatan ham bonus mahsulot qo'shmoqchimisiz?",
        parse_mode="HTML",
        reply_markup=get_confirmation_keyboard("add_bonus", order_id, product_info['id'])
    )
    
    await state.clear()

# ============ NARXNI BLOKLASH ============

@courier_router.callback_query(F.data.startswith("lock_price_"))
async def handle_lock_price(callback_query: types.CallbackQuery):
    """Narxni bloklash"""
    order_id = int(callback_query.data.replace("lock_price_", ""))
    
    await callback_query.answer()
    
    logger.info(f"🔒 Narx bloklanmoqda: Order #{order_id}")
    
    # Tasdiqlash so'rash
    await callback_query.message.answer(
        f"⚠️ {hd.bold('NARXNI BLOKLASH')}\n\n"
        f"📦 Buyurtma: #{order_id}\n\n"
        f"Buyurtma narxini bloklamoqchimisiz?\n\n"
        f"ℹ️ Narx bloklangandan keyin uni o'zgartirib bo'lmaydi!",
        parse_mode="HTML",
        reply_markup=get_confirmation_keyboard("lock_price", order_id)
    )

# ============ TASDIQLASH HANDLERLARI ============

@courier_router.callback_query(F.data.startswith("confirm_update_price_"))
async def handle_confirm_update_price(callback_query: types.CallbackQuery):
    """Narxni o'zgartirishni tasdiqlash"""
    data_parts = callback_query.data.split("_")
    order_id = int(data_parts[3])
    new_price = float(data_parts[4])
    user_id = str(callback_query.from_user.id)
    
    await callback_query.answer()
    
    await callback_query.message.edit_text(f"⏳ Buyurtma #{order_id} narxi o'zgartirilmoqda...")
    
    success, result = await client.update_order_price(order_id, user_id, new_price)
    
    if success:
        success_message = (
            f"✅ {hd.bold('NARX MUVAFFAQIYATLI O\'ZGARTIRILDI')}\n\n"
            f"📦 Buyurtma: #{order_id}\n"
            f"💰 Yangi narx: {new_price:,} so'm\n\n"
            f"ℹ️ Narx muvaffaqiyatli yangilandi."
        )
        await callback_query.message.edit_text(success_message, parse_mode="HTML")
    else:
        error_details = result.get('error', 'Noma\'lum xato') if isinstance(result, dict) else str(result)
        error_message = (
            f"❌ {hd.bold('NARX O\'ZGARTIRILMADI')}\n\n"
            f"📦 Buyurtma: #{order_id}\n\n"
            f"Xato: {error_details}\n\n"
            f"ℹ️ Iltimos, qayta urinib ko'ring yoki admin bilan bog'lanishingiz kerak."
        )
        await callback_query.message.edit_text(error_message, parse_mode="HTML")

@courier_router.callback_query(F.data.startswith("confirm_add_bonus_"))
async def handle_confirm_add_bonus(callback_query: types.CallbackQuery):
    """Bonus mahsulot qo'shishni tasdiqlash"""
    data_parts = callback_query.data.split("_")
    order_id = int(data_parts[3])
    product_id = int(data_parts[4])
    user_id = str(callback_query.from_user.id)
    
    await callback_query.answer()
    
    await callback_query.message.edit_text(f"⏳ Buyurtma #{order_id} ga bonus mahsulot qo'shilmoqda...")
    
    success, result = await client.add_bonus_to_order(
        order_id=order_id,
        telegram_id=user_id,
        product_id=product_id,
        quantity=1
    )
    
    if success:
        bonus_message = (
            f"✅ {hd.bold('BONUS MAHSULOT QO\'SHILDI')}\n\n"
            f"📦 Buyurtma: #{order_id}\n"
            f"🎁 Mahsulot: ID #{product_id}\n"
            f"📦 Miqdor: 1 ta\n"
            f"💰 Status: Tekin (0 so'm)\n\n"
            f"🎉 Mijozga quvonch bag'ishladingiz!"
        )
        await callback_query.message.edit_text(bonus_message, parse_mode="HTML")
    else:
        error_details = result.get('error', 'Noma\'lum xato') if isinstance(result, dict) else str(result)
        error_message = (
            f"❌ {hd.bold('BONUS MAHSULOT QO\'SHISH MUVAFFAQIYATSIZ')}\n\n"
            f"📦 Buyurtma: #{order_id}\n"
            f"🎁 Mahsulot ID: #{product_id}\n\n"
            f"Xato: {error_details}\n\n"
            f"ℹ️ Iltimos, qayta urinib ko'ring yoki admin bilan bog'lanishingiz kerak."
        )
        await callback_query.message.edit_text(error_message, parse_mode="HTML")

@courier_router.callback_query(F.data.startswith("confirm_lock_price_"))
async def handle_confirm_lock_price(callback_query: types.CallbackQuery):
    """Narxni bloklashni tasdiqlash"""
    order_id = int(callback_query.data.split("_")[3])
    user_id = str(callback_query.from_user.id)
    
    await callback_query.answer()
    
    await callback_query.message.edit_text(f"⏳ Buyurtma #{order_id} narxi bloklanmoqda...")
    
    success, result = await client.lock_order_price(order_id, user_id)
    
    if success:
        success_message = (
            f"✅ {hd.bold('NARX MUVAFFAQIYATLI BLOKLANDI')}\n\n"
            f"📦 Buyurtma: #{order_id}\n\n"
            f"🔒 Buyurtma narxi bloklandi.\n\n"
            f"ℹ️ Endi siz buyurtmani yakunlashingiz mumkin."
        )
        await callback_query.message.edit_text(success_message, parse_mode="HTML")
    else:
        error_details = result.get('error', 'Noma\'lum xato') if isinstance(result, dict) else str(result)
        error_message = (
            f"❌ {hd.bold('NARX BLOKLANMADI')}\n\n"
            f"📦 Buyurtma: #{order_id}\n\n"
            f"Xato: {error_details}\n\n"
            f"ℹ️ Iltimos, qayta urinib ko'ring yoki admin bilan bog'lanishingiz kerak."
        )
        await callback_query.message.edit_text(error_message, parse_mode="HTML")

# ============ BEKOR QILISH HANDLERLARI ============

@courier_router.callback_query(F.data.startswith("cancel_"))
async def handle_cancel_action(callback_query: types.CallbackQuery):
    """Har qanday amalni bekor qilish"""
    data_parts = callback_query.data.split("_")
    action = data_parts[1]
    order_id = int(data_parts[2])
    
    await callback_query.answer("❌ Bekor qilindi")
    
    await callback_query.message.edit_text(
        f"❌ {action.replace('_', ' ').title()} bekor qilindi.\n\n"
        f"📦 Buyurtma: #{order_id}",
        parse_mode="HTML"
    )

# ============ YETKAZISH AMALLARI ============

@courier_router.callback_query(F.data.startswith("deliver_order_"))
async def handle_deliver_order(callback_query: types.CallbackQuery):
    """Buyurtmani yetkazildi deb belgilash"""
    order_id = int(callback_query.data.replace("deliver_order_", ""))
    
    await callback_query.answer()
    
    logger.info(f"🚚 Buyurtma yetkazilmoqda: Order #{order_id}")
    
    # Buyurtma ma'lumotlarini olish
    success, order_detail = await client.get_order_detail(order_id)
    
    if not success:
        await callback_query.message.answer(
            f"❌ Buyurtma ma'lumotlari olinmadi.",
            parse_mode="HTML"
        )
        return
    
    is_price_locked = order_detail.get('is_price_locked', False)
    order_status = order_detail.get('status', '')
    
    # Yetkazish amallari klaviaturasini ko'rsatish
    await callback_query.message.answer(
        f"🔄 {hd.bold('KEYINGI AMALNI TANLANG')}\n\n"
        f"📦 Buyurtma: #{order_id}\n"
        f"🔐 Narx holati: {'🔒 BLOKLANGAN' if is_price_locked else '🔓 BLOKLANGANMAS'}\n"
        f"📊 Holat: {order_status.capitalize()}\n\n"
        f"Quyidagi amallardan birini tanlang yoki buyurtmani yakunlang:",
        parse_mode="HTML",
        reply_markup=get_delivery_actions_keyboard(order_id, is_price_locked, order_status)
    )

@courier_router.callback_query(F.data.startswith("confirm_delivery_"))
async def handle_confirm_delivery(callback_query: types.CallbackQuery):
    """Buyurtmani yakunlashni tasdiqlash"""
    order_id = int(callback_query.data.replace("confirm_delivery_", ""))
    user_id = str(callback_query.from_user.id)
    
    await callback_query.answer()
    
    # Buyurtma ma'lumotlarini olish
    success, order_detail = await client.get_order_detail(order_id)
    
    if not success:
        error_message = (
            f"❌ {hd.bold('BUYURTMA MA\'LUMOTLARI OLINMADI')}\n\n"
            f"📦 Buyurtma raqami: #{order_id}\n\n"
            f"Iltimos, qayta urinib ko'ring."
        )
        await callback_query.message.answer(error_message, parse_mode="HTML")
        return
    
    # Narx bloklanganligini tekshirish
    if not order_detail.get('is_price_locked', False):
        error_message = (
            f"❌ {hd.bold('NARX BLOKLANMAGAN')}\n\n"
            f"📦 Buyurtma raqami: #{order_id}\n\n"
            f"ℹ️ Buyurtmani yetkazildi deb belgilashdan avval narxni bloklash shart.\n\n"
            f"Iltimos, avval '🔒 Narxni bloklash' tugmasini bosing."
        )
        await callback_query.message.answer(error_message, parse_mode="HTML")
        return
    
    # Buyurtmani yetkazildi deb belgilash
    await callback_query.message.edit_text(f"⏳ Buyurtma #{order_id} yetkazildi deb belgilanmoqda...")
    
    success, result = await client.deliver_order(order_id, user_id)
    
    if success:
        success_message = (
            f"✅ {hd.bold('BUYURTMA YETKAZILDI')}\n\n"
            f"📦 Buyurtma raqami: #{order_id}\n\n"
            f"🎉 Tabriklaymiz! Buyurtmani muvaffaqiyatli yetkazdingiz.\n\n"
            f"💰 Daromadingiz hisobga qo'shildi."
        )
        await callback_query.message.edit_text(success_message, parse_mode="HTML")
        
        # Yangi amallar klaviaturasi
        await callback_query.message.answer(
            "🔄 Buyurtma holati yangilandi:",
            reply_markup=get_order_actions_keyboard(order_id, "yetkazildi", True)
        )
    else:
        error_details = result.get('error', 'Noma\'lum xato') if isinstance(result, dict) else str(result)
        error_message = (
            f"❌ {hd.bold('BUYURTMA YETKAZILMADI')}\n\n"
            f"📦 Buyurtma raqami: #{order_id}\n\n"
            f"Xato: {error_details}\n\n"
            f"ℹ️ Iltimos, qayta urinib ko'ring yoki admin bilan bog'lanishingiz kerak."
        )
        await callback_query.message.edit_text(error_message, parse_mode="HTML")

@courier_router.callback_query(F.data.startswith("back_to_orders_"))
async def handle_back_to_orders(callback_query: types.CallbackQuery):
    """Buyurtmalar ro'yxatiga qaytish"""
    await callback_query.answer()
    await callback_query.message.edit_text("🔙 Buyurtmalar ro'yxatiga qaytildi.")
    await callback_query.message.answer(
        "📦 Buyurtmalar menyusi:",
        reply_markup=get_orders_keyboard()
    )

# ============ BUYURTMA BATAFSIL MA'LUMOTLARI ============

@courier_router.callback_query(F.data.startswith("detail_order_"))
async def handle_detail_order(callback_query: types.CallbackQuery):
    """Buyurtma batafsil ma'lumotlari"""
    order_id = int(callback_query.data.replace("detail_order_", ""))
    
    await callback_query.answer()
    
    logger.info(f"📋 Buyurtma batafsil: Order #{order_id}")
    
    await callback_query.message.answer(f"⏳ Buyurtma #{order_id} ma'lumotlari yuklanmoqda...")
    
    success, order_detail = await client.get_order_detail(order_id)
    
    if success:
        order_text = format_order_detail(order_detail)
        
        status = order_detail.get('status', '')
        is_price_locked = order_detail.get('is_price_locked', False)
        keyboard = get_order_actions_keyboard(order_id, status, is_price_locked)
        
        await callback_query.message.answer(order_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        error_details = order_detail.get('error', 'Noma\'lum xato') if isinstance(order_detail, dict) else str(order_detail)
        error_message = (
            f"❌ {hd.bold('MA\'LUMOTLAR OLINMADI')}\n\n"
            f"📦 Buyurtma raqami: #{order_id}\n\n"
            f"Xato: {error_details}"
        )
        await callback_query.message.answer(error_message, parse_mode="HTML")

# ============ QOLGAN HANDLERLAR ============

@courier_router.message(F.text == "📋 Zakazlarim tarixi")
async def handle_order_history(message: types.Message, state: FSMContext):
    """Buyurtmalar tarixi"""
    user_id = str(message.from_user.id)
    logger.info(f"📋 'Zakazlarim tarixi' - User: {user_id}")
    
    # State dan kuryer ma'lumotlarini olish
    state_data = await state.get_data()
    
    if state_data and 'courier_info' in state_data:
        courier_info = state_data['courier_info']
        courier_name = courier_info.get('name', 'Kuryer')
    else:
        courier_name = 'Kuryer'
    
    history_text = (
        f"📋 {hd.bold(f'{courier_name} BUYURTMALAR TARIXI')}\n\n"
        f"📊 {hd.bold('Umumiy statistika:')}\n"
        f"• Jami buyurtmalar: 0 ta\n"
        f"• Jami daromad: 0 so'm\n"
        f"• O'rtacha reyting: 0/5.0\n\n"
        f"―――――――――――――――――――――\n"
        f"ℹ️ Batafsil tarix ma'lumotlari hozircha mavjud emas.\n"
        f"Keyingi yangilanishlarda bu bo'lim kengaytiriladi."
    )
    
    await message.answer(history_text, parse_mode="HTML", reply_markup=get_main_keyboard())

@courier_router.message(F.text == "💰 Balans / Hisobot")
async def handle_balance_report(message: types.Message):
    """Balans va hisobot bo'limi"""
    info_message = (
        f"💰 {hd.bold('BALANS VA HISOBOT BO\'LIMI')}\n\n"
        f"Bu yerda siz o'z daromadlaringizni, balansingizni va "
        f"ish faolligingizni ko'rishingiz mumkin.\n\n"
        f"—— Tugmalar ——\n"
        f"💰 Balansim - Umumiy balans va statistika\n"
        f"📊 Kunlik hisobot - Bugungi ish faolligi\n"
        f"📈 Haftalik hisobot - Haftalik statistika\n"
        f"📉 Oylik hisobot - Oylik daromadlar\n\n"
        f"ℹ️ Eslatma: Hozircha mayjud balans yo'q"
    )
    await message.answer(info_message, parse_mode="HTML", reply_markup=get_balance_keyboard())

@courier_router.message(F.text == "💰 Balansim")
async def handle_my_balance(message: types.Message, state: FSMContext):
    """Kuryer balansini ko'rsatish"""
    user_id = str(message.from_user.id)
    logger.info(f"💰 'Balansim' - User: {user_id}")
    
    # State dan kuryer ma'lumotlarini olish
    state_data = await state.get_data()
    
    if state_data and 'courier_info' in state_data:
        courier_info = state_data['courier_info']
        balance_text = format_balance_info(courier_info)
    else:
        # Agar state da ma'lumot bo'lmasa, oddiy formatda ko'rsatamiz
        balance_text = (
            f"💰 {hd.bold('BALANS VA HISOBOT')}\n\n"
            f"👤 {hd.bold('Kuryer:')} Kuryer\n\n"
            f"📊 {hd.bold('STATISTIKA:')}\n"
            f"├ 📦 Yetkazilgan buyurtmalar: 0 ta\n"
            f"├ 🛍 Sotilgan mahsulotlar: 0 ta\n"
            f"├ 💰 Jami to'plangan summa: 0 so'm\n"
            f"└ ⭐ O'rtacha reyting: ☆☆☆☆☆ (0/5.0)\n\n"
            f"💰 {hd.bold('HOZIRGI BALANS:')} 0 so'm\n"
            f"ℹ️ *Balans to'ldirish uchun admin bilan bog'laning*\n\n"
            f"―――――――――――――――――――――\n"
            f"ℹ️ Eslatma: Hozircha mayjud balans yo'q"
        )
    
    await message.answer(balance_text, parse_mode="HTML", reply_markup=get_balance_keyboard())

@courier_router.message(F.text == "📊 Kunlik hisobot")
async def handle_daily_report(message: types.Message):
    """Kunlik hisobot"""
    user_id = str(message.from_user.id)
    logger.info(f"📊 'Kunlik hisobot' - User: {user_id}")
    
    await message.answer("⏳ Bugungi hisobot yuklanmoqda...")
    
    success, report_data = await client.get_courier_daily_report(user_id)
    
    if success:
        report_text = format_daily_report(report_data)
        await message.answer(report_text, parse_mode="HTML", reply_markup=get_balance_keyboard())
    else:
        error_details = report_data.get('error', 'Noma\'lum xato') if isinstance(report_data, dict) else str(report_data)
        error_message = (
            f"❌ {hd.bold('KUNLIK HISOBOT OLINMADI')}\n\n"
            f"Xato: {error_details}\n\n"
            f"ℹ️ Iltimos, keyinroq urinib ko'ring."
        )
        await message.answer(error_message, parse_mode="HTML", reply_markup=get_balance_keyboard())

@courier_router.message(F.text == "📈 Haftalik hisobot")
async def handle_weekly_report(message: types.Message):
    """Haftalik hisobot"""
    user_id = str(message.from_user.id)
    logger.info(f"📈 'Haftalik hisobot' - User: {user_id}")
    
    await message.answer("⏳ Haftalik hisobot yuklanmoqda...")
    
    success, report_data = await client.get_courier_weekly_report(user_id)
    
    if success:
        report_text = format_weekly_report(report_data)
        await message.answer(report_text, parse_mode="HTML", reply_markup=get_balance_keyboard())
    else:
        error_details = report_data.get('error', 'Noma\'lum xato') if isinstance(report_data, dict) else str(report_data)
        error_message = (
            f"❌ {hd.bold('HAFTALIK HISOBOT OLINMADI')}\n\n"
            f"Xato: {error_details}\n\n"
            f"ℹ️ Iltimos, keyinroq urinib ko'ring."
        )
        await message.answer(error_message, parse_mode="HTML", reply_markup=get_balance_keyboard())

@courier_router.message(F.text == "📉 Oylik hisobot")
async def handle_monthly_report(message: types.Message):
    """Oylik hisobot"""
    user_id = str(message.from_user.id)
    logger.info(f"📉 'Oylik hisobot' - User: {user_id}")
    
    await message.answer("⏳ Oylik hisobot yuklanmoqda...")
    
    success, report_data = await client.get_courier_monthly_report(user_id)
    
    if success:
        report_text = format_monthly_report(report_data)
        await message.answer(report_text, parse_mode="HTML", reply_markup=get_balance_keyboard())
    else:
        error_details = report_data.get('error', 'Noma\'lum xato') if isinstance(report_data, dict) else str(report_data)
        error_message = (
            f"❌ {hd.bold('OYLIK HISOBOT OLINMADI')}\n\n"
            f"Xato: {error_details}\n\n"
            f"ℹ️ Iltimos, keyinroq urinib ko'ring."
        )
        await message.answer(error_message, parse_mode="HTML", reply_markup=get_balance_keyboard())

@courier_router.message(F.text == "⭐ Mening reytingim")
async def handle_my_rating(message: types.Message):
    """Kuryer reytingini ko'rsatish"""
    user_id = str(message.from_user.id)
    logger.info(f"⭐ 'Mening reytingim' - User: {user_id}")
    
    rating_text = (
        f"⭐ {hd.bold('MENING REYTINGIM')}\n\n"
        f"📊 {hd.bold('Umumiy reyting:')} ☆☆☆☆☆\n"
        f"👥 {hd.bold('Sharhlar:')} 0 ta\n"
        f"🏆 {hd.bold('Daraja:')} Yangi kuryer\n\n"
        f"🎯 {hd.bold('Keyingi daraja:')} 4.0 reyting\n"
        f"📈 {hd.bold('Yetishmaslik:')} 4.0 ball\n\n"
        f"―――――――――――――――――――――\n"
        f"ℹ️ Hozircha reyting ma'lumotlari mavjud emas."
    )
    
    await message.answer(rating_text, parse_mode="HTML", reply_markup=get_main_keyboard())

@courier_router.message(F.text == "🔄 Yangilash")
async def handle_refresh(message: types.Message, state: FSMContext):
    """Ma'lumotlarni yangilash"""
    user_id = str(message.from_user.id)
    logger.info(f"🔄 'Yangilash' - User: {user_id}")
    
    await message.answer("⏳ Ma'lumotlar yangilanmoqda...")
    
    # Kuryer mavjudligini qayta tekshirish
    check_success, check_data = await client.check_courier_exists(user_id)
    
    if check_success:
        if check_data.get('exists'):
            # Kuryer to'liq ma'lumotlarini olish
            courier_success, courier_data = await client.get_courier_info(user_id)
            
            if courier_success and courier_data:
                await state.update_data(courier_info=courier_data)
                
                success_message = (
                    f"🔄 {hd.bold('YANGILASH MUVAFFAQIYATLI')}\n\n"
                    f"✅ Barcha ma'lumotlar yangilandi.\n"
                    f"✅ Profil faolligi tasdiqlandi.\n\n"
                    f"👤 {hd.bold('Kuryer:')} {courier_data.get('name', 'Kuryer')}\n"
                    f"🆔 {hd.bold('Telegram ID:')} {user_id}\n\n"
                    f"ℹ️ Endi barcha bo'limlardan to'liq foydalanishingiz mumkin."
                )
            else:
                success_message = (
                    f"🔄 {hd.bold('YANGILASH MUVAFFAQIYATLI')}\n\n"
                    f"✅ Profil faolligi tasdiqlandi.\n"
                    f"👤 Kuryer: {check_data.get('courier_name', 'Kuryer')}\n\n"
                    f"ℹ️ To'liq ma'lumotlar hozircha mavjud emas."
                )
            
            await message.answer(success_message, parse_mode="HTML", reply_markup=get_main_keyboard())
        else:
            error_message = (
                f"❌ {hd.bold('YANGILASH MUVAFFAQIYATSIZ')}\n\n"
                f"⚠️ Profil ma'lumotlari topilmadi.\n\n"
                f"ℹ️ Siz kuryerlar ro'yxatida yo'qsiz.\n"
                f"Agar kuryer bo'lishni istasangiz, admin bilan bog'lanishingiz kerak."
            )
            await message.answer(error_message, parse_mode="HTML", reply_markup=get_main_keyboard())
    else:
        error_message = (
            f"❌ {hd.bold('YANGILASH MUVAFFAQIYATSIZ')}\n\n"
            f"⚠️ Profil ma'lumotlari topilmadi yoki xatolik yuz berdi.\n\n"
            f"{hd.bold('Tavsiyalar:')}\n"
            f"1. Internet aloqangizni tekshiring\n"
            f"2. Botni qayta ishga tushuring (/start)\n"
            f"3. Admin bilan bog'lanishingiz mumkin"
        )
        await message.answer(error_message, parse_mode="HTML", reply_markup=get_main_keyboard())

@courier_router.message(F.text == "⬅️ Orqaga")
async def handle_back(message: types.Message, state: FSMContext):
    """Orqaga qaytish"""
    current_state = await state.get_state()
    
    if current_state:
        await state.set_state(CourierStates.main_menu)
    
    await message.answer("Asosiy kuryer menyusi:", reply_markup=get_main_keyboard())

# ============================================================================
# ASOSIY BOT ISHGA TUSHIRISH
# ============================================================================

async def main():
    """Asosiy bot funksiyasi"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN topilmadi! Iltimos, environment variable ni o'rnating.")
        return
    
    logger.info(f"🤖 Bot ishga tushirilmoqda...")
    logger.info(f"📡 API URL: {API_BASE_URL}")
    
    try:
        # Bot va dispatcher yaratish
        bot = Bot(token=BOT_TOKEN)
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        
        # Routerlarni ulash
        dp.include_router(courier_router)
        
        logger.info("✅ Bot muvaffaqiyatli yaratildi")
        logger.info("🔄 Bot polling rejimida ishga tushirilmoqda...")
        
        # Botni ishga tushirish
        await dp.start_polling(bot, skip_updates=True)
        
    except Exception as e:
        logger.error(f"❌ Botni ishga tushirishda xatolik: {e}")
    finally:
        logger.info("👋 Bot to'xtatildi")

# ============================================================================
# ASOSIY ISHGA TUSHIRISH
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🚚 SHUKRONA SUV KURYER BOTI")
    print("="*50)
    print(f"📡 API URL: {API_BASE_URL}")
    print(f"🤖 Bot token: {BOT_TOKEN[:10]}...")
    print("="*50)
    print("📊 Bot ishga tushirilmoqda...")
    print("="*50 + "\n")
    
    # Botni ishga tushirish
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot foydalanuvchi tomonidan to'xtatildi")
    except Exception as e:
        logger.error(f"❌ Asosiy funksiyada xatolik: {e}")