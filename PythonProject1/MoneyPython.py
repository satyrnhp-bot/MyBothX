import telebot
from telebot import types
import requests
import json
from datetime import datetime, timedelta
import time
import pandas as pd
import numpy as np
import talib
import re
from bs4 import BeautifulSoup

# Конфигурация
API_KEY = "8181930295:AAGSrTLXw1NOrmMI5jc2mHRvqCpM5vqxWNM"
BINANCE_API_URL = "https://api.binance.com/api/v3"
NEWSAPI_KEY = "139bdc2a63884f8896552dc48ed16f91"  # Получить на https://newsapi.org
CRYPTO_COMPARE_KEY = "94246ce346bbe6fb3db96c8176e76268a8642be5842ee76ba6b762253504c385"  # Опционально

# Настройки уведомлений
price_alerts = {}  # {user_id: {symbol: {'threshold': 5.0, 'last_price': 10000}}}
alert_check_interval = 60  # Проверка каждые 60 секунд
last_alert_check = time.time()

# Инициализация бота
bot = telebot.TeleBot(API_KEY, parse_mode='HTML')

# База данных для хранения отслеживаемых активов
user_watchlist = {}

# Словарь для маппинга символов
CRYPTO_SYMBOLS = {
    'BTC': 'BTCUSDT', 'BITCOIN': 'BTCUSDT',
    'ETH': 'ETHUSDT', 'ETHEREUM': 'ETHUSDT',
    'BNB': 'BNBUSDT',
    'ADA': 'ADAUSDT', 'CARDANO': 'ADAUSDT',
    'XRP': 'XRPUSDT', 'RIPPLE': 'XRPUSDT',
    'DOGE': 'DOGEUSDT', 'DOGECOIN': 'DOGEUSDT',
    'DOT': 'DOTUSDT', 'POLKADOT': 'DOTUSDT',
    'SOL': 'SOLUSDT', 'SOLANA': 'SOLUSDT',
    'LTC': 'LTCUSDT', 'LITECOIN': 'LTCUSDT',
    'LINK': 'LINKUSDT', 'CHAINLINK': 'LINKUSDT',
    'MATIC': 'MATICUSDT', 'POLYGON': 'MATICUSDT',
    'AVAX': 'AVAXUSDT', 'AVALANCHE': 'AVAXUSDT',
    'ATOM': 'ATOMUSDT', 'COSMOS': 'ATOMUSDT',
    'UNI': 'UNIUSDT', 'UNISWAP': 'UNIUSDT',
}

# Ключевые слова для поиска влиятельных новостей
CRYPTO_KEYWORDS = [
    'bitcoin', 'ethereum', 'crypto', 'blockchain', 'defi', 'nft',
    'regulation', 'sec', 'sec', 'fed', 'interest rates', 'inflation',
    'elon musk', 'microsoft', 'google', 'amazon', 'apple', 'tesla',
    'china', 'india', 'eu', 'european union', 'ban', 'legal', 'law'
]


# --- Вспомогательные функции для работы с API ---

def safe_float(value, default=0.0):
    """Безопасное преобразование в float"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_str(value, default=""):
    """Безопасное преобразование в строку"""
    try:
        return str(value)
    except:
        return default


def normalize_symbol(symbol):
    """Нормализация символа криптовалюты"""
    symbol = symbol.upper().strip()

    if symbol.endswith('USDT') and len(symbol) > 4:
        return symbol

    if symbol in CRYPTO_SYMBOLS:
        return CRYPTO_SYMBOLS[symbol]

    if len(symbol) <= 4 and symbol.isalpha():
        return f"{symbol}USDT"

    return symbol


def setup_price_alert(user_id, symbol, threshold_percent):
    """Настройка уведомления для пользователя"""
    try:
        normalized_symbol = normalize_symbol(symbol)
        current_data = get_binance_price(normalized_symbol)

        if not current_data:
            return False, "Не удалось получить текущую цену"

        if user_id not in price_alerts:
            price_alerts[user_id] = {}

        price_alerts[user_id][normalized_symbol] = {
            'threshold': float(threshold_percent),
            'last_price': current_data['price'],
            'last_check': time.time()
        }

        return True, f"✅ Уведомление для {normalized_symbol} установлено на {threshold_percent}%"

    except Exception as e:
        print(f"Ошибка настройки уведомления: {e}")
        return False, "❌ Ошибка настройки уведомления"


def remove_price_alert(user_id, symbol):
    """Удаление уведомления"""
    try:
        normalized_symbol = normalize_symbol(symbol)

        if user_id in price_alerts and normalized_symbol in price_alerts[user_id]:
            del price_alerts[user_id][normalized_symbol]
            return True, f"✅ Уведомление для {normalized_symbol} удалено"

        return False, f"❌ Уведомление для {normalized_symbol} не найдено"

    except Exception as e:
        print(f"Ошибка удаления уведомления: {e}")
        return False, "❌ Ошибка удаления уведомления"


def check_price_alerts():
    """Проверка всех уведомлений о цене"""
    try:
        current_time = time.time()
        alerts_to_send = []

        for user_id, symbols in list(price_alerts.items()):
            for symbol, alert_data in list(symbols.items()):
                # Проверяем не чаще чем раз в 30 секунд для каждого символа
                if current_time - alert_data.get('last_check', 0) < 30:
                    continue

                current_data = get_binance_price(symbol)
                if not current_data:
                    continue

                current_price = current_data['price']
                last_price = alert_data['last_price']
                threshold = alert_data['threshold']

                # Рассчитываем изменение в процентах
                if last_price > 0:
                    price_change = ((current_price - last_price) / last_price) * 100

                    # Проверяем превышение порога
                    if abs(price_change) >= threshold:
                        alert_message = create_alert_message(symbol, current_price, price_change, threshold)
                        alerts_to_send.append((user_id, alert_message))

                        # Обновляем последнюю цену после уведомления
                        price_alerts[user_id][symbol]['last_price'] = current_price

                # Обновляем время последней проверки
                price_alerts[user_id][symbol]['last_check'] = current_time

        return alerts_to_send

    except Exception as e:
        print(f"Ошибка проверки уведомлений: {e}")
        return []


def create_alert_message(symbol, current_price, price_change, threshold):
    """Создание сообщения для уведомления"""
    change_emoji = "🟢" if price_change >= 0 else "🔴"
    direction = "рост" if price_change >= 0 else "падение"

    message = f"🚨 <b>ЦЕНОВОЕ УВЕДОМЛЕНИЕ: {symbol}</b>\n\n"
    message += f"{change_emoji} <b>Произошло резкое движение цены!</b>\n\n"
    message += f"💰 <b>Текущая цена:</b> ${current_price:,.4f}\n"
    message += f"📈 <b>Изменение:</b> {price_change:+.2f}%\n"
    message += f"🎯 <b>Порог уведомления:</b> {threshold}%\n"
    message += f"📊 <b>Направление:</b> {direction}\n\n"
    message += f"⏰ <i>{datetime.now().strftime('%H:%M:%S')}</i>"

    return message


def show_user_alerts(user_id):
    """Показать текущие уведомления пользователя"""
    if user_id not in price_alerts or not price_alerts[user_id]:
        return "📭 У вас нет активных уведомлений"

    message = "🔔 <b>ВАШИ АКТИВНЫЕ УВЕДОМЛЕНИЯ</b>\n\n"

    for symbol, alert_data in price_alerts[user_id].items():
        message += f"• {symbol}: {alert_data['threshold']}% изменение\n"

    message += "\n💡 <i>Используйте /alertadd и /alertremove для управления</i>"
    return message


@bot.message_handler(commands=['alertadd'])
def alert_add_command(message):
    """Добавление уведомления"""
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.send_message(message.chat.id,
                             "❌ Используйте: /alertadd BTC 5.0\n"
                             "Где 5.0 - процент изменения для уведомления")
            return

        symbol = parts[1]
        threshold = parts[2]

        success, result_msg = setup_price_alert(message.from_user.id, symbol, threshold)
        bot.send_message(message.chat.id, result_msg)

    except Exception as e:
        print(f"Ошибка в alert_add_command: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка добавления уведомления")


@bot.message_handler(commands=['alertremove'])
def alert_remove_command(message):
    """Удаление уведомления"""
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id,
                             "❌ Используйте: /alertremove BTC")
            return

        symbol = parts[1]
        success, result_msg = remove_price_alert(message.from_user.id, symbol)
        bot.send_message(message.chat.id, result_msg)

    except Exception as e:
        print(f"Ошибка в alert_remove_command: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка удаления уведомления")


@bot.message_handler(commands=['alerts'])
def alerts_list_command(message):
    """Список уведомлений"""
    try:
        alerts_text = show_user_alerts(message.from_user.id)
        bot.send_message(message.chat.id, alerts_text)

    except Exception as e:
        print(f"Ошибка в alerts_list_command: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка получения списка уведомлений")


# --- Функции для получения новостей ---

def get_crypto_news(limit=5):
    """Получение криптоновостей с CryptoPanic"""
    try:
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {
            'auth_token': 'YOUR_CRYPTOPANIC_TOKEN',  # Опционально
            'public': 'true',
            'kind': 'news',
            'filter': 'rising',
            'currencies': 'BTC,ETH,USDT'
        }

        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        news_items = []
        for item in data.get('results', [])[:limit]:
            news_items.append({
                'title': item.get('title', ''),
                'url': item.get('url', ''),
                'published_at': item.get('published_at', ''),
                'source': item.get('source', {}).get('title', ''),
                'votes': item.get('votes', {}).get('positive', 0)
            })

        return news_items

    except Exception as e:
        print(f"Ошибка получения криптоновостей: {e}")
        # Альтернативный источник - парсинг CoinDesk
        return get_alternative_crypto_news(limit)


def get_alternative_crypto_news(limit=5):
    """Альтернативный источник новостей (парсинг CoinDesk)"""
    try:
        url = "https://www.coindesk.com/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        news_items = []
        articles = soup.find_all('article', limit=limit)

        for article in articles:
            title_elem = article.find('h2') or article.find('h3') or article.find('h4')
            link_elem = article.find('a')

            if title_elem and link_elem:
                title = title_elem.get_text().strip()
                url = link_elem.get('href')
                if not url.startswith('http'):
                    url = 'https://www.coindesk.com' + url

                news_items.append({
                    'title': title,
                    'url': url,
                    'published_at': datetime.now().strftime('%Y-%m-%d'),
                    'source': 'CoinDesk',
                    'votes': 0
                })

        return news_items

    except Exception as e:
        print(f"Ошибка альтернативного источника новостей: {e}")
        return []


def get_political_news(limit=5):
    """Получение политических новостей с NewsAPI"""
    try:
        if not NEWSAPI_KEY or NEWSAPI_KEY == "ВАШ_NEWSAPI_КЛЮЧ":
            return get_alternative_political_news(limit)

        # Определяем дату за последние 2 дня
        from_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')

        url = "https://newsapi.org/v2/everything"
        params = {
            'apiKey': NEWSAPI_KEY,
            'q': 'crypto cryptocurrency bitcoin ethereum regulation',
            'language': 'en',
            'sortBy': 'publishedAt',
            'from': from_date,
            'pageSize': limit
        }

        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        news_items = []
        for article in data.get('articles', [])[:limit]:
            # Проверяем, относится ли новость к крипто или регулированию
            title = article.get('title', '').lower()
            description = article.get('description', '').lower()

            if any(keyword in title + description for keyword in CRYPTO_KEYWORDS):
                news_items.append({
                    'title': article.get('title', ''),
                    'url': article.get('url', ''),
                    'published_at': article.get('publishedAt', ''),
                    'source': article.get('source', {}).get('name', ''),
                    'description': article.get('description', '')
                })

        return news_items

    except Exception as e:
        print(f"Ошибка получения политических новостей: {e}")
        return get_alternative_political_news(limit)


def get_alternative_political_news(limit=5):
    """Альтернативный источник политических новостей"""
    try:
        # Парсим Reuters для новостей о регулировании
        url = "https://www.reuters.com/business/finance/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        news_items = []
        articles = soup.find_all('a', {'data-testid': 'Heading'}, limit=limit * 2)

        for article in articles:
            title = article.get_text().strip()
            url = article.get('href')
            if not url.startswith('http'):
                url = 'https://www.reuters.com' + url

            # Фильтруем только relevant новости
            if any(keyword in title.lower() for keyword in CRYPTO_KEYWORDS):
                news_items.append({
                    'title': title,
                    'url': url,
                    'published_at': datetime.now().strftime('%Y-%m-%d'),
                    'source': 'Reuters',
                    'description': ''
                })

            if len(news_items) >= limit:
                break

        return news_items

    except Exception as e:
        print(f"Ошибка альтернативного источника политических новостей: {e}")
        return []


def analyze_news_impact(news_items):
    """Анализ потенциального влияния новостей на рынок"""
    impact_analysis = []

    for news in news_items:
        title = news['title'].lower()
        impact_level = "НЕЙТРАЛЬНО"
        affected_coins = []
        sentiment = "⚪"

        # Определяем уровень влияния
        if any(word in title for word in ['ban', 'illegal', 'crackdown', 'sue', 'sued']):
            impact_level = "ВЫСОКИЙ НЕГАТИВ"
            sentiment = "🔴"
        elif any(word in title for word in ['regulation', 'law', 'sec', 'fed', 'government']):
            impact_level = "СРЕДНИЙ НЕГАТИВ"
            sentiment = "🟠"
        elif any(word in title for word in ['approve', 'legal', 'adopt', 'partnership', 'investment']):
            impact_level = "СРЕДНИЙ ПОЗИТИВ"
            sentiment = "🟢"
        elif any(word in title for word in ['bitcoin', 'btc']):
            affected_coins.append("BTC")
        elif any(word in title for word in ['ethereum', 'eth']):
            affected_coins.append("ETH")
        elif any(word in title for word in ['xrp', 'ripple']):
            affected_coins.append("XRP")
        elif any(word in title for word in ['cardano', 'ada']):
            affected_coins.append("ADA")
        elif any(word in title for word in ['solana', 'sol']):
            affected_coins.append("SOL")

        # Если не определены конкретные монеты, применяем ко всему рынку
        if not affected_coins:
            affected_coins = ["ВСЕ РЫНКИ"]

        impact_analysis.append({
            'title': news['title'],
            'url': news['url'],
            'source': news['source'],
            'impact': impact_level,
            'sentiment': sentiment,
            'affected': affected_coins,
            'time': news.get('published_at', '')
        })

    return impact_analysis


def format_news_message(news_analysis):
    """Форматирование сообщения с новостями"""
    if not news_analysis:
        return "❌ Не удалось загрузить новости. Попробуйте позже."

    message = "<b>📰 АКТУАЛЬНЫЕ НОВОСТИ ДЛЯ ТРЕЙДЕРОВ</b>\n\n"

    for i, news in enumerate(news_analysis[:5], 1):
        message += f"{news['sentiment']} <b>{i}. {news['title']}</b>\n"
        message += f"   📊 <b>Влияние:</b> {news['impact']}\n"
        message += f"   📍 <b>Затронет:</b> {', '.join(news['affected'])}\n"
        message += f"   🏢 <b>Источник:</b> {news['source']}\n"
        message += f"   🔗 <a href='{news['url']}'>Читать полностью</a>\n\n"

    message += "<i>💡 Используйте эти новости для принятия торговых решений.</i>"
    message += "\n<i>⚠️ Это не инвестиционная рекомендация.</i>"

    return message


# --- Функции для работы с биржевыми данными (остаются без изменений) ---

def get_historical_data(symbol, interval='1d', limit=100):
    """Получение исторических данных для анализа"""
    try:
        normalized_symbol = normalize_symbol(symbol)
        url = f"{BINANCE_API_URL}/klines"
        params = {
            'symbol': normalized_symbol,
            'interval': interval,
            'limit': limit
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Создаем DataFrame
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])

        # Конвертируем в числовые типы
        numeric_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col])

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        return df

    except Exception as e:
        print(f"Ошибка получения исторических данных: {e}")
        return None


def get_binance_price(symbol):
    """Получение текущей цены с Binance"""
    try:
        normalized_symbol = normalize_symbol(symbol)
        url = f"{BINANCE_API_URL}/ticker/24hr"
        params = {'symbol': normalized_symbol}

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        return {
            'symbol': normalized_symbol,
            'price': safe_float(data.get('lastPrice')),
            'change': safe_float(data.get('priceChange')),
            'change_percent': safe_float(data.get('priceChangePercent')),
            'high': safe_float(data.get('highPrice')),
            'low': safe_float(data.get('lowPrice')),
            'open': safe_float(data.get('openPrice')),
            'volume': safe_float(data.get('volume')),
            'quote_volume': safe_float(data.get('quoteVolume')),
            'timestamp': datetime.now().strftime('%H:%M:%S')
        }

    except Exception as e:
        print(f"Ошибка Binance API: {e}")
        return None


def calculate_technical_indicators(df):
    """Расчет всех технических индикаторов"""
    try:
        close_prices = df['close'].values
        high_prices = df['high'].values
        low_prices = df['low'].values

        indicators = {}

        # 1. Moving Averages (Скользящие средние)
        indicators['MA_20'] = talib.SMA(close_prices, timeperiod=20)[-1]
        indicators['MA_50'] = talib.SMA(close_prices, timeperiod=50)[-1]
        indicators['MA_100'] = talib.SMA(close_prices, timeperiod=100)[-1]

        current_price = close_prices[-1]
        indicators['MA_Signal'] = get_ma_signal(current_price, indicators)

        # 2. RSI (Relative Strength Index)
        indicators['RSI'] = talib.RSI(close_prices, timeperiod=14)[-1]
        indicators['RSI_Signal'] = get_rsi_signal(indicators['RSI'])

        # 3. MACD (Moving Average Convergence Divergence)
        macd, macd_signal, macd_hist = talib.MACD(close_prices,
                                                  fastperiod=12,
                                                  slowperiod=26,
                                                  signalperiod=9)
        indicators['MACD'] = macd[-1]
        indicators['MACD_Signal'] = macd_signal[-1]
        indicators['MACD_Hist'] = macd_hist[-1]
        indicators['MACD_Signal_Type'] = get_macd_signal(macd, macd_signal)

        # 4. Bollinger Bands (Полосы Боллинджера)
        upper_band, middle_band, lower_band = talib.BBANDS(close_prices,
                                                           timeperiod=20,
                                                           nbdevup=2,
                                                           nbdevdn=2)
        indicators['BB_Upper'] = upper_band[-1]
        indicators['BB_Middle'] = middle_band[-1]
        indicators['BB_Lower'] = lower_band[-1]
        indicators['BB_Position'] = get_bb_position(current_price,
                                                    upper_band[-1],
                                                    lower_band[-1])

        # Дополнительные индикаторы
        indicators['Volume_MA'] = talib.SMA(df['volume'].values, timeperiod=20)[-1]
        indicators['Current_Volume'] = df['volume'].values[-1]
        indicators['Volume_Ratio'] = indicators['Current_Volume'] / indicators['Volume_MA'] if indicators[
                                                                                                   'Volume_MA'] > 0 else 1

        return indicators

    except Exception as e:
        print(f"Ошибка расчета индикаторов: {e}")
        return None


def get_ma_signal(current_price, indicators):
    """Сигнал по скользящим средним"""
    ma_20 = indicators['MA_20']
    ma_50 = indicators['MA_50']
    ma_100 = indicators['MA_100']

    if current_price > ma_20 > ma_50 > ma_100:
        return "🟢 СИЛЬНЫЙ БЫЧИЙ (все MA в восходящем порядке)"
    elif current_price < ma_20 < ma_50 < ma_100:
        return "🔴 СИЛЬНЫЙ МЕДВЕЖИЙ (все MA в нисходящем порядке)"
    elif current_price > ma_20 and ma_20 > ma_50:
        return "🟢 БЫЧИЙ (цена выше MA20, MA20 > MA50)"
    elif current_price < ma_20 and ma_20 < ma_50:
        return "🔴 МЕДВЕЖИЙ (цена ниже MA20, MA20 < MA50)"
    else:
        return "⚪ НЕЙТРАЛЬНЫЙ (смешанные сигналы)"


def get_rsi_signal(rsi):
    """Сигнал по RSI"""
    if rsi > 70:
        return "🔴 ПЕРЕКУПЛЕННОСТЬ (RSI > 70)"
    elif rsi > 60:
        return "🟡 ВЕРХНЯЯ ЗОНА (RSI 60-70)"
    elif rsi < 30:
        return "🟢 ПЕРЕПРОДАННОСТЬ (RSI < 30)"
    elif rsi < 40:
        return "🟡 НИЖНЯЯ ЗОНА (RSI 30-40)"
    else:
        return "⚪ НЕЙТРАЛЬНО (RSI 40-60)"


def get_macd_signal(macd, macd_signal):
    """Сигнал по MACD"""
    current_macd = macd[-1]
    current_signal = macd_signal[-1]
    previous_macd = macd[-2]
    previous_signal = macd_signal[-2]

    # Пересечение MACD выше сигнальной линии
    if current_macd > current_signal and previous_macd <= previous_signal:
        return "🟢 БЫЧИЙ ПЕРЕСЕЧЕНИЕ (MACD выше сигнала)"
    # Пересечение MACD ниже сигнальной линии
    elif current_macd < current_signal and previous_macd >= previous_signal:
        return "🔴 МЕДВЕЖИЙ ПЕРЕСЕЧЕНИЕ (MACD ниже сигнала)"
    # MACD выше сигнальной линии
    elif current_macd > current_signal:
        return "🟢 БЫЧИЙ (MACD выше сигнала)"
    # MACD ниже сигнальной линии
    elif current_macd < current_signal:
        return "🔴 МЕДВЕЖИЙ (MACD ниже сигнала)"
    else:
        return "⚪ НЕЙТРАЛЬНЫЙ"


def get_bb_position(price, upper_band, lower_band):
    """Позиция относительно полос Боллинджера"""
    band_width = upper_band - lower_band
    if band_width == 0:
        return "⚪ НЕОПРЕДЕЛЕННО"

    position = (price - lower_band) / band_width

    if position > 0.8:
        return "🔴 ВЕРХНЯЯ ПОЛОСА (>80%)"
    elif position > 0.6:
        return "🟡 ВЕРХНЯЯ ЗОНА (60-80%)"
    elif position < 0.2:
        return "🟢 НИЖНЯЯ ПОЛОСА (<20%)"
    elif position < 0.4:
        return "🟡 НИЖНЯЯ ЗОНА (20-40%)"
    else:
        return "⚪ СРЕДНЯЯ ЗОНА (40-60%)"


def generate_technical_analysis(symbol, df, indicators, current_data):
    """Генерация полного технического анализа"""
    try:
        current_price = current_data['price']
        change_percent = current_data['change_percent']

        analysis = f"""<b>📊 {symbol} - ПОЛНЫЙ ТЕХНИЧЕСКИЙ АНАЛИЗ</b>

💰 <b>Текущая цена:</b> ${current_price:,.4f}
📈 <b>Изменение 24ч:</b> {change_percent:+.2f}%

<b>🎯 СИГНАЛЫ ИНДИКАТОРОВ:</b>

<b>1. 📊 СКОЛЬЗЯЩИЕ СРЕДНИЕ (MA):</b>
• MA(20): ${indicators['MA_20']:,.4f}
• MA(50): ${indicators['MA_50']:,.4f} 
• MA(100): ${indicators['MA_100']:,.4f}
• Сигнал: {indicators['MA_Signal']}

<b>2. 📈 RSI (Индекс Относительной Силы):</b>
• RSI(14): {indicators['RSI']:.2f}
• Сигнал: {indicators['RSI_Signal']}

<b>3. 🔄 MACD (Схождение/Расхождение Скользящих Средних):</b>
• MACD: {indicators['MACD']:.4f}
• Signal: {indicators['MACD_Signal']:.4f}
• Histogram: {indicators['MACD_Hist']:.4f}
• Сигнал: {indicators['MACD_Signal_Type']}

<b>4. 📉 ПОЛОСЫ БОЛЛИНДЖЕРА (BB):</b>
• Верхняя: ${indicators['BB_Upper']:,.4f}
• Средняя: ${indicators['BB_Middle']:,.4f}
• Нижняя: ${indicators['BB_Lower']:,.4f}
• Позиция: {indicators['BB_Position']}

<b>5. 💹 ОБЪЕМ ТОРГОВ:</b>
• Текущий объем: {indicators['Current_Volume']:,.0f}
• Средний объем (20): {indicators['Volume_MA']:,.0f}
• Соотношение: {indicators['Volume_Ratio']:.2f}x

<b>📊 ОБЩИЙ СИГНАЛ:</b>
{generate_overall_signal(indicators)}

⏰ <i>Анализ выполнен: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</i>
<i>📈 Источник: Binance API | 🕐 Таймфрейм: 1 день</i>
"""
        return analysis

    except Exception as e:
        print(f"Ошибка генерации анализа: {e}")
        return None


def generate_overall_signal(indicators):
    """Генерация общего торгового сигнала"""
    bullish_signals = 0
    bearish_signals = 0

    # Анализ MA сигнала
    ma_signal = indicators['MA_Signal']
    if "БЫЧИЙ" in ma_signal:
        bullish_signals += 2 if "СИЛЬНЫЙ" in ma_signal else 1
    elif "МЕДВЕЖИЙ" in ma_signal:
        bearish_signals += 2 if "СИЛЬНЫЙ" in ma_signal else 1

    # Анализ RSI сигнала
    rsi_signal = indicators['RSI_Signal']
    if "ПЕРЕПРОДАННОСТЬ" in rsi_signal:
        bullish_signals += 2
    elif "ПЕРЕКУПЛЕННОСТЬ" in rsi_signal:
        bearish_signals += 2
    elif "НИЖНЯЯ ЗОНА" in rsi_signal:
        bullish_signals += 1

    # Анализ MACD сигнала
    macd_signal = indicators['MACD_Signal_Type']
    if "БЫЧИЙ" in macd_signal:
        bullish_signals += 2 if "ПЕРЕСЕЧЕНИЕ" in macd_signal else 1
    elif "МЕДВЕЖИЙ" in macd_signal:
        bearish_signals += 2 if "ПЕРЕСЕЧЕНИЕ" in macd_signal else 1

    # Анализ Bollinger Bands
    bb_signal = indicators['BB_Position']
    if "НИЖНЯЯ ПОЛОСА" in bb_signal:
        bullish_signals += 2
    elif "НИЖНЯЯ ЗОНА" in bb_signal:
        bullish_signals += 1
    elif "ВЕРХНЯЯ ПОЛОСА" in bb_signal:
        bearish_signals += 2

    # Определение общего сигнала
    if bullish_signals - bearish_signals >= 3:
        return "🟢 СИЛЬНЫЙ БЫЧИЙ СИГНАЛ (покупка)"
    elif bullish_signals - bearish_signals >= 1:
        return "🟢 БЫЧИЙ СИГНАЛ (возможность покупки)"
    elif bearish_signals - bullish_signals >= 3:
        return "🔴 СИЛЬНЫЙ МЕДВЕЖИЙ СИГНАЛ (продажа)"
    elif bearish_signals - bullish_signals >= 1:
        return "🔴 МЕДВЕЖИЙ СИГНАЛ (осторожность)"
    else:
        return "⚪ НЕЙТРАЛЬНЫЙ СИГНАЛ (ожидание)"


def format_price_message(data, indicators=None):
    """Форматирование сообщения с ценой"""
    if not data:
        return "❌ Ошибка получения данных"

    symbol = safe_str(data.get('symbol', 'UNKNOWN'))
    price = safe_float(data.get('price', 0))
    change = safe_float(data.get('change', 0))
    change_percent = safe_float(data.get('change_percent', 0))

    message = f"<b>📊 {symbol} - ТЕКУЩАЯ ЦЕНА</b>\n\n"
    message += f"💰 <b>Цена:</b> ${price:,.4f}\n"

    change_emoji = "🟢" if change >= 0 else "🔴"
    message += f"📈 <b>Изменение 24ч:</b> {change_emoji} ${abs(change):,.4f} ({change_percent:+.2f}%)\n\n"

    if indicators:
        message += f"<b>📊 КЛЮЧЕВЫЕ ИНДИКАТОРЫ:</b>\n"
        message += f"• RSI: {indicators.get('RSI', 0):.1f} - {indicators.get('RSI_Signal', '')}\n"
        message += f"• MACD: {indicators.get('MACD', 0):.4f}\n"
        message += f"• Полосы Боллинджера: {indicators.get('BB_Position', '')}\n"

        overall_signal = generate_overall_signal(indicators)
        message += f"\n<b>🎯 ОБЩИЙ СИГНАЛ:</b> {overall_signal}"

    message += f"\n\n⏰ <i>Обновлено: {data.get('timestamp', '')}</i>"
    message += f"\n<i>Для полного анализа используйте /analysis</i>"

    return message


def get_chart_image(symbol):
    """Генерация ссылки на график"""
    normalized_symbol = normalize_symbol(symbol)
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{normalized_symbol}"


# --- Обработчики команд ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Приветственное сообщение"""
    welcome_text = """
<b>🚀 КРИПТО АНАЛИТИК - ПРОФЕССИОНАЛЬНЫЙ АНАЛИЗ</b>

<u>📊 ДОСТУПНЫЕ КОМАНДЫ:</u>
/price - Текущая цена + базовые индикаторы
/analysis - Полный технический анализ (MA, RSI, MACD, BB)
/news - Актуальные новости рынка
/chart - График на TradingView
/watch - Добавить в избранное
/list - Показать избранное

<u>🔔 КОМАНДЫ УВЕДОМЛЕНИЙ:</u>
/alertadd SYMBOL % - Добавить уведомление (например: /alertadd BTC 5.0)
/alertremove SYMBOL - Удалить уведомление
/alerts - Показать активные уведомления

<u>📊 ОСНОВНЫЕ КОМАНДЫ:</u>
/price SYMBOL - Текущая цена
/analysis SYMBOL - Полный анализ
/news - Актуальные новости

<u>📈 ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ:</u>
• 📊 Moving Averages (MA 20/50/100)
• 📈 RSI - Индекс Относительной Силы
• 🔄 MACD - Схождение/Расхождение Средних
• 📉 Bollinger Bands - Полосы Боллинджера
• 💹 Анализ объема торгов

<u>📰 СИСТЕМА НОВОСТЕЙ:</u>
• Криптовалютные новости
• Политические события
• Анализ влияния на рынок
• Рекомендации для трейдеров

<u>💡 ПРИМЕРЫ:</u>
/price BTC - текущая цена Bitcoin
/analysis ETH - полный анализ Ethereum
/news - актуальные новости рынка
/chart SOL - график Solana
/alertadd BTC 3.5 - Уведомлять при изменении Bitcoin на 3.5%
/alertadd ETH 5.0 - Уведомлять при изменении Ethereum на 5%
"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('📊 Цена')
    btn2 = types.KeyboardButton('📈 Анализ')
    btn3 = types.KeyboardButton('📰 Новости')
    btn4 = types.KeyboardButton('📉 График')
    btn5 = types.KeyboardButton('⭐ Избранное')

    markup.add(btn1, btn2, btn3, btn4, btn5)

    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)


@bot.message_handler(commands=['price'])
def price_command(message):
    """Команда для получения цены с индикаторами"""
    try:
        parts = message.text.split()
        if len(parts) > 1:
            symbol = ' '.join(parts[1:])
            check_crypto_price(message, symbol)
        else:
            bot.send_message(message.chat.id, "❌ Укажите символ: /price BTC")
    except Exception as e:
        print(f"Ошибка в price_command: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка обработки команды")


@bot.message_handler(commands=['analysis'])
def analysis_command(message):
    """Команда для полного технического анализа"""
    try:
        parts = message.text.split()
        if len(parts) > 1:
            symbol = ' '.join(parts[1:])
            perform_technical_analysis(message, symbol)
        else:
            bot.send_message(message.chat.id, "❌ Укажите символ: /analysis BTC")
    except Exception as e:
        print(f"Ошибка в analysis_command: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка обработки команды")


@bot.message_handler(commands=['news'])
def news_command(message):
    """Команда для получения новостей"""
    try:
        show_news(message)
    except Exception as e:
        print(f"Ошибка в news_command: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка загрузки новостей")


@bot.message_handler(commands=['chart'])
def chart_command(message):
    """Команда для графика"""
    try:
        parts = message.text.split()
        if len(parts) > 1:
            symbol = ' '.join(parts[1:])
            show_chart(message, symbol)
        else:
            bot.send_message(message.chat.id, "❌ Укажите символ: /chart BTC")
    except Exception as e:
        print(f"Ошибка в chart_command: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


@bot.message_handler(commands=['watch'])
def watch_command(message):
    """Добавление в избранное"""
    try:
        parts = message.text.split()
        if len(parts) > 1:
            symbol = ' '.join(parts[1:])
            add_to_watchlist(message, symbol)
        else:
            bot.send_message(message.chat.id, "❌ Укажите символ: /watch BTC")
    except Exception as e:
        print(f"Ошибка в watch_command: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка при добавлении в избранное")


@bot.message_handler(commands=['list'])
def list_command(message):
    """Показать избранное"""
    show_watchlist(message)


# --- Основные обработчики ---

@bot.message_handler(func=lambda message: message.text in ['📊 Цена', 'цена', 'Цена'])
def handle_price_button(message):
    """Обработчик кнопки Цена"""
    msg = bot.send_message(message.chat.id, "🔍 Введите символ для цены (BTC, ETH):")
    bot.register_next_step_handler(msg, process_price_input)


@bot.message_handler(func=lambda message: message.text in ['📈 Анализ', 'анализ', 'Анализ'])
def handle_analysis_button(message):
    """Обработчик кнопки Анализ"""
    msg = bot.send_message(message.chat.id, "📊 Введите символ для анализа (BTC, ETH):")
    bot.register_next_step_handler(msg, process_analysis_input)


@bot.message_handler(func=lambda message: message.text in ['📰 Новости', 'новости', 'Новости'])
def handle_news_button(message):
    """Обработчик кнопки Новости"""
    show_news(message)


@bot.message_handler(func=lambda message: message.text in ['📉 График', 'график', 'График'])
def handle_chart_button(message):
    """Обработчик кнопки График"""
    msg = bot.send_message(message.chat.id, "📈 Введите символ для графика (BTC):")
    bot.register_next_step_handler(msg, process_chart_input)


@bot.message_handler(func=lambda message: message.text in ['⭐ Избранное', 'избранное'])
def handle_watchlist_button(message):
    """Обработчик кнопки Избранное"""
    show_watchlist(message)


def process_price_input(message):
    """Обработка ввода для цены"""
    try:
        symbol = message.text.strip()
        if symbol:
            check_crypto_price(message, symbol)
        else:
            bot.send_message(message.chat.id, "❌ Пожалуйста, введите символ")
    except Exception as e:
        print(f"Ошибка в process_price_input: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка обработки запроса")


def process_analysis_input(message):
    """Обработка ввода для анализа"""
    try:
        symbol = message.text.strip()
        if symbol:
            perform_technical_analysis(message, symbol)
        else:
            bot.send_message(message.chat.id, "❌ Пожалуйста, введите символ")
    except Exception as e:
        print(f"Ошибка в process_analysis_input: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка обработки запроса")


def process_chart_input(message):
    """Обработка ввода для графика"""
    try:
        symbol = message.text.strip()
        if symbol:
            show_chart(message, symbol)
        else:
            bot.send_message(message.chat.id, "❌ Пожалуйста, введите символ")
    except Exception as e:
        print(f"Ошибка в process_chart_input: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")


def show_news(message):
    """Показ актуальных новостей"""
    try:
        bot.send_chat_action(message.chat.id, 'typing')

        # Получаем криптоновости
        crypto_news = get_crypto_news(limit=3)
        # Получаем политические новости
        political_news = get_political_news(limit=3)

        # Объединяем и анализируем влияние
        all_news = crypto_news + political_news
        news_analysis = analyze_news_impact(all_news)

        # Форматируем сообщение
        news_message = format_news_message(news_analysis)

        # Добавляем кнопку обновления
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Обновить новости", callback_data="refresh_news"))

        bot.send_message(message.chat.id, news_message, reply_markup=markup, disable_web_page_preview=True)

    except Exception as e:
        print(f"Ошибка в show_news: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка загрузки новостей. Попробуйте позже.")


def check_crypto_price(message, symbol):
    """Проверка цены с базовыми индикаторами"""
    try:
        bot.send_chat_action(message.chat.id, 'typing')

        # Получаем текущие данные
        current_data = get_binance_price(symbol)
        if not current_data:
            bot.send_message(message.chat.id, f"❌ Не удалось получить данные для '{symbol}'")
            return

        # Получаем исторические данные для индикаторов
        df = get_historical_data(symbol, interval='1d', limit=100)
        if df is None or len(df) < 50:
            bot.send_message(message.chat.id, f"❌ Недостаточно данных для анализа '{symbol}'")
            return

        # Рассчитываем индикаторы
        indicators = calculate_technical_indicators(df)
        if not indicators:
            bot.send_message(message.chat.id, f"❌ Ошибка расчета индикаторов для '{symbol}'")
            return

        response = format_price_message(current_data, indicators)

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 Полный анализ", callback_data=f"analysis_{symbol}"),
            types.InlineKeyboardButton("📈 График", callback_data=f"chart_{symbol}"),
            types.InlineKeyboardButton("⭐ В избранное", callback_data=f"watch_{symbol}"),
            types.InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{symbol}")
        )

        bot.send_message(message.chat.id, response, reply_markup=markup)

    except Exception as e:
        print(f"Ошибка в check_crypto_price: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка при получении данных для {symbol}")


def perform_technical_analysis(message, symbol):
    """Выполнение полного технического анализа"""
    try:
        bot.send_chat_action(message.chat.id, 'typing')

        # Получаем текущие данные
        current_data = get_binance_price(symbol)
        if not current_data:
            bot.send_message(message.chat.id, f"❌ Не удалось получить данные для '{symbol}'")
            return

        # Получаем исторические данные
        df = get_historical_data(symbol, interval='1d', limit=100)
        if df is None or len(df) < 50:
            bot.send_message(message.chat.id, f"❌ Недостаточно данных для анализа '{symbol}'")
            return

        # Рассчитываем индикаторы
        indicators = calculate_technical_indicators(df)
        if not indicators:
            bot.send_message(message.chat.id, f"❌ Ошибка расчета индикаторов для '{symbol}'")
            return

        # Генерируем полный анализ
        analysis = generate_technical_analysis(symbol, df, indicators, current_data)
        if not analysis:
            bot.send_message(message.chat.id, f"❌ Ошибка генерации анализа для '{symbol}'")
            return

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("📈 Текущая цена", callback_data=f"price_{symbol}"),
            types.InlineKeyboardButton("📉 График", callback_data=f"chart_{symbol}")
        )

        # Разбиваем сообщение на части если оно слишком длинное
        if len(analysis) > 4000:
            parts = [analysis[i:i + 4000] for i in range(0, len(analysis), 4000)]
            for part in parts:
                bot.send_message(message.chat.id, part, parse_mode='HTML')
            bot.send_message(message.chat.id, "📊 Анализ завершен!", reply_markup=markup)
        else:
            bot.send_message(message.chat.id, analysis, reply_markup=markup)

    except Exception as e:
        print(f"Ошибка в perform_technical_analysis: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка при анализе {symbol}")


def show_chart(message, symbol):
    """Показ графика"""
    try:
        chart_url = get_chart_image(symbol)
        normalized_symbol = normalize_symbol(symbol)

        response = f"<b>📈 ГРАФИК {normalized_symbol}</b>\n\n"
        response += f"🔗 <a href='{chart_url}'>Открыть интерактивный график на TradingView</a>\n\n"
        response += f"<i>Нажмите на ссылку для просмотра реального графика с индикаторами</i>"

        bot.send_message(message.chat.id, response, disable_web_page_preview=False)

    except Exception as e:
        print(f"Ошибка в show_chart: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка при получении графика")


# --- Функции для избранного ---

def add_to_watchlist(message, symbol):
    """Добавление в избранное"""
    try:
        user_id = message.from_user.id
        normalized_symbol = normalize_symbol(symbol)

        if user_id not in user_watchlist:
            user_watchlist[user_id] = []

        if normalized_symbol in user_watchlist[user_id]:
            bot.send_message(message.chat.id, f"✅ {normalized_symbol} уже в избранном")
        else:
            user_watchlist[user_id].append(normalized_symbol)
            bot.send_message(message.chat.id, f"✅ {normalized_symbol} добавлен в избранное!")

    except Exception as e:
        print(f"Ошибка в add_to_watchlist: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка при добавлении в избранное")


def show_watchlist(message):
    """Показ избранного"""
    try:
        user_id = message.from_user.id
        if user_id not in user_watchlist or not user_watchlist[user_id]:
            bot.send_message(message.chat.id, "📭 Избранное пусто. Добавьте символы: /watch BTC")
            return

        bot.send_message(message.chat.id, "🔄 Загружаю актуальные цены...")

        markup = types.InlineKeyboardMarkup()
        for symbol in user_watchlist[user_id]:
            data = get_binance_price(symbol)
            if data:
                price = safe_float(data.get('price', 0))
                change_percent = safe_float(data.get('change_percent', 0))
                change_emoji = "🟢" if change_percent >= 0 else "🔴"

                markup.add(types.InlineKeyboardButton(
                    f"{symbol} - ${price:,.2f} {change_emoji}{change_percent:+.1f}%",
                    callback_data=f"price_{symbol}"
                ))

        markup.add(types.InlineKeyboardButton("🗑️ Управление избранным", callback_data="manage_watchlist"))

        bot.send_message(message.chat.id, "📊 <b>Ваше избранное:</b>", reply_markup=markup)

    except Exception as e:
        print(f"Ошибка в show_watchlist: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка при загрузке избранного")


# --- Обработчик callback-кнопок ---

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработчик callback-кнопок"""
    try:
        if call.data.startswith('price_'):
            symbol = call.data.split('_', 1)[1]
            check_crypto_price(call.message, symbol)

        elif call.data.startswith('analysis_'):
            symbol = call.data.split('_', 1)[1]
            perform_technical_analysis(call.message, symbol)

        elif call.data.startswith('chart_'):
            symbol = call.data.split('_', 1)[1]
            show_chart(call.message, symbol)

        elif call.data.startswith('watch_'):
            symbol = call.data.split('_', 1)[1]
            user_id = call.from_user.id

            if user_id not in user_watchlist:
                user_watchlist[user_id] = []

            if symbol in user_watchlist[user_id]:
                bot.answer_callback_query(call.id, f"✅ {symbol} уже в избранном")
            else:
                user_watchlist[user_id].append(symbol)
                bot.answer_callback_query(call.id, f"✅ {symbol} добавлен в избранное!")

        elif call.data.startswith('refresh_'):
            if call.data == 'refresh_news':
                bot.answer_callback_query(call.id, "✅ Новости обновляются")
                show_news(call.message)
            else:
                symbol = call.data.split('_', 1)[1]
                bot.answer_callback_query(call.id, "✅ Данные обновлены")
                check_crypto_price(call.message, symbol)

    except Exception as e:
        print(f"Ошибка callback: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка обработки запроса")


# --- Запуск бота ---

if __name__ == '__main__':
    print("🤖 КРИПТО АНАЛИТИК запущен...")
    print("🔔 Система уведомлений активирована")
    print("📊 Отслеживание цен в реальном времени")

    # Запускаем бота в отдельном потоке
    from threading import Thread


    def polling_thread():
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=30)
            except Exception as e:
                print(f"❌ Ошибка бота: {e}. Перезапуск через 10 секунд...")
                time.sleep(10)


    # Запускаем бота в отдельном потоке
    bot_thread = Thread(target=polling_thread, daemon=True)
    bot_thread.start()

    # Основной цикл проверки уведомлений
    while True:
        try:
            current_time = time.time()

            # Проверяем уведомления каждые alert_check_interval секунд
            if current_time - last_alert_check >= alert_check_interval:
                alerts = check_price_alerts()

                for user_id, alert_message in alerts:
                    try:
                        bot.send_message(user_id, alert_message)
                        print(f"📨 Отправлено уведомление пользователю {user_id}")
                    except Exception as e:
                        print(f"❌ Ошибка отправки уведомления: {e}")

                last_alert_check = current_time

            time.sleep(10)  # Короткая пауза между проверками

        except Exception as e:
            print(f"❌ Ошибка в основном цикле: {e}")
            time.sleep(30)