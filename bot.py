import asyncio
import logging
import requests
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8886277781:AAG1V4oG43FNCVco78cVbfMnRWDDKA2KreM"
CHAT_ID = 8273404618
CHECK_INTERVAL = 10           # Интервал проверки в секундах
PRICE_JUMP_THRESHOLD = 5.0    # Процент резкого скачка цены
MIN_LIQ_USDT = 10000          # Минимальный объем ликвидации в USDT для алерта
# ===================================================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Ручные алерты по уровням
alerts_list = []
next_alert_id = 1

# Автомониторинг монет и кэш уже отправленных ликвидаций
watchlist = {}
seen_liquidations = {}

def get_binance_ticker_data(symbol: str):
    """Получает детальные данные по тикеру с Binance 24hr API"""
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {
                'price': float(data['lastPrice']),
                'volume': float(data['quoteVolume']),
                'high': float(data['highPrice']),
                'low': float(data['lowPrice']),
                'price_change_percent': float(data['priceChangePercent'])
            }
    except Exception as e:
        logging.error(f"Ошибка запроса тикера {symbol}: {e}")
    return None

def get_binance_price(symbol: str):
    data = get_binance_ticker_data(symbol)
    return data['price'] if data else None

def get_recent_liquidations(symbol: str):
    """Запрашивает последние ликвидации с фьючерсного рынка Binance"""
    url = f"https://fapi.binance.com/fapi/v1/allForceOrders?symbol={symbol.upper()}&limit=5"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        pass
    return []

# --- КЛАВИАТУРЫ ---

def get_main_menu_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📜 Мои алерты", callback_data="menu_alerts"),
            InlineKeyboardButton(text="⚡️ Автомониторинг", callback_data="menu_watch")
        ],
        [
            InlineKeyboardButton(text="ℹ️ Помощь по командам", callback_data="menu_help")
        ]
    ])
    return keyboard

@dp.message(Command("start", "menu"))
async def cmd_start(message: Message):
    text = (
        "📊 **Крипто-Алерт Бот v7.0 (с кнопками) запущен!**\n\n"
        "Выбери нужный раздел с помощью меню ниже или продолжай использовать команды."
    )
    await message.answer(text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

@dp.callback_query(F.data == "menu_main")
async def cb_menu_main(callback: CallbackQuery):
    text = "📊 **Главное меню управления ботом:**"
    await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "menu_help")
async def cb_menu_help(callback: CallbackQuery):
    text = (
        "ℹ️ **Справка по командам:**\n\n"
        "• `/add BTCUSDT 95000` — постоянный алерт\n"
        "• `/add_once BTCUSDT 95000` — одноразовый алерт\n"
        "• `/watch MEGAUSDT` — добавить монету в автомониторинг\n"
        "• `/unwatch MEGAUSDT` — убрать из автомониторинга\n"
        "• `/price BTCUSDT` — текущая цена и объем"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_main")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "menu_alerts")
async def cb_menu_alerts(callback: CallbackQuery):
    if not alerts_list:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_main")]
        ])
        await callback.message.edit_text("📜 Список ручных алертов пуст.", reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()
        return

    text = "📜 **Активные ручные алерты:**\nНажми на кнопку нужного алерта, чтобы удалить его:"
    
    buttons = []
    for item in alerts_list:
        dir_icon = "📈 >=" if item['direction'] == 'above' else "📉 <="
        btn_text = f"❌ Удалить #{item['id']} ({item['symbol']} {dir_icon} {item['level']})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"del_alert_{item['id']}")])
    
    buttons.append([InlineKeyboardButton(text="🗑 Очистить все", callback_data="del_all_alerts")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_main")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("del_alert_"))
async def cb_del_alert(callback: CallbackQuery):
    global alerts_list
    alert_id = int(callback.data.split("_")[2])
    
    initial_length = len(alerts_list)
    alerts_list = [a for a in alerts_list if a['id'] != alert_id]
    
    if len(alerts_list) < initial_length:
        await callback.answer(f"Алерт #{alert_id} удален!")
    else:
        await callback.answer(f"Алерт не найден.")
    
    # Обновляем список на экране
    await cb_menu_alerts(callback)

@dp.callback_query(F.data == "del_all_alerts")
async def cb_del_all_alerts(callback: CallbackQuery):
    global alerts_list
    alerts_list.clear()
    await callback.answer("Все ручные алерты удалены!")
    await cb_menu_alerts(callback)

@dp.callback_query(F.data == "menu_watch")
async def cb_menu_watch(callback: CallbackQuery):
    if not watchlist:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_main")]
        ])
        await callback.message.edit_text("⚡️ Список автомониторинга пуст. Добавь монеты через команду `/watch <тикер>`.", reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()
        return

    text = "⚡️ **Монеты в автомониторинге:**\nНажми, чтобы удалить монету из сканера:"
    
    buttons = []
    for symbol in watchlist.keys():
        current_p = get_binance_price(symbol)
        btn_text = f"❌ Убрать {symbol} ({current_p})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"unwatch_{symbol}")])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_main")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("unwatch_"))
async def cb_unwatch(callback: CallbackQuery):
    symbol = callback.data.split("_")[1]
    if symbol in watchlist:
        del watchlist[symbol]
        if symbol in seen_liquidations:
            del seen_liquidations[symbol]
        await callback.answer(f"Монета {symbol} удалена из мониторинга!")
    else:
        await callback.answer("Монета не найдена.")
    
    await cb_menu_watch(callback)

# --- РУЧНЫЕ КОМАНДЫ (ДУБЛИРУЮТ ФУНКЦИОНАЛ КНОПОК) ---

async def process_add(message: Message, is_once: bool = False):
    global next_alert_id
    args = message.text.split()
    if len(args) < 3:
        cmd_name = args[0] if args else "/add"
        await message.answer(f"❌ Формат: `{cmd_name} BTCUSDT 95000`", parse_mode="Markdown")
        return
    
    symbol = args[1].upper()
    try:
        target_price = float(args[2].replace(',', '.'))
    except ValueError:
        await message.answer("❌ Ошибка в формате цены. Пример: `95000` или `0.05`", parse_mode="Markdown")
        return

    current_price = get_binance_price(symbol)
    if current_price is None:
        await message.answer(f"❌ Не удалось найти тикер **{symbol}** на Binance.", parse_mode="Markdown")
        return

    direction = 'above' if target_price > current_price else 'below'
    mode_str = "одноразовый" if is_once else "постоянный"
    
    new_alert = {
        'id': next_alert_id,
        'symbol': symbol,
        'level': target_price,
        'direction': direction,
        'mode': 'once' if is_once else 'infinite'
    }
    
    alerts_list.append(new_alert)
    alert_id = next_alert_id
    next_alert_id += 1
    
    dir_str = "выше" if direction == 'above' else "ниже"
    await message.answer(
        f"✅ **Алерт #{alert_id} добавлен ({mode_str})!**\n"
        f"Тикер: `{symbol}`\n"
        f"Текущая цена: `{current_price}` USDT\n"
        f"Уведомить при пробитии уровня: `{target_price}` ({dir_str})",
        parse_mode="Markdown"
    )

@dp.message(Command("add"))
async def cmd_add(message: Message):
    await process_add(message, is_once=False)

@dp.message(Command("add_once"))
async def cmd_add_once(message: Message):
    await process_add(message, is_once=True)

@dp.message(Command("list"))
async def cmd_list(message: Message):
    if not alerts_list:
        await message.answer("📜 Список ручных алертов пуст.")
        return
    
    text = "📜 **Активные ручные алерты:**\n\n"
    for item in alerts_list:
        dir_icon = "📈 >=" if item['direction'] == 'above' else "📉 <="
        text += f"🔹 **#{item['id']}** | `{item['symbol']}` {dir_icon} `{item['level']}` USDT\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("delete"))
async def cmd_delete(message: Message):
    global alerts_list
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Укажи номер алерта. Пример: `/delete 1`", parse_mode="Markdown")
        return
    
    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("❌ Номер алерта должен быть числом.", parse_mode="Markdown")
        return
    
    initial_length = len(alerts_list)
    alerts_list = [a for a in alerts_list if a['id'] != target_id]
    
    if len(alerts_list) < initial_length:
        await message.answer(f"🗑 Алерт **#{target_id}** успешно удален.", parse_mode="Markdown")
    else:
        await message.answer(f"❌ Алерт с номером **#{target_id}** не найден.", parse_mode="Markdown")

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    alerts_list.clear()
    await message.answer("🗑 Все ручные алерты очищены.")

@dp.message(Command("watch"))
async def cmd_watch(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Укажи тикер. Пример: `/watch MEGAUSDT`", parse_mode="Markdown")
        return
    
    symbol = args[1].upper()
    data = get_binance_ticker_data(symbol)
    if not data:
        await message.answer(f"❌ Не удалось найти тикер **{symbol}** на Binance.", parse_mode="Markdown")
        return
    
    watchlist[symbol] = {
        'last_price': data['price'],
        'local_high': data['high'],
        'local_low': data['low']
    }
    seen_liquidations[symbol] = set()
    
    recent = get_recent_liquidations(symbol)
    if recent:
        for liq in recent:
            seen_liquidations[symbol].add(liq.get('time', 0))

    await message.answer(
        f"⚡️ **Монета добавлена в автомониторинг!**\n"
        f"Тикер: `{symbol}`\n"
        f"Текущая цена: `{data['price']}` USDT",
        parse_mode="Markdown"
    )

@dp.message(Command("unwatch"))
async def cmd_unwatch(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Укажи тикер. Пример: `/unwatch MEGAUSDT`", parse_mode="Markdown")
        return
    
    symbol = args[1].upper()
    if symbol in watchlist:
        del watchlist[symbol]
        if symbol in seen_liquidations:
            del seen_liquidations[symbol]
        await message.answer(f"🗑 Тикер `{symbol}` удален из автомониторинга.", parse_mode="Markdown")
    else:
        await message.answer(f"❌ Тикер `{symbol}` не найден в списке.", parse_mode="Markdown")

@dp.message(Command("watchlist"))
async def cmd_watchlist(message: Message):
    if not watchlist:
        await message.answer("⚡️ Список автомониторинга пуст. Добавь монеты через `/watch <тикер>`.")
        return
    
    text = "⚡️ **Монеты в автомониторинге:**\n\n"
    for symbol in watchlist.keys():
        current_p = get_binance_price(symbol)
        text += f"• `{symbol}` (Цена: `{current_p}` USDT)\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("price"))
async def cmd_price(message: Message):
    args = message.text.split()
    symbol = args[1].upper() if len(args) > 1 else "BTCUSDT"
    data = get_binance_ticker_data(symbol)
    if data:
        await message.answer(
            f"💵 Цена **{symbol}**:\n"
            f"• Текущая: `{data['price']}` USDT\n"
            f"• Изменение за 24ч: `{data['price_change_percent']}%`\n"
            f"• Объем за 24ч: `{data['volume']:,.2f}` USDT\n"
            f"• Хай / Лоу: `{data['high']}` / `{data['low']}`",
            parse_mode="Markdown"
        )
    else:
        await message.answer(f"❌ Тикер {symbol} не найден.")

# --- ФОНОВЫЙ ЦИКЛ ПРОВЕРОК ---

async def price_checker():
    global alerts_list
    while True:
        try:
            if alerts_list:
                triggered_ids = []
                for item in alerts_list:
                    symbol = item['symbol']
                    current_price = get_binance_price(symbol)
                    if current_price is None:
                        continue
                    
                    target = item['level']
                    direction = item['direction']
                    
                    is_triggered = (direction == 'above' and current_price >= target) or \
                                   (direction == 'below' and current_price <= target)
                    
                    if is_triggered:
                        await bot.send_message(
                            CHAT_ID,
                            f"🚨 **УРОВЕНЬ ПРОБИТ ({symbol} #{item['id']})!**\n"
                            f"Цена {'выше' if direction == 'above' else 'ниже'} уровня `{target}` USDT!\n"
                            f"Текущая цена: `{current_price}` USDT",
                            parse_mode="Markdown"
                        )
                        if item['mode'] == 'once':
                            triggered_ids.append(item['id'])
                
                if triggered_ids:
                    alerts_list = [a for a in alerts_list if a['id'] not in triggered_ids]

            if watchlist:
                for symbol in list(watchlist.keys()):
                    data = get_binance_ticker_data(symbol)
                    if not data:
                        continue
                    
                    current_price = data['price']
                    state = watchlist[symbol]
                    
                    price_diff_percent = ((current_price - state['last_price']) / state['last_price']) * 100
                    if abs(price_diff_percent) >= PRICE_JUMP_THRESHOLD:
                        dir_icon = "📈 ВВЕРХ" if price_diff_percent > 0 else "📉 ВНИЗ"
                        await bot.send_message(
                            CHAT_ID,
                            f"⚡️ **РЕЗКИЙ СКАЧОК ЦЕНЫ ({symbol})!**\n"
                            f"Движение: {dir_icon} на **{price_diff_percent:.2f}%**\n"
                            f"Новая цена: `{current_price}` USDT",
                            parse_mode="Markdown"
                        )
                        state['last_price'] = current_price

                    if current_price > state['local_high']:
                        state['local_high'] = current_price
                        await bot.send_message(
                            CHAT_ID,
                            f"🚀 **ОБНОВЛЕНИЕ МАКСИМУМА ({symbol})!**\n"
                            f"Новый хай: `{current_price}` USDT!",
                            parse_mode="Markdown"
                        )
                    elif current_price < state['local_low']:
                        state['local_low'] = current_price
                        await bot.send_message(
                            CHAT_ID,
                            f"⚠️ **ОБНОВЛЕНИЕ МИНИМУМА ({symbol})!**\n"
                            f"Новый лоу: `{current_price}` USDT!",
                            parse_mode="Markdown"
                        )

                    liquidations = get_recent_liquidations(symbol)
                    if liquidations:
                        if symbol not in seen_liquidations:
                            seen_liquidations[symbol] = set()
                        
                        for liq in liquidations:
                            liq_id = liq.get('time', 0)
                            if liq_id not in seen_liquidations[symbol]:
                                seen_liquidations[symbol].add(liq_id)
                                
                                price = float(liq['price'])
                                usdt_val = price * float(liq['origQty'])
                                
                                if usdt_val >= MIN_LIQ_USDT:
                                    side_text = "🟢 ШОРТЫ СБРИТЫ (Ликвидация продавцов)" if liq['side'] == 'BUY' else "🔴 ЛОНГОВЫЕ ЛИКВИДАЦИИ"
                                    await bot.send_message(
                                        CHAT_ID,
                                        f"💥 **КРУПНАЯ ЛИКВИДАЦИЯ ({symbol})!**\n\n"
                                        f"{side_text}\n"
                                        f"• Цена: `{price}` USDT\n"
                                        f"• Объем сбритых позиций: **${usdt_val:,.0f}**",
                                        parse_mode="Markdown"
                                    )
                        
                        if len(seen_liquidations[symbol]) > 50:
                            seen_liquidations[symbol] = set(list(seen_liquidations[symbol])[-20:])

        except Exception as e:
            logging.error(f"Ошибка в фоновом цикле автомониторинга: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

async def main():
    asyncio.create_task(price_checker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
