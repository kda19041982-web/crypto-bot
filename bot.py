import asyncio
import logging
import os
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import web

# ================= Конфигурация и Ключи =================
BOT_TOKEN = "8886277781:AAG1V4oG43FNCVco78cVbfMnRWDDKA2KreM"
CHAT_ID = 8273404618

# Параметры мониторинга (Шестая версия)
CHECK_INTERVAL = 10             # Интервал проверки рынка (сек)
PRICE_CHANGE_THRESHOLD = 0.8    # Порог резкого скачка цены (%)
MIN_LIQ_USDT = 10000            # Минимальный объем ликвидации ($)

# Список отслеживаемых пар
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    "SUIUSDT", "NEARUSDT", "APTUSDT", "FETUSDT", "PEPEUSDT"
]

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище состояний и пользовательских уровней (Вариант 6)
price_states = {}
seen_liquidations = {}
custom_levels = {}  # { 'BTCUSDT': [{'price': 95000, 'once': False, 'user_id': 8273404618}] }


# ================= Встроенный веб-сервер для Render =================
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Crypto Monitoring Bot v6 is Live!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Веб-сервер Render успешно запущен на порту {port}")


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
    url = f"https://fapi.binance.com/fapi/v1/forceOrders?symbol={symbol}&limit=10"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        logging.error(f"Ошибка получения ликвидаций {symbol}: {e}")
    return []


# ================= Обработка Команд (Вариант 6) =================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        "🚀 **Крипто-Монитор Бот v6.0 запущен!**\n\n"
        "**Доступные возможности:**\n"
        "• Отслеживание резких импульсов и скачков цен\n"
        "• Обновление локальных максимумов и минимумов\n"
        "• Фильтрация крупных ликвидаций (сбритые шорты/лонги)\n"
        "• Ручные алерты по ценовым уровням\n\n"
        "**Команды управления уровнями:**\n"
        "`/add BTCUSDT 95000` — Постоянный алерт при пересечении уровня\n"
        "`/add_once BTCUSDT 95000` — Одноразовый алерт по уровню\n"
        "`/levels` — Посмотреть активные уровни\n"
        "`/clear` — Очистить все сохраненные уровни\n"
        "`/status` — Проверить работоспособность системы"
    )
    await message.answer(welcome_text, parse_mode="Markdown")


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    active_levels_count = sum(len(v) for v in custom_levels.values())
    status_text = (
        "✅ **Система работает в штатном режиме 24/7**\n\n"
        f"• Мониторится монет: `{len(SYMBOLS)}`\n"
        f"• Активных уровней: `{active_levels_count}`\n"
        f"• Порог скачка цены: `{PRICE_CHANGE_THRESHOLD}%`\n"
        f"• Мин. объем ликвидации: `${MIN_LIQ_USDT:,.0f}`"
    )
    await message.answer(status_text, parse_mode="Markdown")


@dp.message(Command("add"))
async def cmd_add_level(message: types.Message):
    try:
        _, symbol, price = message.text.split()
        symbol = symbol.upper()
        price = float(price)
        
        if symbol not in custom_levels:
            custom_levels[symbol] = []
            
        custom_levels[symbol].append({'price': price, 'once': False, 'user_id': message.from_user.id})
        await message.answer(f"✅ Добавлен постоянный алерт: **{symbol}** на уровень `{price}`", parse_mode="Markdown")
    except Exception:
        await message.answer("❌ Ошибка. Формат: `/add BTCUSDT 95000`", parse_mode="Markdown")


@dp.message(Command("add_once"))
async def cmd_add_once_level(message: types.Message):
    try:
        _, symbol, price = message.text.split()
        symbol = symbol.upper()
        price = float(price)
        
        if symbol not in custom_levels:
            custom_levels[symbol] = []
            
        custom_levels[symbol].append({'price': price, 'once': True, 'user_id': message.from_user.id})
        await message.answer(f"🎯 Добавлен одноразовый алерт: **{symbol}** на уровень `{price}`", parse_mode="Markdown")
    except Exception:
        await message.answer("❌ Ошибка. Формат: `/add_once BTCUSDT 95000`", parse_mode="Markdown")


@dp.message(Command("levels"))
async def cmd_show_levels(message: types.Message):
    if not custom_levels or all(len(v) == 0 for v in custom_levels.values()):
        await message.answer("📋 У вас пока нет активных отслеживаемых уровней.", parse_mode="Markdown")
        return
        
    text = "📋 **Ваши отслеживаемые уровни:**\n\n"
    for sym, lvl_list in custom_levels.items():
        if lvl_list:
            text += f"**{sym}**:\n"
            for item in lvl_list:
                mode = "Одноразовый" if item['once'] else "Постоянный"
                text += f"  • `{item['price']}` USDT ({mode})\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("clear"))
async def cmd_clear_levels(message: types.Message):
    custom_levels.clear()
    await message.answer("🗑 Все пользовательские уровни успешно удалены.", parse_mode="Markdown")


# ================= Основной Фоновый Цикл Мониторинга (Вариант 6) =================
async def price_checker():
    logging.info("Запуск фонового мониторинга цен и уровней...")
    while True:
        try:
            for symbol in SYMBOLS:
                current_price = get_current_price(symbol)
                if not current_price:
                    continue

                # Инициализация первого значения
                if symbol not in price_states:
                    price_states[symbol] = {
                        'last_price': current_price,
                        'local_high': current_price,
                        'local_low': current_price
                    }
                    continue

                state = price_states[symbol]
                last_price = state['last_price']
                
                # 1. Проверка резкого импульса цены
                price_diff_percent = ((current_price - last_price) / last_price) * 100
                if abs(price_diff_percent) >= PRICE_CHANGE_THRESHOLD:
                    dir_icon = "🟢 ↑" if price_diff_percent > 0 else "🔴 ↓"
                    await bot.send_message(
                        CHAT_ID,
                        f"⚡️ **РЕЗКИЙ СКАЧОК ЦЕНЫ ({symbol})!**\n"
                        f"Движение: {dir_icon} **{price_diff_percent:.2f}%**\n"
                        f"Новая цена: `{current_price}` USDT",
                        parse_mode="Markdown"
                    )
                    state['last_price'] = current_price

                # 2. Обновление максимумов и минимумов
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

                # 3. Проверка пользовательских уровней (/add и /add_once)
                if symbol in custom_levels and custom_levels[symbol]:
                    to_remove = []
                    for lvl in custom_levels[symbol]:
                        target_price = lvl['price']
                        # Проверка пересечения уровня вверх или вниз
                        if (last_price < target_price <= current_price) or (last_price > target_price >= current_price):
                            await bot.send_message(
                                CHAT_ID,
                                f"🎯 **ДОСТИГНУТ ВАШ УРОВЕНЬ ({symbol})!**\n"
                                f"Целевой уровень: `{target_price}` USDT\n"
                                f"Текущая цена: `{current_price}` USDT",
                                parse_mode="Markdown"
                            )
                            if lvl['once']:
                                to_remove.append(lvl)
                    
                    for item in to_remove:
                        custom_levels[symbol].remove(item)

                # 4. Проверка сбритых позиций и крупных ликвидаций
                liquidations = get_recent_liquidations(symbol)
                if liquidations:
                    if symbol not in seen_liquidations:
                        seen_liquidations[symbol] = set()

                    for liq in liquidations:
                        liq_id = liq.get('time', 0)
                        if liq_id not in seen_liquidations[symbol]:
                            seen_liquidations[symbol].add(liq_id)

                            price = float(liq['price'])
                            usdt_
