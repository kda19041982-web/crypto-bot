import asyncio
import logging
import os
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

# ================= Конфигурация и Ключи =================
BOT_TOKEN = "8886277781:AAG1V4oG43FNCVco78cVbfMnRWDDKA2KreM"
CHAT_ID = 8273404618

# Параметры мониторинга
CHECK_INTERVAL = 10             # Интервал проверки рынка (сек)
PRICE_CHANGE_THRESHOLD = 0.8    # Порог резкого скачка цены (%)
MIN_LIQ_USDT = 10000            # Минимальный объем ликвидации ($)

# Список отслеживаемых пар по умолчанию
SYMBOLS = [
    "BTCUSDT"
]

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилища состояний и уровней
price_states = {}
seen_liquidations = {}
custom_levels = {}  # { 'BTCUSDT': [{'price': 95000, 'once': False, 'id': 1}] }
level_id_counter = 1


# ================= Встроенный веб-сервер для Render =================
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Crypto Monitoring Bot v6 is Live!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Веб-сервер Render запущен на порту {port}")


# ================= Модуль работы с Binance API =================
def get_current_price(symbol):
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return float(res.json()['price'])
    except Exception as e:
        logging.error(f"Ошибка получения цены {symbol}: {e}")
    return None


def get_recent_liquidations(symbol):
    url = f"https://fapi.binance.com/fapi/v1/forceOrders?symbol={symbol}&limit=20"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        logging.error(f"Ошибка получения ликвидаций {symbol}: {e}")
    return []


# ================= Клавиатуры (Кнопки) =================
def get_main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Активные уровни", callback_data="btn_levels")
    builder.button(text="📊 Статус системы", callback_data="btn_status")
    builder.button(text="🗑 Очистить всё", callback_data="btn_clear")
    builder.adjust(2, 1)
    return builder.as_markup()


# ================= Обработка Команд и Кнопок =================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        "Крипто-Монитор Бот v6.0 запущен!\n\n"
        "Интерактивное управление и кнопки активированы:\n"
        "- Управление ценовыми уровнями через команды или меню\n"
        "- Контроль резких импульсов цены (от 0.8%)\n"
        "- Фильтрация крупных ликвидаций (от $10k)\n\n"
        "Команды:\n"
        "/add BTCUSDT 95000 - Постоянный алерт\n"
        "/add_once BTCUSDT 95000 - Одноразовый алерт\n"
        "/levels - Список уровней с номерами для удаления\n"
        "/clear - Очистить все уровни"
    )
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard())


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    active_levels_count = sum(len(v) for v in custom_levels.values())
    status_text = (
        "Система мониторинга активна (24/7)\n\n"
        f"Мониторится пар: {len(SYMBOLS)}\n"
        f"Активных пользовательских уровней: {active_levels_count}\n"
        f"Порог скачка: {PRICE_CHANGE_THRESHOLD}%\n"
        f"Мин. объем ликвидации: ${MIN_LIQ_USDT:,.0f}"
    )
    await message.answer(status_text, reply_markup=get_main_menu_keyboard())


@dp.message(Command("add"))
async def cmd_add_level(message: types.Message):
    global level_id_counter
    try:
        _, symbol, price = message.text.split()
        symbol = symbol.upper()
        price = float(price)
        
        if symbol not in custom_levels:
            custom_levels[symbol] = []
            
        custom_levels[symbol].append({'price': price, 'once': False, 'id': level_id_counter})
        level_id_counter += 1
        
        await message.answer(f"Добавлен постоянный алерт: {symbol} на уровень {price}", reply_markup=get_main_menu_keyboard())
    except Exception:
        await message.answer("Ошибка формата. Пример: /add BTCUSDT 95000")


@dp.message(Command("add_once"))
async def cmd_add_once_level(message: types.Message):
    global level_id_counter
    try:
        _, symbol, price = message.text.split()
        symbol = symbol.upper()
        price = float(price)
        
        if symbol not in custom_levels:
            custom_levels[symbol] = []
            
        custom_levels[symbol].append({'price': price, 'once': True, 'id': level_id_counter})
        level_id_counter += 1
        
        await message.answer(f"Добавлен одноразовый алерт: {symbol} на уровень {price}", reply_markup=get_main_menu_keyboard())
    except Exception:
        await message.answer("Ошибка формата. Пример: /add_once BTCUSDT 95000")


@dp.message(Command("levels"))
async def cmd_show_levels(message: types.Message):
    if not custom_levels or all(len(v) == 0 for v in custom_levels.values()):
        await message.answer("Нет активных отслеживаемых уровней.", reply_markup=get_main_menu_keyboard())
        return
        
    text = "Активные уровни (нажми кнопку ниже для удаления нужного):\n\n"
    builder = InlineKeyboardBuilder()
    
    idx = 1
    for sym, lvl_list in custom_levels.items():
        if lvl_list:
            text += f"*{sym}*:\n"
            for item in lvl_list:
                mode = "🕯 Пост." if not item['once'] else "⚡ Однор."
                text += f"  {idx}. Уровень: `{item['price']}` USDT ({mode})\n"
                
                builder.button(text=f"❌ Удалить #{idx} ({item['price']})", callback_data=f"del_lvl_{item['id']}")
                idx += 1
                
    builder.button(text="🗑 Очистить всё", callback_data="btn_clear")
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@dp.message(Command("clear"))
async def cmd_clear_levels(message: types.Message):
    custom_levels.clear()
    await message.answer("Все пользовательские уровни очищены.", reply_markup=get_main_menu_keyboard())


# ================= Обработка нажатий на инлайн-кнопки =================
@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    data = callback.data
    
    if data == "btn_levels":
        if not custom_levels or all(len(v) == 0 for v in custom_levels.values()):
            await callback.message.edit_text("Нет активных отслеживаемых уровней.", reply_markup=get_main_menu_keyboard())
            return
            
        text = "Активные уровни:\n\n"
        builder = InlineKeyboardBuilder()
        idx = 1
        for sym, lvl_list in custom_levels.items():
            if lvl_list:
                text += f"*{sym}*:\n"
                for item in lvl_list:
                    mode = "Постоянный" if not item['once'] else "Одноразовый"
                    text += f"  {idx}. Уровень: `{item['price']}` USDT ({mode})\n"
                    builder.button(text=f"❌ Удалить #{idx} ({item['price']})", callback_data=f"del_lvl_{item['id']}")
                    idx += 1
        builder.button(text="🗑 Очистить всё", callback_data="btn_clear")
        builder.adjust(1)
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

    elif data == "btn_status":
        active_levels_count = sum(len(v) for v in custom_levels.values())
        status_text = (
            "Система мониторинга активна (24/7)\n\n"
            f"Мониторится пар: {len(SYMBOLS)}\n"
            f"Активных пользовательских уровней: {active_levels_count}\n"
            f"Порог скачка: {PRICE_CHANGE_THRESHOLD}%\n"
            f"Мин. объем ликвидации: ${MIN_LIQ_USDT:,.0f}"
        )
        await callback.message.edit_text(status_text, reply_markup=get_main_menu_keyboard())

    elif data == "btn_clear":
        custom_levels.clear()
        await callback.message.edit_text("Все пользовательские уровни успешно очищены.", reply_markup=get_main_menu_keyboard())

    elif data.startswith("del_lvl_"):
        target_id = int(data.split("_")[2])
        removed = False
        for sym in list(custom_levels.keys()):
            custom_levels[sym] = [lvl for lvl in custom_levels[sym] if lvl['id'] != target_id]
            if not custom_levels[sym]:
                del custom_levels[sym]
            removed = True
            
        if removed:
            await callback.answer("Уровень удален!")
            if not custom_levels or all(len(v) == 0 for v in custom_levels.values()):
                await callback.message.edit_text("Все уровни удалены. Список пуст.", reply_markup=get_main_menu_keyboard())
            else:
                text = "Активные уровни:\n\n"
                builder = InlineKeyboardBuilder()
                idx = 1
                for sym, lvl_list in custom_levels.items():
                    if lvl_list:
                        text += f"*{sym}*:\n"
                        for item in lvl_list:
                            mode = "Постоянный" if not item['once'] else "Одноразовый"
                            text += f"  {idx}. Уровень: `{item['price']}` USDT ({mode})\n"
                            builder.button(text=f"❌ Удалить #{idx} ({item['price']})", callback_data=f"del_lvl_{item['id']}")
                            idx += 1
                builder.button(text="🗑 Очистить всё", callback_data="btn_clear")
                builder.adjust(1)
                await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        else:
            await callback.answer("Уровень не найден.")

    await callback.answer()


# ================= Основной Фоновый Цикл =================
async def price_checker():
    logging.info("Запуск фонового мониторинга с инлайн-управлением...")
    while True:
        try:
            for symbol in SYMBOLS:
                current_price = get_current_price(symbol)
                if not current_price:
                    continue

                if symbol not in price_states:
                    price_states[symbol] = {'last_price': current_price}
                    continue

                last_price = price_states[symbol]['last_price']
                
                # 1. Проверка резкого импульса цены
                price_diff_percent = ((current_price - last_price) / last_price) * 100
                if abs(price_diff_percent) >= PRICE_CHANGE_THRESHOLD:
                    dir_icon = "📈 ↑" if price_diff_percent > 0 else "📉 ↓"
                    await bot.send_message(
                        CHAT_ID,
                        f"⚡️ РЕЗКИЙ ИМПУЛЬС ({symbol})!\n"
                        f"Движение: {dir_icon} {price_diff_percent:.2f}%\n"
                        f"Текущая цена: {current_price} USDT",
                        reply_markup=get_main_menu_keyboard()
                    )
                    price_states[symbol]['last_price'] = current_price

                # 2. Проверка пользовательских уровней
                if symbol in custom_levels and custom_levels[symbol]:
                    to_remove = []
                    for lvl in custom_levels[symbol]:
                        target_price = lvl['price']
                        if (last_price < target_price <= current_price) or (last_price > target_price >= current_price):
                            await bot.send_message(
                                CHAT_ID,
                                f"🎯 ДОСТИГНУТ УРОВЕНЬ ({symbol})!\n"
                                f"Цель: {target_price} USDT\n"
                                f"Цена: {current_price} USDT",
                                reply_markup=get_main_menu_keyboard()
                            )
                            if lvl['once']:
                                to_remove.append(lvl)
                    
                    for item in to_remove:
                        custom_levels[symbol].remove(item)

                # 3. Фильтрация и оповещение по крупным ликвидациям
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
                                side = liq['side']
                                side_text = "🟢 СБРИТЫ ШОРТЫ (Ликвидация продавцов)" if side == 'BUY' else "🔴 СБРИТЫ ЛОНГИ (Лонговая ликвидация)"
                                await bot.send_message(
                                    CHAT_ID,
                                    f"💥 КРУПНАЯ ЛИКВИДАЦИЯ ({symbol})!\n"
                                    f"{side_text}\n"
                                    f"- Цена: {price} USDT\n"
                                    f"- Объем: ${usdt_val:,.0f}",
                                    reply_markup=get_main_menu_keyboard()
                                )

                    if len(seen_liquidations[symbol]) > 100:
                        seen_liquidations[symbol] = set(list(seen_liquidations[symbol])[-50:])

                price_states[symbol]['last_price'] = current_price

        except Exception as e:
            logging.error(f"Ошибка в фоновом цикле: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


# ================= Точка Входа =================
async def main():
    asyncio.create_task(start_web_server())
    asyncio.create_task(price_checker())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
