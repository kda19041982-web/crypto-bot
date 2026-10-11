import asyncio
import logging
import os
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import web

# ================= Настройки бота =================
BOT_TOKEN = "8886277781:AAG1V4oG43FNCVco78cVbfMnRWDDKA2KreM"
CHAT_ID = 8273404618

CHECK_INTERVAL = 10  # Интервал проверки (в секундах)
PRICE_CHANGE_THRESHOLD = 0.8  # Порог изменения цены для алерта (%)
MIN_LIQ_USDT = 10000  # Минимальный объем ликвидации для алерта ($)

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    "SUIUSDT", "NEARUSDT", "APTUSDT", "FETUSDT", "PEPEUSDT"
]

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище состояний
price_states = {}
seen_liquidations = {}


# ================= Веб-сервер для Render =================
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


# ================= Вспомогательные функции =================
def get_recent_liquidations(symbol):
    url = f"https://fapi.binance.com/fapi/v1/forceOrders?symbol={symbol}&limit=10"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logging.error(f"Ошибка получения ликвидаций для {symbol}: {e}")
    return []


def get_current_price(symbol):
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return float(response.json()['price'])
    except Exception as e:
        logging.error(f"Ошибка получения цены для {symbol}: {e}")
    return None


# ================= Команды Telegram =================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🚀 **Крипто-Монитор Бот запущен!**\n\n"
        "Бот отслеживает резкие скачки цен и крупные ликвидации на Binance Futures.",
        parse_mode="Markdown"
    )

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    await message.answer("✅ Бот работает стабильно 24/7!", parse_mode="Markdown")


# ================= Фоновый мониторинг =================
async def price_checker():
    logging.info("Запуск фонового мониторинга цен...")
    while True:
        try:
            for symbol in SYMBOLS:
                current_price = get_current_price(symbol)
                if not current_price:
                    continue

                if symbol not in price_states:
                    price_states[symbol] = {
                        'last_price': current_price,
                        'local_high': current_price,
                        'local_low': current_price
                    }
                    continue

                state = price_states[symbol]
                last_price = state['last_price']
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
                                    f"💥 **КРУПНАЯ ЛИКВИДАЦИЯ ({symbol})!**\n"
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


# ================= Главная функция =================
async def main():
    asyncio.create_task(start_web_server())
    asyncio.create_task(price_checker())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
