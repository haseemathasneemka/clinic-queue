import os
from dotenv import load_dotenv

load_dotenv()  # reads values from the .env file

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "clinic_queue"),
}

# Used for wait estimates when a doctor has no consultation history yet
DEFAULT_CONSULT_MIN = 8
