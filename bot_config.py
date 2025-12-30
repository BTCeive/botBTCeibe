"""
Configuración del bot.
Lee variables de entorno desde .env
"""
import os
from dotenv import load_dotenv
from pathlib import Path

# Cargar .env desde el directorio config del proyecto
ROOT_DIR = Path(__file__).parent

# Usar siempre rutas relativas para portabilidad
env_path = ROOT_DIR / 'config' / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"✅ .env cargado desde: {env_path}")
else:
    # Fallback: intentar en el directorio raíz
    env_path = ROOT_DIR / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        print(f"⚠️ .env cargado desde raíz: {env_path}")
    else:
        print("❌ ERROR: No se encontró archivo .env")
        load_dotenv()  # Último intento desde CWD

# Credenciales de Binance
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_KEY', '')
# NOTA: Para leer datos reales de Binance sin arriesgar saldo, usa BINANCE_TESTNET=false
# Esto permite leer precios/tickers live mientras las operaciones se simulan en Python
BINANCE_TESTNET = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
BINANCE_READ_ONLY = os.getenv('BINANCE_READ_ONLY', 'true').lower() == 'true'  # Lectura live sin escribir

# Ruta de la base de datos
DB_PATH = os.getenv('DB_PATH', 'multibot.db')

