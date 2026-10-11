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

# Параметры мониторинга
CHECK_INTERVAL = 10             # Интервал проверки рынка (сек)
PRICE_CHANGE_THRESHOLD = 0.8    # Порог резкого скачка цены (%)
MIN_LIQ_USDT = 10000            # Минимальный объем ликвидации ($)

# Список отслеживаемых пар (оставлен только биткоин)
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

# Хранилище состояний и пользовательских уровней
price_states = {}
seen_liquidations = {}
custom_levels = {}


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
    url = f"https://fapi.binance.com/fapi/v1/forceOrders?symbol={symbol}&limit=10"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        logging.error(f"Ошибка получения ликвидаций {symbol}: {e}")
    return []


# ================= Обработка Команд =================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        "Крипто-Монитор Бот v6.0 запущен!\n\n"
        "Возможности:\n"
        "- Сигналы по твоим кастомным уровням (/add, /add_once)\n"
        "- Отслеживание резких скачков цены (от 0.8%)\n"
        "- Фильтрация крупных ликвидаций (от $10,000)\n\n"
        "Команды:\n"
        "/add BTCUSDT 95000 - Постоянный алерт по уровню\n"
        "/add_once BTCUSDT 95000 - Одноразовый алерт по уровню\n"
        "/levels - Просмотр твоих активных уровней\n"
        "/clear - Удалить все уровни\n"
        "/status - Статус работы бота"
    )
    await message.answer(welcome_text)


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    active_levels_count = sum(len(v) for v in custom_levels.values())
    status_text = (
        "Система работает 24/7 без спама\n\n"
        f"Мониторится монет: {len(SYMBOLS)}\n"
        f"Активных твоих уровней: {active_levels_count}\n"
        f"Порог скачка цены: {PRICE_CHANGE_THRESHOLD}%\n"
        f"Мин. объем ликвидации: ${MIN_LIQ_USDT:,.0f}"
    )
    await message.answer(status_text)


@dp.message(Command("add"))
async def cmd_add_level(message: types.Message):
    try:
        _, symbol, price = message.text.split()
        symbol = symbol.upper()
        price = float(price)
        
        if symbol not in custom_levels:
            custom_levels[symbol] = []
            
        custom_levels[symbol].append({'price': price, 'once': False, 'user_id': message.from_user.id})
        await message.answer(f"Добавлен постоянный алерт: {symbol} на уровень {price}")
    except Exception:
        await message.answer("Ошибка формата. Пример: /add BTCUSDT 95000")


@dp.message(Command("add_once"))
async def cmd_add_once_level(message: types.Message):
    try:
        _, symbol, price = message.text.split()
        symbol = symbol.upper()
        price = float(price)
        
        if symbol not in custom_levels:
            custom_levels[symbol] = []
            
        custom_levels[symbol].append({'price': price, 'once': True, 'user_id': message.from_user.id})
        await message.answer(f"Добавлен одноразовый алерт: {symbol} на уровень {price}")
    except Exception:
        await message.answer("Ошибка формата. Пример: /add_once BTCUSDT 95000")


@dp.message(Command("levels"))
async def cmd_show_levels(message: types.Message):
    if not custom_levels or all(len(v) == 0 for v in custom_levels.values()):
        await message.answer("Нет активных отслеживаемых уровней.")
        return
        
    text = "Активные уровни:\n\n"
    for sym, lvl_list in custom_levels.items():
        if lvl_list:
            text += f"{sym}:\n"
            for item in lvl_list:
                mode = "Одноразовый" if item['once'] else "Постоянный"
                text += f"  - {item['price']} USDT ({mode})\n"
    await message.answer(text)


@dp.message(Command("clear"))
async def cmd_clear_levels(message: types.Message):
    custom_levels.clear()
    await message.answer("Все уровни очищены.")


# ================= Основной Фоновый Цикл =================
async def price_checker():
    logging.info("Запуск фонового мониторинга...")
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
                    dir_icon = "↑" if price_diff_percent > 0 else "↓"
                    await bot.send_message(
                        CHAT_ID,
                        f"РЕЗКИЙ СКАЧОК ЦЕНЫ ({symbol})!\n"
                        f"Движение: {dir_icon} {price_diff_percent:.2f}%\n"
                        f"Новая цена: {current_price} USDT"
                    )
                    price_states[symbol]['last_price'] = current_price

                # 2. Проверка кастомных уровней
                if symbol in custom_levels and custom_levels[symbol]:
                    to_remove = []
                    for lvl in custom_levels[symbol]:
                        target_price = lvl['price']
                        if (last_price < target_price <= current_price) or (last_price > target_price >= current_price):
                            await bot.send_message(
                                CHAT_ID,
                                f"ДОСТИГНУТ ВАШ УРОВЕНЬ ({symbol})!\n"
                                f"Целевой уровень: {target_price} USDT\n"
                                f"Текущая цена: {current_price} USDT"
                            )
                            if lvl['once']:
                                to_remove.append(lvl)
                    
                    for item in to_remove:
                        custom_levels[symbol].remove(item)

                # 3. Крупные ликвидации
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
                                side_text = "ШОРТЫ СБРИТЫ" if liq['side'] == 'BUY' else "ЛОНГОВЫЕ ЛИКВИДАЦИИ"
                                await bot.send_message(
                                    CHAT_ID,
                                    f"КРУПНАЯ ЛИКВИДАЦИЯ ({symbol})!\n"
                                    f"{side_text}\n"
                                    f"- Цена: {price} USDT\n"
                                    f"- Объем: ${usdt_val:,.0f}"
                                )

                    if len(seen_liquidations[symbol]) > 50:
                        seen_liquidations[symbol] = set(list(seen_liquidations[symbol])[-20:])

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
