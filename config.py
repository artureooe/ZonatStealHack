import os

class Config:
    # Telegram
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "8075320326:AAHVxtnOER6Ud8VSXxU9ApAtsz3-boeDQPk")
    ADMIN_ID = int(os.environ.get("ADMIN_ID", "7725796090"))
    
    # Server
    WEBHOOK_BASE = os.environ.get("WEBHOOK_BASE", "https://artursaoo.onrender.com")
    PORT = int(os.environ.get("PORT", 10000))
    
    # Subscription
    FREE_TRIAL_HOURS = 1
    PRICES = {
        "1day": 100,
        "7days": 500,
        "30days": 1500
    }
    
    # Features
    VERSION = "Zonat Steal v3.0"
    ENABLE_APK_GENERATOR = True
    ENABLE_SUBSCRIPTIONS = True
    
    # Database
    DB_PATH = "zonat.db"
    
    # Security
    SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-here")

config = Config()
