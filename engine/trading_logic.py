"""
Motor de trading para botCeibe.
Lee strategy.json y ejecuta la lógica de trading.
"""
import asyncio
import ccxt
import json
import logging
import os
import sys
import time
import threading
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from pathlib import Path

# Agregar el directorio raíz al path para importar módulos existentes
# engine/trading_logic.py está en botCeibe/engine/, así que el ROOT_DIR es botCeibe/
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Configurar logging PRIMERO (antes de otros imports que puedan usar logger)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Asegurar que .env se carga desde config/.env (ubicación estándar)
# Esto es crítico: load_dotenv() busca .env en el directorio actual de trabajo,
# pero necesitamos buscarlo en config/.env primero (ubicación estándar)
try:
    from dotenv import load_dotenv
    # Intentar primero en config/.env (ubicación estándar, como bot_config.py)
    env_path = ROOT_DIR / 'config' / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        logger.debug(f"✅ .env cargado desde {env_path}")
    else:
        # Fallback: intentar en el directorio raíz
        env_path = ROOT_DIR / '.env'
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            logger.debug(f"✅ .env cargado desde {env_path} (raíz)")
        else:
            # Último fallback: directorio actual
            load_dotenv()
            logger.debug("⚠️ .env no encontrado en config/.env ni en raíz, intentando directorio actual")
except ImportError:
    logger.debug("python-dotenv no está instalado, se usará config.py")
except Exception as e:
    logger.debug(f"Error al cargar .env: {e}")

from database import Database
from vault import Vault
from router import get_available_pairs, get_pair_info, find_swap_route, init_router
from bot_config import BINANCE_API_KEY, BINANCE_SECRET_KEY, BINANCE_TESTNET, BINANCE_READ_ONLY, DB_PATH

# Integración SQLite de almacenamiento
try:
    from storage import save_market_data, save_portfolio_snapshot, init_db
    init_db()
    logger.info("Storage SQLite inicializado (bot_data.db)")
except Exception as e:
    logger.debug(f"Storage SQLite no disponible: {e}")

# Intentar importar utils para file locking
try:
    from utils.file_utils import read_json_safe, write_json_safe
    HAS_FILE_UTILS = True
except ImportError:
    HAS_FILE_UTILS = False
    logger.warning("utils.file_utils no encontrado. Usando escritura JSON estándar sin file locking.")

# Intentar importar signals.py
try:
    import signals
    HAS_SIGNALS = True
except ImportError:
    HAS_SIGNALS = False
    logging.warning("signals.py no encontrado. Las señales de Triple Confluencia no estarán disponibles.")



def write_bitacora(message: str):
    """
    Escribe un mensaje en bitacora.txt con fecha y hora.
    
    Args:
        message: Mensaje a escribir (debe incluir el prefijo del tipo de evento)
    """
    try:
        from datetime import datetime
        bitacora_file = ROOT_DIR / 'bitacora.txt'

        # Formato: YYYY-MM-DD HH:MM:SS | [PREFIJO] Mensaje
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} | {message}\n"

        # Añadir la entrada
        with open(bitacora_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)

        # Rotación por tamaño en líneas: mantener solo las últimas MAX_LINES líneas
        try:
            MAX_LINES = 10000
            from collections import deque
            import tempfile
            import shutil

            # Contar líneas y mantener una deque de las últimas MAX_LINES
            total = 0
            dq = deque()
            with open(bitacora_file, 'r', encoding='utf-8') as f:
                for line in f:
                    total += 1
                    dq.append(line)

            if total > MAX_LINES:
                # Escribir en un archivo temporal y reemplazar atomically
                tmp = bitacora_file.with_suffix('.tmp')
                with open(tmp, 'w', encoding='utf-8') as tf:
                    tf.writelines(dq)
                try:
                    shutil.move(str(tmp), str(bitacora_file))
                except Exception:
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Error rotando bitácora: {e}")
    except Exception as e:
        logger.debug(f"Error al escribir en bitácora: {e}")


class TradingEngine:
    """Motor de trading que lee configuración desde strategy.json."""
    
    def __init__(self):
        """Inicializa el motor cargando strategy.json."""
        self.config_path = Path(__file__).parent.parent / "config" / "strategy.json"
        self.state_path = Path(__file__).parent.parent / "shared" / "state.json"
        self.radar_path = Path(__file__).parent.parent / "shared" / "radar.json"
        self.active_trades_path = Path(__file__).parent.parent / "shared" / "active_trades.json"
        self.hucha_diversificada_path = Path(__file__).parent.parent / "shared" / "hucha_diversificada.json"
        self.strategy = self._load_strategy()
        # Usar ruta absoluta para la base de datos (en el directorio raíz del proyecto)
        db_path_absolute = ROOT_DIR / DB_PATH if not os.path.isabs(DB_PATH) else DB_PATH
        self.db = Database(str(db_path_absolute))
        self.vault = Vault(self.db)
        self.exchange = self._init_exchange()
        # Cache de volúmenes por par para cálculo de vol_pct entre ciclos
        self.last_volumes: Dict[str, float] = {}
        self.last_volumes_path: Path = ROOT_DIR / 'shared' / 'last_volumes.json'
        # Cargar cache persistente de volúmenes si existe
        try:
            if self.last_volumes_path.exists():
                if HAS_FILE_UTILS:
                    self.last_volumes = read_json_safe(self.last_volumes_path, {}) or {}
                else:
                    with open(self.last_volumes_path, 'r', encoding='utf-8') as f:
                        self.last_volumes = json.load(f) or {}
                if not isinstance(self.last_volumes, dict):
                    self.last_volumes = {}
                logger.info(f"📦 last_volumes cargado: {len(self.last_volumes)} pares")
        except Exception as e:
            logger.debug(f"No se pudo cargar last_volumes: {e}")
        
        # VERIFICACIÓN DE CREDENCIALES API BINANCE
        # Solo verificar si NO estamos en modo lectura (BINANCE_READ_ONLY)
        if not BINANCE_READ_ONLY:
            try:
                # Test de conectividad con Binance
                test_balance = self.exchange.fetch_balance()
                if test_balance:
                    print("\n" + "="*60)
                    print("✅ API BINANCE CONECTADA CORRECTAMENTE")
                    print(f"   Cuenta verificada: {len(test_balance.get('total', {}))} activos detectados")
                    print("="*60 + "\n")
                    logger.info("✅ API Binance verificada correctamente")
            except ccxt.AuthenticationError as auth_err:
                print("\n" + "="*60)
                print("❌ ERROR DE CREDENCIALES - API BINANCE")
                print(f"   Detalles: {auth_err}")
                print("   Verifica config/.env con tus claves reales")
                print("="*60 + "\n")
                logger.error(f"❌ Error de autenticación Binance: {auth_err}")
                raise
            except Exception as conn_err:
                print("\n" + "="*60)
                print("⚠️ ERROR DE CONEXIÓN - API BINANCE")
                print(f"   Detalles: {conn_err}")
                print("   Verifica tu conexión a internet")
                print("="*60 + "\n")
                logger.warning(f"⚠️ Error de conexión Binance: {conn_err}")
                # No lanzar excepción, permitir continuar en modo degradado
        else:
            print("\n" + "="*60)
            print("✅ MODO LECTURA LIVE (sin credenciales privadas)")
            print("   Leyendo precios reales de API pública")
            print("   Operaciones simuladas en Python")
            print("="*60 + "\n")
            logger.info("✅ Motor en modo lectura live (BINANCE_READ_ONLY=true)")
        
        # Inicializar router con la instancia de exchange
        init_router(self.exchange)
        self._running = False
        self.fiat_assets = self.strategy.get("fiat_assets", ["EUR", "USDC"])
        self.positions_detected = False
        # Hucha Oportunista (Tax-on-Exit)
        self.hucha_enabled = self.strategy.get("hucha", {}).get("enabled", True)
        self.hucha_eur_pct = self.strategy.get("hucha", {}).get("hucha_eur_pct", 2.5)
        self.hucha_btc_pct = self.strategy.get("hucha", {}).get("hucha_btc_pct", 2.5)
        # Gestión de Gas (BNB) por Inercia
        gas_config = self.strategy.get("gas_management", {})
        self.gas_max_target = gas_config.get("max_target", 5.0)
        self.gas_low_warning = gas_config.get("low_warning", 2.5)
        self.gas_critical = gas_config.get("critical", 1.0)
        
        # Activos de reserva para hucha selectiva (solo se guarda 5% si el destino está en esta lista)
        self.RESERVE_ASSETS = ['EUR', 'USDC', 'BTC', 'ETH', 'SOL', 'DOT']
        
        # 🎯 EFECTO CENTINELA: Control de cooldown y diferencia mínima
        self.last_centinela_swap_time = None  # Timestamp del último swap centinela
        self.centinela_cooldown_seconds = 3600  # 1 hora de cooldown (3600 segundos)
        self.centinela_min_heat_diff = 40  # Diferencia mínima de Heat Score (ej: 40 puntos)
        # 🎯 DIVERSIFICACIÓN: Cooldown para evitar múltiples swaps rápidos
        self.last_diversify_time = None
        self.diversify_cooldown_seconds = 30  # 30 segundos mínimo entre diversificaciones
        
        # Radar dinámico: estado y tareas de actualización
        self.radar_data_cache = {}  # Cache de datos del radar por moneda
        self.radar_last_update = {}  # Última actualización por moneda
        self.radar_update_tasks = {}  # Tareas asyncio por zona
        
        # Frecuencias de actualización por zona (en segundos)
        # Modo CRUCERO por defecto: 15s. Persecución por par: 5s (ver _persecute_currency)
        self.radar_frequencies = {
            'muy_caliente': 15,
            'caliente': 15,
            'fria': 15,
            'muy_fria': 15
        }

        # Tareas de persecución por par (per-pair short polling)
        self.persecution_tasks: Dict[str, asyncio.Task] = {}

        # Control de escritura agrupada para radar.json (evitar I/O excesivo)
        self.radar_last_save_time = 0  # Timestamp de última escritura
        self.radar_save_interval = 30  # Segundos entre escrituras (agrupar actualizaciones)
        self.radar_pending_save = False  # Flag para indicar que hay cambios pendientes

        # Mantenimiento preventivo
        self.PROJECT_SIZE_WARNING_BYTES = 100 * 1024 * 1024  # 100 MB
        self.MAINTENANCE_INTERVAL_SECONDS = 24 * 3600  # 24 horas
        self.RADAR_CACHE_MAX_AGE_SECONDS = 2 * 3600  # 2 horas
        self._maintenance_thread = None

        # Ejecutar comprobaciones iniciales
        try:
            self._check_project_size_and_warn()
        except Exception:
            logger.debug("Error comprobando tamaño del proyecto en init")

        try:
            self._ensure_gitignore()
        except Exception:
            logger.debug("Error asegurando .gitignore en init")

    def _trim_price_history(self, entry: Dict[str, Any], max_points: int = 200) -> Dict[str, Any]:
        """
        Control de historial:
        - Si una lista supera 2000 entradas, elimina el 20% más antiguo (mantener las más recientes).
        - Si supera `max_points` (por defecto 200), recorta a las últimas `max_points`.
        Modifica `entry` in-place y la devuelve.
        """
        if not isinstance(entry, dict):
            return entry

        keys_to_check = ['history', 'price_history', 'ohlcv', 'prices', 'price_history_points', 'candles']
        for k in keys_to_check:
            v = entry.get(k)
            if isinstance(v, list) and len(v) > max_points:
                try:
                    # Política de 30 días aprox.: si >2000 puntos, eliminar 20% más antiguo
                    if len(v) > 2000:
                        cut = max(1, int(len(v) * 0.2))
                        entry[k] = v[cut:]
                    else:
                        entry[k] = v[-max_points:]
                except Exception:
                    entry[k] = v

        # También comprobar campos anidados comunes
        for k, v in list(entry.items()):
            if isinstance(v, dict):
                entry[k] = self._trim_price_history(v, max_points)

        return entry

    def _get_directory_size_bytes(self, path: Path) -> int:
        """Calcula el tamaño total (bytes) de un directorio recursivamente, excluyendo venv/ y .venv/."""
        total = 0
        try:
            for root, dirs, files in os.walk(path):
                # Excluir directorios venv/ y .venv/ del recorrido
                dirs[:] = [d for d in dirs if d not in ('venv', '.venv')]
                
                # Verificar si estamos dentro de un directorio venv (por si acaso)
                root_path = Path(root)
                if 'venv' in root_path.parts or '.venv' in root_path.parts:
                    continue
                
                for f in files:
                    try:
                        fp = os.path.join(root, f)
                        if os.path.islink(fp):
                            continue
                        total += os.path.getsize(fp)
                    except Exception:
                        continue
        except Exception:
            return 0
        return total

    @property
    def running(self) -> bool:
        return getattr(self, '_running', False)

    @running.setter
    def running(self, value: bool):
        try:
            prev = getattr(self, '_running', False)
            self._running = bool(value)
            # Si se activa desde False->True, iniciar hilo de mantenimiento
            if not prev and self._running:
                try:
                    self._start_maintenance_thread()
                    logger.debug("Hilo de mantenimiento iniciado al activar running=True")
                except Exception:
                    logger.debug("No se pudo iniciar hilo de mantenimiento al activar running")
        except Exception as e:
            logger.debug(f"Error al asignar running: {e}")

    def _check_project_size_and_warn(self):
        """Verifica tamaño del ROOT_DIR y emite warning si supera el umbral."""
        try:
            size = self._get_directory_size_bytes(ROOT_DIR)
            if size > self.PROJECT_SIZE_WARNING_BYTES:
                size_mb = size / (1024 * 1024)
                logger.warning(f"⚠️ Espacio del proyecto alto: {size_mb:.1f} MB (>100 MB). Revisa caches/venvs.")
        except Exception as e:
            logger.debug(f"Error comprobando tamaño del proyecto: {e}")

    def _ensure_gitignore(self):
        """Comprueba que `.gitignore` exista en ROOT_DIR; si no, lo crea con reglas básicas."""
        try:
            gitignore_path = ROOT_DIR / '.gitignore'
            if gitignore_path.exists():
                return

            content = """## Entornos virtuales
venv/
.venv/
env/
ENV/

## Variables de entorno locales
.env

## Caché de Python
__pycache__/
*.pyc
*.pyo
*.pyd

## Logs
*.log
bitacora.txt

## Bases de datos / cachés / datos temporales
data/
*.db
*.sqlite
*.sqlite3
*.bak
*.cache
shared/*.json
*.jsonl

## Archivos de sistema
.DS_Store
Thumbs.db

## IDE / editor
.idea/
.vscode/

"""
            try:
                with open(gitignore_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                try:
                    gitignore_path.chmod(0o664)
                except Exception:
                    pass
                logger.info(f".gitignore creado en {gitignore_path}")
            except Exception as e:
                logger.debug(f"No se pudo crear .gitignore: {e}")
        except Exception:
            pass

    def _cleanup_radar_cache(self):
        """Elimina entradas de `radar_data_cache` que no se actualizaron en las últimas 2 horas."""
        try:
            now = time.time()
            removed = 0
            keys = list(self.radar_data_cache.keys())
            for k in keys:
                last = self.radar_last_update.get(k, 0)
                if now - last > self.RADAR_CACHE_MAX_AGE_SECONDS:
                    try:
                        del self.radar_data_cache[k]
                    except Exception:
                        pass
                    try:
                        del self.radar_last_update[k]
                    except Exception:
                        pass
                    removed += 1
            if removed > 0:
                logger.info(f"🧹 Mantenimiento: Eliminadas {removed} entradas antiguas del radar_data_cache")
        except Exception as e:
            logger.debug(f"Error en limpieza de radar cache: {e}")

    def _maintenance_loop(self):
        """Bucle que corre en hilo separado y ejecuta limpieza cada `MAINTENANCE_INTERVAL_SECONDS`.

        El hilo espera a que `self.running` sea True antes de empezar los intervalos efectivos.
        """
        try:
            while True:
                # esperar hasta que el motor esté corriendo
                while not getattr(self, 'running', False):
                    time.sleep(5)

                # cuando el motor está corriendo, esperar el intervalo
                time.sleep(self.MAINTENANCE_INTERVAL_SECONDS)
                # ejecutar limpieza
                try:
                    self._cleanup_radar_cache()
                except Exception:
                    logger.debug("Error ejecutando mantenimiento periódico")
        except Exception:
            logger.debug("Hilo de mantenimiento terminado inesperadamente")

    def _start_maintenance_thread(self):
        if self._maintenance_thread and self._maintenance_thread.is_alive():
            return
        t = threading.Thread(target=self._maintenance_loop, daemon=True, name='maintenance-thread')
        t.start()
        self._maintenance_thread = t
    
    def _load_strategy(self) -> Dict[str, Any]:
        """Carga la configuración desde strategy.json."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                strategy = json.load(f)
            logger.info(f"✅ Estrategia cargada desde {self.config_path}")
            return strategy
        except FileNotFoundError:
            logger.error(f"❌ No se encontró {self.config_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error al parsear strategy.json: {e}")
            raise
    
    def _init_exchange(self) -> ccxt.binance:
        """Inicializa la conexión con Binance usando ccxt.
        
        Modos:
        - BINANCE_TESTNET=true: Conecta a testnet.binance.vision (datos ficticios)
        - BINANCE_TESTNET=false + BINANCE_READ_ONLY=true: Lee datos reales de API pública (sin credenciales)
        - BINANCE_TESTNET=false + BINANCE_READ_ONLY=false: Conecta con credenciales reales (⚠️ cuidado)
        """
        exchange_config = {
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            }
        }
        
        # Solo usar credenciales si NO estamos en modo lectura
        if not BINANCE_READ_ONLY:
            exchange_config['apiKey'] = BINANCE_API_KEY
            exchange_config['secret'] = BINANCE_SECRET_KEY
        
        if BINANCE_TESTNET:
            exchange_config['urls'] = {
                'api': {
                    'public': 'https://testnet.binance.vision/api',
                    'private': 'https://testnet.binance.vision/api',
                }
            }
        
        return ccxt.binance(exchange_config)
    
    async def start_radar_dynamic_updates(self):
        """
        Inicia el sistema de actualizaciones dinámicas del radar.
        Versión simplificada: se ejecuta implícitamente en cada tick del bucle principal.
        """
        logger.debug("✅ Radar dinámico ready (modo integrado en ciclo principal)")
        return True
    
    async def stop_radar_dynamic_updates(self):
        """
        Detiene las actualizaciones del radar dinámico.
        Versión simplificada: sin tareas asincio pendientes.
        """
        logger.debug("✅ Radar dinámico detenido")
        return True

    def reload_strategy(self):
        """Recarga la estrategia desde strategy.json (útil para cambios en caliente)."""
        self.strategy = self._load_strategy()
        logger.info("🔄 Estrategia recargada")
    
    def _get_active_assets(self) -> List[str]:
        """Obtiene la lista de activos actualmente en uso en los slots activos."""
        active_trades = self.db.get_all_active_trades()
        return [trade['target_asset'] for trade in active_trades]
    
    def _get_hucha_amount_per_currency(self) -> Dict[str, float]:
        """
        Lee hucha_diversificada.json y agrega el total de cada moneda guardada.
        
        Returns:
            Dict con currency -> total_amount guardado en hucha
        """
        hucha_amounts = {}
        try:
            if not self.hucha_diversificada_path.exists():
                return hucha_amounts
            
            with open(self.hucha_diversificada_path, 'r', encoding='utf-8') as f:
                hucha_data = json.load(f)
            
            if not isinstance(hucha_data, list):
                return hucha_amounts
            
            # Agregar todos los montos por moneda
            for entry in hucha_data:
                currency = entry.get('currency')
                amount = entry.get('amount', 0.0)
                if currency and amount > 0:
                    hucha_amounts[currency] = hucha_amounts.get(currency, 0.0) + amount
                    
        except Exception as e:
            logger.debug(f"Error leyendo hucha_diversificada.json: {e}")
        
        return hucha_amounts
    
    async def _save_hucha_diversificada(self, currency: str, amount: float, value_eur_at_save: float):
        """
        Guarda una cantidad de moneda en la hucha diversificada de forma segura.
        """
        max_retries = 3
        retry_delay = 0.1

        for attempt in range(max_retries):
            try:
                hucha_data = []
                if self.hucha_diversificada_path.exists():
                    try:
                        if HAS_FILE_UTILS:
                            hucha_data = read_json_safe(self.hucha_diversificada_path, [])
                        else:
                            with open(self.hucha_diversificada_path, 'r', encoding='utf-8') as f:
                                hucha_data = json.load(f)
                            if not isinstance(hucha_data, list):
                                hucha_data = []
                    except (json.JSONDecodeError, IOError):
                        logger.warning(f"⚠️ Error leyendo hucha_diversificada.json (intento {attempt + 1}). Reiniciando lista vacía.")
                        hucha_data = []

                # Añadir nueva entrada
                hucha_data.append({
                    'currency': currency,
                    'amount': amount,
                    'value_eur_at_save': value_eur_at_save,
                    'timestamp': datetime.now().isoformat()
                })

                # Asegurar que el directorio existe
                self.hucha_diversificada_path.parent.mkdir(parents=True, exist_ok=True)

                # Guardar de forma segura
                if HAS_FILE_UTILS:
                    write_json_safe(self.hucha_diversificada_path, hucha_data)
                else:
                    import tempfile
                    import shutil
                    temp_path = self.hucha_diversificada_path.with_suffix('.tmp')
                    try:
                        with open(temp_path, 'w', encoding='utf-8') as f:
                            json.dump(hucha_data, f, indent=2, default=str)
                        shutil.move(str(temp_path), str(self.hucha_diversificada_path))
                    finally:
                        if temp_path.exists():
                            try:
                                temp_path.unlink()
                            except Exception:
                                pass

                logger.info(f"💎 Hucha diversificada: Guardados {amount:.8f} {currency} (valor NETO: {value_eur_at_save:.2f}€)")
                return

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Error guardando hucha diversificada (intento {attempt + 1}/{max_retries}): {e}. Reintentando en {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(f"❌ Error crítico guardando hucha diversificada después de {max_retries} intentos: {e}")
                    raise
    
    def _calculate_swap_order_size(self, currency: str, total_balance: float) -> float:
        """
        Calcula el tamaño de orden para un swap según las reglas:
        - Máximo entre 25% del saldo operable y mínimo 10€
        - Saldo operable = total - hucha
        - Si el resto sería < 10€, usar 100% del saldo operable (evitar polvo)
        - BNB siempre retorna 0 (no operable, reservado para gas)
        
        Args:
            currency: Moneda a intercambiar
            total_balance: Balance total de la moneda en la wallet
        
        Returns:
            Cantidad a intercambiar, o 0 si no es operable o no cumple requisitos
        """
        try:
            # BNB no es operable (reservado para gas)
            if currency == 'BNB':
                return 0.0
            
            # Obtener cantidad en hucha para esta moneda
            hucha_amounts = self._get_hucha_amount_per_currency()
            hucha_amount = hucha_amounts.get(currency, 0.0)
            
            # Calcular saldo operable (total - hucha)
            operable_balance = max(0.0, total_balance - hucha_amount)
            
            if operable_balance <= 0:
                return 0.0
            
            # Constantes
            MIN_ORDER_VALUE_EUR = 10.0
            MAX_INVESTMENT_PCT = 0.25  # 25% del saldo operable
            
            # Calcular 25% del saldo operable
            order_size_25_percent = operable_balance * MAX_INVESTMENT_PCT
            
            # Convertir mínimo 10€ a cantidad de la moneda
            min_order_value_in_asset = 0.0
            try:
                # Intentar obtener precio en EUR
                value_eur = self.vault.get_asset_value(currency, operable_balance, 'EUR')
                if value_eur > 0:
                    price_per_unit = value_eur / operable_balance
                    min_order_value_in_asset = MIN_ORDER_VALUE_EUR / price_per_unit if price_per_unit > 0 else 0.0
            except Exception as e:
                logger.debug(f"Error calculando precio para {currency}: {e}")
                # Si no podemos calcular, usar el 25% directamente
                return order_size_25_percent
            
            # El tamaño es el máximo entre 25% y el mínimo en EUR
            swap_amount = max(order_size_25_percent, min_order_value_in_asset)
            
            # 🔒 PROTECCIÓN CONTRA POLVO: Verificar si al usar swap_amount, el resto sería < 10€
            # Caso borde: Si tenemos exactamente 10.01€ y usamos 25% (2.50€), quedarían 7.51€ (polvo)
            # Solución: Usar 100% del saldo para evitar orden huérfana por debajo del mínimo
            remaining_balance = operable_balance - swap_amount
            if remaining_balance > 0:
                try:
                    remaining_value_eur = self.vault.get_asset_value(currency, remaining_balance, 'EUR')
                    # Si el resto es < 10€, usar el 100% del saldo operable para evitar polvo
                    if remaining_value_eur < MIN_ORDER_VALUE_EUR:
                        swap_amount = operable_balance
                        logger.info(
                            f"🛡️ Protección contra polvo: Usando 100% del saldo operable de {currency} "
                            f"({operable_balance:.8f}) para evitar polvo. "
                            f"Resto sería {remaining_value_eur:.2f}€ < {MIN_ORDER_VALUE_EUR}€ (mínimo Binance)"
                        )
                except Exception as e:
                    logger.debug(f"Error verificando polvo para {currency}: {e}")
            
            # Asegurar que no exceda el saldo operable
            swap_amount = min(swap_amount, operable_balance)
            
            # Verificación final: Asegurar que el swap_amount tenga valor >= 10€
            try:
                final_value_eur = self.vault.get_asset_value(currency, swap_amount, 'EUR')
                if final_value_eur < MIN_ORDER_VALUE_EUR:
                    # Si aún no cumple el mínimo, retornar 0 (no se puede hacer swap)
                    logger.warning(
                        f"⚠️ Swap rechazado para {currency}: Valor calculado ({final_value_eur:.2f}€) "
                        f"menor al mínimo de Binance ({MIN_ORDER_VALUE_EUR}€)"
                    )
                    return 0.0
            except Exception as e:
                logger.debug(f"Error en verificación final de swap_amount para {currency}: {e}")
            
            return swap_amount
            
        except Exception as e:
            logger.error(f"Error calculando tamaño de orden para {currency}: {e}")
            return 0.0
    
    async def _get_dynamic_inventory(self) -> List[Dict[str, Any]]:
        """
        Genera inventario dinámico basado en los balances de Binance.
        Cada activo con saldo operable > 10€ aparece como una línea.
        
        Returns:
            Lista de diccionarios con información de cada activo en el inventario
        """
        inventory = []
        try:
            balances = self.exchange.fetch_balance()
            if not balances or 'total' not in balances:
                return inventory
            
            total_balances = balances.get('total', {})
            hucha_amounts = self._get_hucha_amount_per_currency()
            MIN_VALUE_EUR = 10.0
            MAX_INVESTMENT_PCT = 0.25  # Máximo 25% del valor total para invertir
            
            # Calcular valor total de inversión (para el límite del 25%)
            total_investment_value = self._calculate_total_investment_value()
            
            for currency, total_amount in total_balances.items():
                if total_amount <= 0:
                    continue
                
                # Excluir BNB (reservado para gas)
                if currency == 'BNB':
                    continue
                
                try:
                    # Calcular saldo operable (total - hucha)
                    hucha_amount = hucha_amounts.get(currency, 0.0)
                    operable_amount = max(0.0, total_amount - hucha_amount)
                    
                    if operable_amount <= 0:
                        continue
                    
                    # Calcular valor en EUR del saldo operable
                    value_eur = self.vault.get_asset_value(currency, operable_amount, 'EUR')
                    
                    if value_eur < MIN_VALUE_EUR:
                        continue
                    
                    # Obtener información de escalón y trailing stop si existe trade activo
                    escalon_label = "Sin protección activa"
                    stop_loss = 0.0
                    stop_loss_percent = 0.0
                    pnl_percent = 0.0
                    entry_price = 0.0
                    current_price = value_eur / operable_amount if operable_amount > 0 else 0.0
                    created_at = None
                    
                    # Buscar trade activo para este activo
                    active_trades = self.db.get_all_active_trades()
                    for trade in active_trades:
                        if trade.get('target_asset') == currency:
                            # Calcular PNL respecto al último swap
                            initial_value = trade.get('initial_fiat_value', 0)
                            if initial_value > 0:
                                pnl_percent = ((value_eur - initial_value) / initial_value) * 100
                            
                            entry_price = trade.get('entry_price', 0)
                            created_at = trade.get('created_at')
                            highest_price = trade.get('highest_price', entry_price)
                            
                            # Calcular información de escalón
                            escalon_info = self._calculate_escalon_info(
                                pnl_percent,
                                entry_price,
                                highest_price,
                                trade.get('stop_loss', entry_price * 0.999),
                                current_price
                            )
                            escalon_label = escalon_info.get('label', 'Sin protección activa')
                            stop_loss = escalon_info.get('stop_loss', 0)
                            stop_loss_percent = escalon_info.get('stop_loss_percent_from_current', 0)
                            break
                    
                    inventory_item = {
                        'currency': currency,
                        'operable_amount': operable_amount,
                        'value_eur': value_eur,
                        'pnl_percent': pnl_percent,
                        'escalon_label': escalon_label,
                        'stop_loss': stop_loss,
                        'stop_loss_percent': stop_loss_percent,
                        'entry_price': entry_price,
                        'current_price': current_price,
                        'created_at': created_at,
                        'max_investment_value': total_investment_value * MAX_INVESTMENT_PCT
                    }
                    inventory.append(inventory_item)
                    
                except Exception as e:
                    logger.debug(f"Error procesando {currency} para inventario: {e}")
                    continue
            
            # Ordenar por valor EUR descendente
            inventory.sort(key=lambda x: x.get('value_eur', 0), reverse=True)
            
        except Exception as e:
            logger.error(f"Error obteniendo inventario dinámico: {e}")
        
        return inventory
    
    def _calculate_real_investment_balance(self) -> Dict[str, Any]:
        """
        🎯 GESTIÓN DINÁMICA DE CAPITAL: Calcula el saldo real de inversión.
        
        Aplica descuentos en este orden:
        1. Reserva de Gas (BNB): 2.5% - 5% del valor total (intocable)
        2. Exclusión de Hucha: Resta activos en hucha_diversificada.json
        
        Returns:
            Dict con:
            - total_portfolio_eur: Valor total del portfolio
            - gas_reserve_eur: Valor reservado para gas (2.5-5%)
            - hucha_total_eur: Valor total en hucha
            - real_investment_balance_eur: Capital disponible para trading
            - gas_percentage: Porcentaje actual de gas
        """
        try:
            # Calcular valor total del portfolio
            total_portfolio_eur = self.vault.calculate_total_portfolio_value()
            if total_portfolio_eur <= 0:
                return {
                    'total_portfolio_eur': 0.0,
                    'gas_reserve_eur': 0.0,
                    'hucha_total_eur': 0.0,
                    'real_investment_balance_eur': 0.0,
                    'gas_percentage': 0.0
                }
            
            # 1. Reserva de Gas (BNB): 2.5% - 5% del valor total
            gas_percentage = self._get_gas_percentage()
            target_gas_percent = 5.0  # Objetivo: 5%
            gas_reserve_eur = total_portfolio_eur * (target_gas_percent / 100.0)
            
            # 2. Calcular valor total en hucha
            hucha_amounts = self._get_hucha_amount_per_currency()
            hucha_total_eur = 0.0
            balances = self.exchange.fetch_balance()
            
            for currency, amount in hucha_amounts.items():
                if amount > 0:
                    try:
                        value_eur = self.vault.get_asset_value(currency, amount, 'EUR')
                        hucha_total_eur += value_eur
                    except:
                        pass
            
            # 3. Saldo real de inversión (excluyendo Gas y Hucha)
            real_investment_balance_eur = max(0.0, total_portfolio_eur - gas_reserve_eur - hucha_total_eur)
            
            return {
                'total_portfolio_eur': total_portfolio_eur,
                'gas_reserve_eur': gas_reserve_eur,
                'hucha_total_eur': hucha_total_eur,
                'real_investment_balance_eur': real_investment_balance_eur,
                'gas_percentage': gas_percentage
            }
            
        except Exception as e:
            logger.error(f"Error calculando saldo real de inversión: {e}")
            return {
                'total_portfolio_eur': 0.0,
                'gas_reserve_eur': 0.0,
                'hucha_total_eur': 0.0,
                'real_investment_balance_eur': 0.0,
                'gas_percentage': 0.0
            }
    
    def _detect_overexposure(self) -> List[Dict[str, Any]]:
        """
        🎯 DETECCIÓN DE SOBREEXPOSICIÓN: Detecta activos que superan el 25% del capital real.
        
        Returns:
            Lista de activos sobreexpuestos con:
            - currency: Activo sobreexpuesto
            - current_value_eur: Valor actual en EUR
            - current_percent: Porcentaje actual del portfolio
            - excess_value_eur: Valor que excede el 25% (capital disponible para swaps)
            - excess_percent: Porcentaje de exceso sobre el 25%
        """
        try:
            # Calcular capital real de inversión
            capital_info = self._calculate_real_investment_balance()
            real_investment_balance_eur = capital_info.get('real_investment_balance_eur', 0.0)
            
            if real_investment_balance_eur <= 0:
                return []
            
            # Umbral máximo por activo (25% del capital real)
            MAX_POSITION_PCT = 0.25
            max_position_value_eur = real_investment_balance_eur * MAX_POSITION_PCT
            
            # Obtener balances operables (excluyendo FIAT y BNB de gas)
            balances = self.exchange.fetch_balance()
            total_balances = balances.get('total', {})
            
            overexposed = []
            
            # Excluir activos que no deben contarse (FIAT, BNB de gas)
            excluded_assets = {'EUR', 'USDC', 'BNB'}
            
            for currency, balance in total_balances.items():
                if currency in excluded_assets or balance <= 0:
                    continue
                
                try:
                    # Calcular valor en EUR
                    asset_value_eur = self.vault.get_asset_value(currency, balance, 'EUR')
                    if asset_value_eur <= 0:
                        continue
                    
                    # Calcular porcentaje sobre el capital real
                    asset_percent = (asset_value_eur / real_investment_balance_eur * 100.0) if real_investment_balance_eur > 0 else 0
                    
                    # Detectar sobreexposición (>25%)
                    if asset_percent > (MAX_POSITION_PCT * 100):
                        excess_value_eur = asset_value_eur - max_position_value_eur
                        excess_percent = (excess_value_eur / asset_value_eur * 100.0) if asset_value_eur > 0 else 0
                        
                        overexposed.append({
                            'currency': currency,
                            'current_value_eur': asset_value_eur,
                            'current_percent': asset_percent,
                            'excess_value_eur': excess_value_eur,
                            'excess_percent': excess_percent
                        })
                        
                except Exception as e:
                    logger.debug(f"Error detectando sobreexposición para {currency}: {e}")
                    continue
            
            return overexposed
            
        except Exception as e:
            logger.error(f"Error en _detect_overexposure: {e}")
            return []
    
    def _calculate_total_investment_value(self) -> float:
        """
        Calcula el valor total de inversión: suma de saldos operables + hucha convertidos a EUR.
        DEPRECATED: Usar _calculate_real_investment_balance() para nueva lógica.
        
        Returns:
            Valor total en EUR
        """
        try:
            balances = self.exchange.fetch_balance()
            total_balances = balances.get('total', {})
            valor_total = 0.0
            
            # Obtener saldos en hucha para excluirlos del saldo operable
            hucha_amounts = self._get_hucha_amount_per_currency()
            
            # Sumar todos los saldos operables (total - hucha)
            for currency, total_amount in total_balances.items():
                if total_amount <= 0:
                    continue
                
                # Excluir BNB del cálculo (BNB es solo para gas)
                if currency == 'BNB':
                    continue
                
                # Restar hucha de este activo
                hucha_amount = hucha_amounts.get(currency, 0.0)
                operable_amount = max(0.0, total_amount - hucha_amount)
                
                if operable_amount > 0:
                    asset_value = self.vault.get_asset_value(currency, operable_amount, 'EUR')
                    valor_total += asset_value
            
            # Sumar valor de la hucha
            for currency, hucha_amount in hucha_amounts.items():
                if hucha_amount > 0:
                    hucha_value = self.vault.get_asset_value(currency, hucha_amount, 'EUR')
                    valor_total += hucha_value
            
            return valor_total
        except Exception as e:
            logger.error(f"Error calculando valor total de inversión: {e}")
            # Fallback: usar calculate_total_portfolio_value
            return self.vault.calculate_total_portfolio_value()
    
    def _calculate_gas_reserve_separation(self) -> Dict[str, Any]:
        """
        🎯 SEPARACIÓN GAS/INVERSIÓN: Calcula saldos separados de BNB.
        
        BNB tiene dos propósitos:
        1. Reserva de Gas: 5% del portfolio total (intocable para trading)
        2. Inversión: Cualquier BNB adicional puede usarse en slots
        
        Returns:
            Dict con:
            - total_bnb: Balance total de BNB
            - gas_reserve_bnb: Cantidad reservada para gas (5% del portfolio)
            - investment_bnb: Cantidad disponible para inversión (resto)
            - gas_percentage: Porcentaje actual de gas sobre total
        """
        try:
            balances = self.exchange.fetch_balance()
            total_bnb = balances.get('total', {}).get('BNB', 0.0)
            
            # Calcular valor total del portfolio
            total_portfolio_eur = self.vault.calculate_total_portfolio_value()
            if total_portfolio_eur <= 0:
                return {
                    'total_bnb': total_bnb,
                    'gas_reserve_bnb': 0.0,
                    'investment_bnb': 0.0,
                    'gas_percentage': 0.0
                }
            
            # Calcular reserva de gas (5% del portfolio)
            target_gas_percent = 5.0
            gas_reserve_eur = total_portfolio_eur * (target_gas_percent / 100.0)
            
            # Convertir a BNB
            bnb_price_eur = self.vault.get_asset_value('BNB', 1.0, 'EUR')
            if bnb_price_eur <= 0:
                return {
                    'total_bnb': total_bnb,
                    'gas_reserve_bnb': 0.0,
                    'investment_bnb': 0.0,
                    'gas_percentage': 0.0
                }
            
            gas_reserve_bnb = gas_reserve_eur / bnb_price_eur
            
            # BNB de inversión = total - reserva (mínimo 0)
            investment_bnb = max(0.0, total_bnb - gas_reserve_bnb)
            
            # Calcular porcentaje actual
            gas_percentage = (total_bnb * bnb_price_eur / total_portfolio_eur * 100) if total_portfolio_eur > 0 else 0.0
            
            return {
                'total_bnb': total_bnb,
                'gas_reserve_bnb': gas_reserve_bnb,
                'investment_bnb': investment_bnb,
                'gas_percentage': gas_percentage
            }
            
        except Exception as e:
            logger.error(f"Error calculando separación gas/inversión: {e}")
            return {
                'total_bnb': 0.0,
                'gas_reserve_bnb': 0.0,
                'investment_bnb': 0.0,
                'gas_percentage': 0.0
            }
    
    def _get_gas_percentage(self) -> float:
        """
        Calcula el porcentaje de gas (BNB) respecto al valor total de inversión.
        
        NUEVO: Usa valor_total_inversion (saldos operables + hucha) en lugar de portfolio total.
        
        Returns:
            Porcentaje de gas (0.0 - 100.0)
        """
        try:
            valor_total_inversion = self._calculate_total_investment_value()
            if valor_total_inversion <= 0:
                return 0.0
            
            balances = self.exchange.fetch_balance()
            bnb_balance = balances.get('total', {}).get('BNB', 0.0)
            
            if bnb_balance <= 0:
                return 0.0
            
            bnb_value_eur = self.vault.get_asset_value('BNB', bnb_balance, 'EUR')
            gas_percent = (bnb_value_eur / valor_total_inversion * 100.0) if valor_total_inversion > 0 else 0.0
            
            return gas_percent
        except Exception as e:
            logger.debug(f"Error calculando porcentaje de gas: {e}")
            return 0.0
    
    async def _refill_gas_passive(self, bnb_amount: float, target_percent: float = None) -> float:
        """
        Rellena gas de forma pasiva reteniendo BNB de una operación.
        
        Args:
            bnb_amount: Cantidad de BNB disponible para retener
            target_percent: Porcentaje objetivo (default: gas_max_target)
        
        Returns:
            Cantidad de BNB retenida
        """
        if target_percent is None:
            target_percent = self.gas_max_target
        
        try:
            total_portfolio = self.vault.calculate_total_portfolio_value()
            if total_portfolio <= 0:
                return 0.0
            
            current_gas_percent = self._get_gas_percentage()
            
            if current_gas_percent >= target_percent:
                return 0.0  # Ya tenemos suficiente gas
            
            # Calcular cuánto BNB necesitamos en EUR
            target_gas_value_eur = total_portfolio * (target_percent / 100.0)
            balances = self.exchange.fetch_balance()
            current_bnb_balance = balances.get('BNB', {}).get('total', 0.0)
            current_bnb_value_eur = self.vault.get_asset_value('BNB', current_bnb_balance, 'EUR')
            needed_gas_value_eur = max(0, target_gas_value_eur - current_bnb_value_eur)
            
            if needed_gas_value_eur <= 0:
                return 0.0
            
            # Calcular cuánto BNB retener
            bnb_price_eur = self.vault.get_asset_value('BNB', 1.0, 'EUR')
            if bnb_price_eur <= 0:
                return 0.0
            
            needed_bnb = needed_gas_value_eur / bnb_price_eur
            bnb_to_retain = min(bnb_amount, needed_bnb)
            
            if bnb_to_retain > 0:
                logger.info(
                    f"⛽ Gas pasivo: Reteniendo {bnb_to_retain:.4f} BNB "
                    f"({bnb_to_retain * bnb_price_eur:.2f}€) para alcanzar {target_percent}%"
                )
                write_bitacora(
                    f"[⛽ GAS_RETENIDO] Gas reposición: Retenidos {bnb_to_retain:.4f} BNB "
                    f"({bnb_to_retain * bnb_price_eur:.2f}€) para mantener gas al {target_percent}%"
                )
            
            return bnb_to_retain
        except Exception as e:
            logger.error(f"Error en refill gas pasivo: {e}")
            return 0.0
    
    async def _refill_gas_emergency(self) -> bool:
        """
        NIVEL EMERGENCIA (< 0.5%): Detiene cualquier operación y compra BNB inmediatamente.
        Usa el activo con mayor saldo disponible para comprar BNB hasta alcanzar 2.5%.
        
        Returns:
            True si se ejecutó la compra, False en caso contrario
        """
        try:
            current_gas_percent = self._get_gas_percentage()
            
            # Solo ejecutar si está por debajo de 0.5%
            if current_gas_percent >= 0.5:
                return False  # No es emergencia
            
            valor_total_inversion = self._calculate_total_investment_value()
            if valor_total_inversion <= 0:
                return False
            
            # Objetivo: 2.5% del valor total de inversión
            target_percent = 2.5
            target_gas_value_eur = valor_total_inversion * (target_percent / 100.0)
            
            balances = self.exchange.fetch_balance()
            current_bnb_balance = balances.get('total', {}).get('BNB', 0.0)
            current_bnb_value_eur = self.vault.get_asset_value('BNB', current_bnb_balance, 'EUR')
            needed_gas_value_eur = max(0, target_gas_value_eur - current_bnb_value_eur)
            
            if needed_gas_value_eur <= 0:
                return False
            
            # Obtener saldos en hucha para calcular saldos operables
            hucha_amounts = self._get_hucha_amount_per_currency()
            
            # Buscar el activo con mayor saldo disponible (> 10€)
            best_asset = None
            best_asset_value_eur = 0.0
            best_asset_amount = 0.0
            
            for currency, total_amount in balances.get('total', {}).items():
                if currency == 'BNB' or total_amount <= 0:
                    continue
                
                # Calcular saldo operable (excluyendo hucha)
                hucha_amount = hucha_amounts.get(currency, 0.0)
                operable_amount = max(0.0, total_amount - hucha_amount)
                
                if operable_amount <= 0:
                    continue
                
                asset_value_eur = self.vault.get_asset_value(currency, operable_amount, 'EUR')
                
                # Solo considerar activos con valor > 10€
                if asset_value_eur > 10.0 and asset_value_eur > best_asset_value_eur:
                    best_asset = currency
                    best_asset_value_eur = asset_value_eur
                    best_asset_amount = operable_amount
            
            if not best_asset:
                logger.warning(f"⛽ Gas EMERGENCIA: No se encontró activo con saldo suficiente (> 10€) para comprar BNB")
                return False
            
            # Usar el mejor activo para comprar BNB
            # Buscar mejor ruta: best_asset -> BNB
            from router import find_swap_route
            
            route = find_swap_route(
                from_asset=best_asset,
                to_asset='BNB',
                whitelist=self.strategy["whitelist"],
                fiat_assets=self.fiat_assets,
                prefer_low_fees=False  # En emergencia, priorizar velocidad
            )
            
            if not route:
                logger.error(f"⛽ Gas EMERGENCIA: No se encontró ruta desde {best_asset} hacia BNB")
                return False
            
            swap_pair, intermediate = route
            
            # Calcular cuánto del activo necesitamos vender
            bnb_price_eur = self.vault.get_asset_value('BNB', 1.0, 'EUR')
            if bnb_price_eur <= 0:
                return False
            
            needed_bnb_amount = needed_gas_value_eur / bnb_price_eur
            
            # Estimar cantidad a vender (aproximado, puede variar por comisiones)
            asset_price_eur = self.vault.get_asset_value(best_asset, 1.0, 'EUR')
            if asset_price_eur <= 0:
                return False
            
            # Usar máximo lo necesario o el 50% del saldo (para no vaciar completamente)
            amount_to_sell_eur = min(needed_gas_value_eur * 1.02, best_asset_value_eur * 0.5)  # 2% extra por comisiones
            amount_to_sell = amount_to_sell_eur / asset_price_eur
            amount_to_sell = min(amount_to_sell, best_asset_amount)
            
            logger.warning(
                f"⛽ GAS CRÍTICO ({current_gas_percent:.2f}%) - EMERGENCIA: "
                f"Comprando BNB usando {best_asset} ({amount_to_sell:.8f})"
            )
            
            # Ejecutar swap
            sell_amount = self.exchange.amount_to_precision(swap_pair, amount_to_sell)
            order_sell = self.exchange.create_market_sell_order(swap_pair, sell_amount)
            
            filled_amount = order_sell.get('filled', 0)
            
            write_bitacora(
                f"[⛽ GAS_EMERGENCIA] Gas reposición: Comprado BNB usando {best_asset} "
                f"({amount_to_sell:.8f}) para restaurar gas al {target_percent}%"
            )
            
            logger.info(f"⛽ Gas emergencia ejecutado: {filled_amount:.8f} {best_asset} -> BNB")
            return True
            
        except Exception as e:
            logger.error(f"Error en compra de emergencia de gas: {e}")
            return False
    
    async def _refill_gas_strategic_improved(self) -> bool:
        """
        🎯 NIVEL ESTRATÉGICO (<2%): Buscar activamente BNB usando Radar.
        
        Reduce umbral de exigencia (Heat Score > 60) para facilitar recarga.
        Objetivo: Volver al 5% de gas.
        """
        try:
            MIN_ORDER_VALUE_EUR = 10.0
            target_gas_percent = 5.0
            
            gas_separation = self._calculate_gas_reserve_separation()
            current_gas_percent = gas_separation['gas_percentage']
            
            if current_gas_percent >= target_gas_percent:
                return False
            
            # Calcular cuánto BNB necesitamos
            total_portfolio_eur = self.vault.calculate_total_portfolio_value()
            target_gas_eur = total_portfolio_eur * (target_gas_percent / 100.0)
            current_gas_eur = total_portfolio_eur * (current_gas_percent / 100.0)
            needed_gas_eur = max(0.0, target_gas_eur - current_gas_eur)
            
            if needed_gas_eur < MIN_ORDER_VALUE_EUR:
                return False
            
            # 🎯 Buscar BNB en Radar con umbral reducido (Heat Score > 60)
            radar_list = []
            if self.radar_data_cache:
                for currency, data in self.radar_data_cache.items():
                    if currency == 'BNB':
                        radar_list.append(data.copy())
            else:
                try:
                    if HAS_FILE_UTILS:
                        radar_data = read_json_safe(self.radar_path, {})
                    else:
                        if self.radar_path.exists():
                            with open(self.radar_path, 'r', encoding='utf-8') as f:
                                radar_data = json.load(f)
                        else:
                            radar_data = {}
                    
                    if radar_data and 'radar_data' in radar_data:
                        for currency_data in radar_data.get('radar_data', []):
                            if currency_data.get('currency') == 'BNB':
                                radar_list.append(currency_data)
                except:
                    pass
            
            # Si BNB está en radar con Heat Score > 60, usar activo más débil para comprar
            bnb_heat_score = 0
            if radar_list:
                bnb_data = radar_list[0]
                bnb_heat_score = bnb_data.get('heat_score', 0)
            
            if bnb_heat_score < 60:
                logger.debug(f"BNB no está en radar con Heat Score suficiente (actual: {bnb_heat_score})")
                # Aún así, intentar comprar con activo más débil
                return await self._buy_bnb_with_weakest_asset(needed_gas_eur)
            
            # Si BNB tiene Heat Score > 60, buscar activo más débil para intercambiar
            return await self._buy_bnb_with_weakest_asset(needed_gas_eur)
            
        except Exception as e:
            logger.error(f"Error en refill gas estratégico mejorado: {e}")
            return False
    
    async def _buy_bnb_with_weakest_asset(self, needed_gas_eur: float) -> bool:
        """
        Compra BNB usando el activo con menor Heat Score (más débil).
        """
        try:
            MIN_ORDER_VALUE_EUR = 10.0
            
            balances = self.exchange.fetch_balance()
            active_trades = self.db.get_all_active_trades()
            
            # Buscar activo con menor Heat Score
            weakest_asset = None
            weakest_heat_score = 999999
            weakest_balance = 0.0
            
            for trade in active_trades:
                asset = trade.get('target_asset')
                if asset == 'BNB':
                    continue
                
                balance = balances.get('total', {}).get(asset, 0.0)
                if balance <= 0:
                    continue
                
                # Obtener Heat Score
                heat_score = await self._get_current_asset_heat_score(asset)
                if heat_score < weakest_heat_score:
                    weakest_heat_score = heat_score
                    weakest_asset = asset
                    weakest_balance = balance
            
            if not weakest_asset:
                logger.warning("No se encontró activo para comprar BNB estratégicamente")
                return False
            
            # Calcular cantidad a vender
            asset_price_eur = self.vault.get_asset_value(weakest_asset, 1.0, 'EUR')
            if asset_price_eur <= 0:
                return False
            
            amount_to_sell = needed_gas_eur / asset_price_eur
            amount_to_sell = min(amount_to_sell, weakest_balance)
            
            # Validar mínimo
            sell_value_eur = self.vault.get_asset_value(weakest_asset, amount_to_sell, 'EUR')
            if sell_value_eur < MIN_ORDER_VALUE_EUR:
                amount_to_sell = MIN_ORDER_VALUE_EUR / asset_price_eur
                amount_to_sell = min(amount_to_sell, weakest_balance)
            
            # Buscar par BNB
            bnb_pair = f"{weakest_asset}/BNB"
            if not get_pair_info(bnb_pair):
                bnb_pair = f"BNB/{weakest_asset}"
                if not get_pair_info(bnb_pair):
                    return False
            
            # Ejecutar compra
            try:
                sell_amount = self.exchange.amount_to_precision(bnb_pair, amount_to_sell)
                base, quote = bnb_pair.split('/')
                
                if base == weakest_asset:
                    order = self.exchange.create_market_sell_order(bnb_pair, sell_amount)
                else:
                    order = self.exchange.create_market_buy_order(bnb_pair, sell_amount)
                
                if order and order.get('filled', 0) > 0:
                    filled = order.get('filled', 0)
                    logger.info(
                        f"✅ Gas estratégico: Comprado BNB usando {weakest_asset} "
                        f"(Heat: {weakest_heat_score}, cantidad: {filled:.8f})"
                    )
                    return True
            except Exception as e:
                logger.error(f"Error comprando BNB estratégicamente: {e}")
                return False
            
            return False
            
        except Exception as e:
            logger.error(f"Error en _buy_bnb_with_weakest_asset: {e}")
            return False
    
    async def _refill_gas_strategic(self) -> bool:
        """
        NIVEL ESTRATÉGICO (< 2.5%): Busca en el Radar la moneda operable (>10€) 
        que tenga el mejor par de intercambio hacia BNB y ejecuta una compra hasta alcanzar 5%.
        
        Returns:
            True si se ejecutó la compra, False en caso contrario
        """
        try:
            current_gas_percent = self._get_gas_percentage()
            
            # Solo ejecutar si está entre 0.5% y 2.5%
            if current_gas_percent < 0.5 or current_gas_percent >= 2.5:
                return False
            
            valor_total_inversion = self._calculate_total_investment_value()
            if valor_total_inversion <= 0:
                return False
            
            # Objetivo: 5% del valor total de inversión
            target_percent = 5.0
            target_gas_value_eur = valor_total_inversion * (target_percent / 100.0)
            
            balances = self.exchange.fetch_balance()
            current_bnb_balance = balances.get('total', {}).get('BNB', 0.0)
            current_bnb_value_eur = self.vault.get_asset_value('BNB', current_bnb_balance, 'EUR')
            needed_gas_value_eur = max(0, target_gas_value_eur - current_bnb_value_eur)
            
            if needed_gas_value_eur <= 0:
                return False
            
            # Obtener monedas de la wallet con balance > 10 USD
            wallet_currencies = await self._get_wallet_currencies_for_radar()
            
            if not wallet_currencies:
                logger.debug("⛽ Gas estratégico: No hay monedas en wallet para buscar mejor par")
                return False
            
            # Buscar la mejor moneda del radar que tenga buen par hacia BNB
            best_currency = None
            best_swap_pair = None
            best_heat_score = 0
            
            hucha_amounts = self._get_hucha_amount_per_currency()
            
            for currency in wallet_currencies:
                if currency == 'BNB':
                    continue
                
                # Verificar que tenga saldo operable > 10€
                total_amount = balances.get('total', {}).get(currency, 0.0)
                hucha_amount = hucha_amounts.get(currency, 0.0)
                operable_amount = max(0.0, total_amount - hucha_amount)
                
                if operable_amount <= 0:
                    continue
                
                asset_value_eur = self.vault.get_asset_value(currency, operable_amount, 'EUR')
                if asset_value_eur <= 10.0:
                    continue
                
                # Verificar si hay par directo o ruta hacia BNB
                from router import find_swap_route
                
                route = find_swap_route(
                    from_asset=currency,
                    to_asset='BNB',
                    whitelist=self.strategy["whitelist"],
                    fiat_assets=self.fiat_assets,
                    prefer_low_fees=True
                )
                
                if route:
                    swap_pair, intermediate = route
                    
                    # Si hay ruta, obtener heat_score de la moneda del radar
                    heat_score = 0
                    if self.radar_data_cache and currency in self.radar_data_cache:
                        heat_score = self.radar_data_cache[currency].get('heat_score', 0)
                    
                    # Preferir monedas con menor heat_score (mejor momento para venderlas)
                    if not best_currency or heat_score < best_heat_score:
                        best_currency = currency
                        best_swap_pair = swap_pair
                        best_heat_score = heat_score
            
            if not best_currency or not best_swap_pair:
                logger.debug("⛽ Gas estratégico: No se encontró moneda adecuada con par hacia BNB")
                return False
            
            # Calcular cantidad a vender (máximo 50% del saldo operable)
            total_amount = balances.get('total', {}).get(best_currency, 0.0)
            hucha_amount = hucha_amounts.get(best_currency, 0.0)
            operable_amount = max(0.0, total_amount - hucha_amount)
            
            asset_price_eur = self.vault.get_asset_value(best_currency, 1.0, 'EUR')
            bnb_price_eur = self.vault.get_asset_value('BNB', 1.0, 'EUR')
            
            if asset_price_eur <= 0 or bnb_price_eur <= 0:
                return False
            
            # Calcular cantidad a vender para obtener BNB necesario (con margen de comisiones)
            amount_to_sell_eur = min(needed_gas_value_eur * 1.02, operable_amount * asset_price_eur * 0.5)
            amount_to_sell = amount_to_sell_eur / asset_price_eur
            amount_to_sell = min(amount_to_sell, operable_amount)
            
            logger.info(
                f"⛽ Gas ESTRATÉGICO ({current_gas_percent:.2f}%): "
                f"Comprando BNB usando {best_currency} (heat_score: {best_heat_score})"
            )
            
            # Ejecutar swap
            sell_amount = self.exchange.amount_to_precision(best_swap_pair, amount_to_sell)
            order_sell = self.exchange.create_market_sell_order(best_swap_pair, sell_amount)
            
            filled_amount = order_sell.get('filled', 0)
            
            write_bitacora(
                f"[⛽ GAS_ESTRATÉGICO] Gas reposición: Comprado BNB usando {best_currency} "
                f"({amount_to_sell:.8f}) para alcanzar {target_percent}%"
            )
            
            logger.info(f"⛽ Gas estratégico ejecutado: {filled_amount:.8f} {best_currency} -> BNB")
            return True
            
        except Exception as e:
            logger.error(f"Error en compra estratégica de gas: {e}")
            return False
        except Exception as e:
            logger.error(f"Error en _refill_gas_strategic: {e}")
            return False

    async def manage_gas_level(self) -> bool:
        """
        Gestión automática de gas (BNB).

        - Si el porcentaje de gas está por debajo de `gas_critical`, ejecuta compra de emergencia
        - Si está por debajo del umbral estratégico (2%), intenta recarga estratégica
        - Si realiza una acción de compra devuelve True (prioridad alta)
        """
        try:
            current_gas = self._get_gas_percentage()
            # Emergencia: < gas_critical (p.ej. 1%) -> compra inmediata
            if current_gas < self.gas_critical:
                logger.warning(f"⛽ manage_gas_level: Gas crítico ({current_gas:.2f}%), ejecutando compra de emergencia")
                performed = await self._refill_gas_emergency()
                if performed:
                    write_bitacora(f"[⛽ MANAGE_GAS] Compra de emergencia ejecutada por gas crítico ({current_gas:.2f}%)")
                    return True
                return False

            # Estratégico: < 2% -> intentar refill estratégico mejorado
            if current_gas < 2.0:
                logger.info(f"⛽ manage_gas_level: Gas reducido ({current_gas:.2f}%), intentando recarga estratégica")
                performed = await self._refill_gas_strategic_improved()
                if performed:
                    write_bitacora(f"[⛽ MANAGE_GAS] Recarga estratégica ejecutada (gas {current_gas:.2f}%)")
                    return True
                # fallback a refill strategico normal
                performed = await self._refill_gas_strategic()
                if performed:
                    write_bitacora(f"[⛽ MANAGE_GAS] Recarga estratégica (fallback) ejecutada (gas {current_gas:.2f}%)")
                    return True

            return False
        except Exception as e:
            logger.error(f"Error en manage_gas_level: {e}")
            return False
    
    async def _check_btc_panic_mode(self) -> bool:
        """Verifica si BTC ha caído más de 2.5% en la última hora."""
        try:
            btc_pairs = ['BTC/EUR', 'BTC/USDC', 'BTC/USDT']
            current_price = None
            
            for pair in btc_pairs:
                try:
                    ticker = self.exchange.fetch_ticker(pair)
                    current_price = ticker['last']
                    if current_price:
                        break
                except:
                    continue
            
            if not current_price:
                return False
            
            try:
                ohlcv = self.exchange.fetch_ohlcv('BTC/EUR', '1h', limit=2)
                if len(ohlcv) >= 2:
                    price_1h_ago = ohlcv[0][4]
                    price_change = ((current_price - price_1h_ago) / price_1h_ago) * 100
                    
                    if price_change < -2.5:
                        logger.warning(f"Modo Cautela activado: BTC cayó {price_change:.2f}% en la última hora")
                        return True
            except Exception as e:
                logger.debug(f"Error al obtener precio histórico de BTC: {e}")
            
            return False
        except Exception as e:
            logger.error(f"Error al verificar modo pánico BTC: {e}")
            return False
    
    async def _detect_existing_positions(self):
        """Detecta posiciones existentes en la wallet y las asigna a slots disponibles."""
        if self.positions_detected:
            return
        
        try:
            print("DEBUG: Escaneando wallet para detectar posiciones existentes...")
            balances = self.exchange.fetch_balance()
            print("DEBUG: Balances obtenidos, analizando posiciones...")
            
            if not balances or 'total' not in balances:
                logger.warning("No se pudieron obtener balances para detectar posiciones")
                return
            
            max_slots = self.strategy["trading"]["max_slots"]
            occupied_slots = set()
            for slot_id in range(max_slots):
                active_trade = self.db.get_active_trade(slot_id)
                if active_trade:
                    occupied_slots.add(slot_id)
            
            for currency, total_balance in balances['total'].items():
                if total_balance > 0.0001:
                    if currency not in self.fiat_assets:
                        already_in_slot = False
                        for slot_id in range(max_slots):
                            active_trade = self.db.get_active_trade(slot_id)
                            if active_trade and active_trade.get('target_asset') == currency:
                                already_in_slot = True
                                break
                        
                        if not already_in_slot and len(occupied_slots) < max_slots:
                            free_slot = None
                            for slot_id in range(max_slots):
                                if slot_id not in occupied_slots:
                                    free_slot = slot_id
                                    break
                            
                            if free_slot is not None:
                                try:
                                    # Calcular el valor total del activo
                                    asset_value_eur = self.vault.get_asset_value(currency, total_balance, 'EUR')
                                    
                                    # Calcular monto por slot: (total - gas_reserve) / max_slots
                                    total_portfolio_eur = self.vault.calculate_total_portfolio_value()
                                    if total_portfolio_eur <= 0:
                                        # Si no podemos calcular el total, usar solo el valor del activo
                                        total_portfolio_eur = asset_value_eur
                                    
                                    gas_reserve_eur = total_portfolio_eur * 0.05
                                    available_for_trading = max(0.0, total_portfolio_eur - gas_reserve_eur)
                                    monto_por_slot_eur = available_for_trading / max_slots if max_slots > 0 else 0.0
                                    
                                    # Limitar el valor inicial al monto por slot
                                    initial_value_eur = min(asset_value_eur, monto_por_slot_eur)
                                    
                                    # Si el valor es menor al mínimo de Binance, no crear el trade
                                    if initial_value_eur < 10.0:
                                        logger.debug(
                                            f"Omitiendo {currency}: valor ({initial_value_eur:.2f}€) menor al mínimo de Binance (10€)"
                                        )
                                        continue
                                    
                                    # Calcular la cantidad proporcional del activo
                                    amount_to_use = total_balance * (initial_value_eur / asset_value_eur) if asset_value_eur > 0 else 0
                                    
                                    logger.info(
                                        f"Detectando posición existente: {currency} - "
                                        f"Valor total: {asset_value_eur:.2f}€, "
                                        f"Limitando a monto por slot: {initial_value_eur:.2f}€ "
                                        f"(cantidad: {amount_to_use:.8f} de {total_balance:.8f})"
                                    )
                                    
                                    symbol = None
                                    for base in self.fiat_assets:
                                        try:
                                            pair_candidates = get_available_pairs(base)
                                            for pair in pair_candidates:
                                                if currency in pair:
                                                    symbol = pair
                                                    break
                                            if symbol:
                                                break
                                        except:
                                            continue
                                    
                                    if not symbol:
                                        symbol = f"{currency}/EUR"
                                    
                                    # Calcular precio de entrada usando la cantidad limitada
                                    entry_price = initial_value_eur / amount_to_use if amount_to_use > 0 else 0
                                    
                                    trade_id = self.db.create_trade(
                                        slot_id=free_slot,
                                        symbol=symbol,
                                        base_asset='EUR',
                                        target_asset=currency,
                                        amount=amount_to_use,
                                        entry_price=entry_price,
                                        initial_fiat_value=initial_value_eur,
                                        highest_price=entry_price,
                                        path_history=currency,
                                        is_active=True
                                    )
                                    
                                    occupied_slots.add(free_slot)
                                    
                                    logger.info(
                                        f"Posición existente detectada: {currency} ({amount_to_use:.8f} de {total_balance:.8f}) "
                                        f"asignada al Slot {free_slot + 1}. Valor inicial: {initial_value_eur:.2f} EUR "
                                        f"(limitado a monto por slot de {monto_por_slot_eur:.2f}€)"
                                    )
                                    
                                except Exception as e:
                                    logger.error(f"Error al procesar posición existente {currency}: {e}")
            
            self.positions_detected = True
            logger.info("Detección de posiciones existentes completada")
            
        except Exception as e:
            logger.error(f"Error al detectar posiciones existentes: {e}")
    
    async def monitor_active_trades(self):
        """
        ⚡ VIGILANCIA RÁPIDA: Monitorea trades activos (alta prioridad, cada 5s).
        Esta función es ligera y rápida, solo verifica trades activos.
        Aplica trailing stop escalonado, rotación activa y RE-EQUILIBRIO AUTOMÁTICO.
        """
        try:
            # 🎯 RE-EQUILIBRIO AUTOMÁTICO: Detectar y corregir sobreexposición
            overexposed = self._detect_overexposure()
            
            if overexposed:
                for item in overexposed:
                    currency = item.get('currency')
                    excess_value_eur = item.get('excess_value_eur', 0)
                    current_percent = item.get('current_percent', 0)
                    
                    if excess_value_eur > 10.0:  # Solo reequilibrar si el exceso es > 10€
                        logger.warning(
                            f"⚠️ SOBREEXPOSICIÓN DETECTADA: {currency} al {current_percent:.1f}% "
                            f"(exceso: {excess_value_eur:.2f}€). Iniciando diversificación automática..."
                        )
                        
                        # 🎯 DIVERSIFICACIÓN AUTOMÁTICA: Buscar activamente mejor destino en whitelist
                        # NO usar EUR, buscar activos de la whitelist con par directo
                        whitelist_destination = await self._find_best_whitelist_destination(
                            source_asset=currency,
                            exclude_assets=[currency]
                        )
                        
                        if whitelist_destination:
                            logger.info(
                                f"🌱 Diversificación automática: {currency} -> {whitelist_destination} "
                                f"(exceso: {excess_value_eur:.2f}€)"
                            )
                            # Ejecutar swap directo al destino de whitelist
                            rebalanced = await self._rebalance_to_whitelist_asset(
                                currency, excess_value_eur, whitelist_destination
                            )
                        else:
                            # Si no hay destino en whitelist, usar reequilibrio tradicional
                            rebalanced = await self._rebalance_overexposed_asset(currency, excess_value_eur)
                        
                        if rebalanced:
                            logger.info(
                                f"✅ Reequilibrio completado para {currency}. "
                                f"Exceso de {excess_value_eur:.2f}€ vendido y redistribuido."
                            )
                        else:
                            logger.warning(f"⚠️ No se pudo reequilibrar {currency}. Se intentará en el próximo ciclo.")
            
            # Monitorear todos los trades activos (sin límite de max_slots)
            active_trades = self.db.get_all_active_trades()
            
            for trade in active_trades:
                try:
                    slot_id = trade.get('slot_id')
                    if slot_id is not None:
                        # Vigilancia rápida: trailing stop escalonado y rotación activa
                        await self._evaluate_slot_optimized(slot_id, trade)
                except Exception as e:
                    logger.error(f"Error al monitorear trade {trade.get('id')}: {e}")
                continue
        
        except Exception as e:
            logger.error(f"Error en monitor_active_trades: {e}")
    
    async def scan_new_opportunities(self):
        """
        🔍 ESCANEO DINÁMICO: Busca nuevas oportunidades con slots variables.
        
        🎯 GESTIÓN DINÁMICA DE CAPITAL:
        - Slots variables: No hay máximo fijo de 4
        - Cada slot respeta el 25% del capital real de inversión
        - Mínimo 10€ por slot (requisito de Binance)
        - Si hay sobreexposición, prioriza reequilibrio antes de nuevas entradas
        """
        try:
            btc_panic_mode = await self._check_btc_panic_mode()
            
            if btc_panic_mode:
                logger.debug("Modo Cautela activo - no se escanean nuevas oportunidades")
                return
            
            # 🎯 Calcular saldo real de inversión (excluyendo Gas y Hucha)
            investment_data = self._calculate_real_investment_balance()
            real_investment_balance = investment_data['real_investment_balance_eur']
            
            if real_investment_balance < 10.0:
                logger.debug(f"Capital insuficiente para nuevas oportunidades: {real_investment_balance:.2f}€ < 10€")
                return
            
            # 🎯 Detectar sobreexposición (>25%)
            overexposed = self._detect_overexposure()
            
            # 🎯 RE-EQUILIBRIO PROACTIVO: Si hay sobreexposición, intentar reequilibrar primero
            if overexposed:
                logger.info(
                    f"🔄 Reequilibrio proactivo: {len(overexposed)} activos sobreexpuestos. "
                    f"Capital disponible: {sum(o.get('excess_value_eur', 0) for o in overexposed):.2f}€"
                )
                # El reequilibrio se hará automáticamente cuando el Radar detecte una oportunidad caliente
                # y se seleccione el activo sobreexpuesto como origen
            
            # 🎯 Calcular capacidad estimada de slots (dinámico)
            MAX_POSITION_PCT = 0.25  # 25% por posición
            MIN_SLOT_VALUE_EUR = 10.0  # Mínimo de Binance
            estimated_capacity = int(real_investment_balance / (real_investment_balance * MAX_POSITION_PCT)) if real_investment_balance > 0 else 0
            # Asegurar mínimo de 1 slot si hay capital
            if real_investment_balance >= MIN_SLOT_VALUE_EUR and estimated_capacity == 0:
                estimated_capacity = 1
            
            # Obtener slots actualmente activos
            active_trades = self.db.get_all_active_trades()
            active_slots_count = len(active_trades)
            
            # 🎯 SLOTS VARIABLES: Buscar nuevas oportunidades si hay capacidad
            # No hay máximo fijo, solo verificar que cada nueva entrada respete el 25%
            if active_slots_count < estimated_capacity or (overexposed and len(overexposed) > 0):
                # Buscar oportunidad caliente en el radar
                radar_assigned = await self._assign_from_radar_dynamic()
                if not radar_assigned:
                    # Fallback: escaneo tradicional desde fiat
                    await self._scan_fiat_entry_dynamic()
                else:
                    logger.debug(
                        f"Capacidad alcanzada: {active_slots_count} slots activos / "
                        f"{estimated_capacity} estimados (capital: {real_investment_balance:.2f}€)"
                    )
        except Exception as e:
            logger.error(f"Error en scan_new_opportunities: {e}")

    async def _assign_from_radar_dynamic(self) -> bool:
        """
        🎯 ASIGNACIÓN DINÁMICA DESDE RADAR: Asigna activos sin límite de slots fijos.
        
        Busca oportunidades calientes y las asigna respetando:
        - 25% del capital real de inversión por posición
        - Mínimo 10€ por posición
        - Prioriza reequilibrio de activos sobreexpuestos
        
        Returns:
            True si se asignó una oportunidad, False en caso contrario
        """
        try:
            # Calcular saldo real de inversión
            investment_data = self._calculate_real_investment_balance()
            real_investment_balance = investment_data['real_investment_balance_eur']
            MAX_POSITION_PCT = 0.25
            max_position_value = real_investment_balance * MAX_POSITION_PCT
            
            # Obtener umbral de heat_score
            min_heat_score = self.strategy.get("trading", {}).get("radar_min_heat_score", 85)
            
            # Obtener monedas activas
            active_assets = self._get_active_assets()

            # Priorizar gestión de gas antes de asignar desde radar
            try:
                gas_action = await self.manage_gas_level()
                if gas_action:
                    logger.info("Acción de gestión de gas ejecutada. Prioridad satisfecha.")
                    return True
            except Exception:
                pass
            
            # Leer radar
            radar_list = []
            if self.radar_data_cache:
                for currency, data in self.radar_data_cache.items():
                    radar_list.append(data.copy())
                radar_list.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
            else:
                try:
                    if HAS_FILE_UTILS:
                        radar_data = read_json_safe(self.radar_path, {})
                    else:
                        if self.radar_path.exists():
                            with open(self.radar_path, 'r', encoding='utf-8') as f:
                                radar_data = json.load(f)
                        else:
                            radar_data = {}
                    
                    if radar_data and 'radar_data' in radar_data:
                        radar_list = radar_data.get('radar_data', [])
                except:
                    pass
            
            if not radar_list:
                return False
            
                        # Buscar la mejor oportunidad caliente (priorizar por heat más alto)
            radar_list = sorted(radar_list, key=lambda x: x.get('heat_score', 0), reverse=True)

            for currency_data in radar_list:
                currency = currency_data.get('currency', '')
                heat_score = currency_data.get('heat_score', 0)
                
                # 🎯 Tratar EUR/USDC como activos normales (solo excluir BNB para gas)
                if currency == 'BNB':
                    continue
                # EUR y USDC ahora se tratan como activos normales en el radar
                if currency in active_assets:
                    continue
                # Requerir heat mínimo configurado
                if heat_score < min_heat_score:
                    continue
                # Requerir que esté en whitelist
                if currency not in self.strategy.get("whitelist", []):
                    continue
                # Requerir Heat > 80 y Triple Green para diversificación
                final_triple_green = currency_data.get('triple_green', False)
                if heat_score <= 80 or not final_triple_green:
                    logger.debug(f"Candidato {currency} rechazado: heat={heat_score}, triple_green={final_triple_green}")
                    continue
                # Cooldown global de diversificación
                if self.last_diversify_time and (time.time() - self.last_diversify_time) < self.diversify_cooldown_seconds:
                    logger.info("Saltando diversificación: cooldown activo")
                    continue
                
                # 🎯 SELECCIÓN DE ORIGEN MEJORADA
                origin_result = await self._select_best_origin_asset_improved(currency, heat_score, max_position_value)
                
                if origin_result:
                    origin_asset, pair, origin_heat_score, is_overexposed = origin_result
                    base_asset = origin_asset
                    is_fiat_entry = (origin_asset in self.fiat_assets)
                    
                    logger.info(
                        f"🎯 Oportunidad Caliente: {currency} (Heat: {heat_score}) "
                        f"desde {origin_asset} (Heat: {origin_heat_score}) "
                        f"{'[SOBREEXPUESTO]' if is_overexposed else ''}"
                    )
                    
                    # Calcular tamaño de posición (25% del capital real)
                    position_size_eur = min(max_position_value, real_investment_balance * MAX_POSITION_PCT)
                    
                    if is_fiat_entry:
                        success = await self.execute_buy_dynamic(
                            pair=pair,
                            base_asset=base_asset,
                            target_asset=currency,
                            position_size_eur=position_size_eur,
                            confidence=heat_score / 100.0,
                            signal_data=currency_data
                        )
                    else:
                        success = await self.execute_swap_dynamic(
                            origin_asset=origin_asset,
                            target_asset=currency,
                            pair=pair,
                            position_size_eur=position_size_eur,
                            heat_score=heat_score,
                            signal_data=currency_data
                        )
                    
                    if success:
                        # Registrar tiempo de última diversificación
                        try:
                            self.last_diversify_time = time.time()
                        except Exception:
                            pass
                        return True
                
            return False
                    
        except Exception as e:
            logger.error(f"Error en _assign_from_radar_dynamic: {e}")
            return False
    
    async def execute_buy_dynamic(self, pair: str, base_asset: str, target_asset: str, 
                                   position_size_eur: float, confidence: float, signal_data: Dict[str, Any]) -> bool:
        """
        🎯 EJECUCIÓN DINÁMICA DE COMPRA: Similar a execute_buy pero con tamaño dinámico.
        """
        try:
            # Buscar slot disponible (dinámico)
            active_trades = self.db.get_all_active_trades()
            used_slot_ids = {trade.get('slot_id') for trade in active_trades}
            
            free_slot = None
            for slot_id in range(100):
                if slot_id not in used_slot_ids:
                    free_slot = slot_id
                    break
            
            if free_slot is None:
                logger.warning("No hay slots disponibles (límite de 100 alcanzado)")
                return False
            
            # Usar execute_buy existente
            success = await self.execute_buy(
                slot_id=free_slot,
                pair=pair,
                base_asset=base_asset,
                target_asset=target_asset,
                is_fiat_entry=True,
                confidence=confidence,
                signal_data=signal_data
            )
            
            if success:
                logger.info(
                    f"✅ Compra dinámica ejecutada: {target_asset} en slot {free_slot + 1} "
                    f"(Tamaño objetivo: {position_size_eur:.2f}€)"
                )
            
            return success
            
        except Exception as e:
            logger.error(f"Error en execute_buy_dynamic: {e}")
            return False
    
    async def execute_swap_dynamic(self, origin_asset: str, target_asset: str, pair: str,
                                    position_size_eur: float, heat_score: int, signal_data: Dict[str, Any]=None,
                                    require_triple_green: bool = True) -> bool:
        """
        🎯 EJECUCIÓN DINÁMICA DE SWAP: Fracciona solo el 25% necesario, no todo el balance.
        
        Cuando se abre un slot desde un activo sobreexpuesto (ej. XRP 91%), solo se vende
        la cantidad necesaria para cubrir el 25% del capital en la nueva moneda.
        
        Args:
            origin_asset: Activo de origen (ej. XRP)
            target_asset: Activo destino (ej. ETH)
            pair: Par de trading (ej. XRP/ETH)
            position_size_eur: Tamaño objetivo de la posición (25% del capital)
            heat_score: Heat Score del destino
        
        Returns:
            True si el swap fue exitoso, False en caso contrario
        """
        try:
            MIN_ORDER_VALUE_EUR = 10.0

            # Protección: exigir heat>80 antes de diversificar
            if heat_score <= 80:
                logger.warning(f"Swap rechazado por heat insuficiente ({heat_score} <= 80)")
                self._log_bitacora(f"[SWAP_REJECT] {origin_asset}→{target_asset}: Heat insuficiente ({heat_score} <= 80)")
                return False
            
            # Si se requiere triple_green (diversificación desde Radar), verificar indicadores
            if require_triple_green:
                # AUDITORÍA: Extraer valores de indicadores para logging
                rsi_value = signal_data.get('rsi') if signal_data else None
                ema_distance = signal_data.get('ema200_distance') if signal_data else None
                volume_status = signal_data.get('volume_status', 'N/A') if signal_data else 'N/A'
                triple_green = False
                
                try:
                    triple_green = (signal_data.get('triple_green') if signal_data else False)
                except Exception:
                    triple_green = False
                
                # LOG DE AUDITORÍA: Registrar condiciones en bitacora.txt
                audit_msg = (
                    f"[BUY_CHECK] Revisando condiciones para {pair}: "
                    f"RSI={rsi_value if rsi_value else 'N/A'}, "
                    f"EMA={ema_distance if ema_distance else 'N/A'}, "
                    f"VOL={volume_status}, "
                    f"Triple_Green={triple_green}, "
                    f"Heat={heat_score}"
                )
                self._log_bitacora(audit_msg)
                logger.info(audit_msg)
                
                if not triple_green:
                    logger.warning(f"Swap rechazado: indicadores no en verde (triple_green={triple_green})")
                    self._log_bitacora(f"[SWAP_REJECT] {origin_asset}→{target_asset}: Triple_Green=False")
                    return False
            
            # Obtener balance total del activo de origen
            balances = self.exchange.fetch_balance()
            total_balance = balances.get('total', {}).get(origin_asset, 0.0)
            # Excluir hucha: no vender lo que está marcado como reserva
            try:
                hucha_amounts = self._get_hucha_amount_per_currency()
                hucha_amount = hucha_amounts.get(origin_asset, 0.0)
            except Exception:
                hucha_amount = 0.0
            operable_balance = max(0.0, total_balance - hucha_amount)

            if operable_balance <= 0:
                logger.warning(f"No hay balance operable de {origin_asset} para fraccionar (hucha excluida)")
                return False
            
            # 🎯 Calcular cantidad exacta a vender (solo el 25% necesario)
            # Convertir position_size_eur a cantidad del activo de origen
            origin_price_eur = self.vault.get_asset_value(origin_asset, 1.0, 'EUR')
            if origin_price_eur <= 0:
                logger.warning(f"No se puede obtener precio de {origin_asset}")
                return False
            
            # Cantidad necesaria para obtener position_size_eur en el destino
            # Primero necesitamos el precio del par para calcular cuánto recibiremos
            try:
                ticker = self.exchange.fetch_ticker(pair)
                if not ticker:
                    logger.warning(f"No se puede obtener ticker para {pair}")
                    return False
                
                # Determinar dirección del par
                base, quote = pair.split('/')
                if base == origin_asset:
                    # Par directo: origin/target - vendemos origin para recibir target
                    price = ticker.get('bid', ticker.get('last', 0))
                    # Cantidad de origin necesaria para obtener position_size_eur en target
                    target_price_eur = self.vault.get_asset_value(target_asset, 1.0, 'EUR')
                    if target_price_eur <= 0:
                        logger.warning(f"No se puede obtener precio de {target_asset}")
                        return False
                    
                    # Calcular cantidad de target que queremos
                    target_amount_desired = position_size_eur / target_price_eur
                    # Calcular cantidad de origin necesaria (considerando comisión)
                    taker_fee = 0.001  # 0.1% de Binance
                    origin_amount_needed = (target_amount_desired / price) / (1 - taker_fee)
                else:
                    # Par inverso: target/origin - compramos target con origin
                    price = ticker.get('ask', ticker.get('last', 0))
                    target_price_eur = self.vault.get_asset_value(target_asset, 1.0, 'EUR')
                    if target_price_eur <= 0:
                        return False
                    
                    target_amount_desired = position_size_eur / target_price_eur
                    # Para comprar target_amount_desired, necesitamos origin_amount_needed
                    origin_value_eur_needed = (target_amount_desired * price) / (1 - taker_fee)
                    origin_amount_needed = origin_value_eur_needed / origin_price_eur
                
                # 🎯 VALIDACIÓN DE MÍNIMOS Y POLVO
                # Verificar que el remanente no quede < 10€ (usar balance operable)
                remaining_balance = operable_balance - origin_amount_needed
                remaining_value_eur = self.vault.get_asset_value(origin_asset, remaining_balance, 'EUR')

                if remaining_value_eur < MIN_ORDER_VALUE_EUR and remaining_balance > 0:
                    # Si el remanente sería < 10€, liquidar el 100% para evitar polvo
                    logger.info(
                        f"⚠️ Remanente sería {remaining_value_eur:.2f}€ (< 10€). "
                        f"Liquidando 100% de {origin_asset} para evitar polvo."
                    )
                    origin_amount_needed = operable_balance
                else:
                    # Limitar a balance operable disponible
                    origin_amount_needed = min(origin_amount_needed, operable_balance)
                
                # Validar que el swap sea >= 10€
                swap_value_eur = self.vault.get_asset_value(origin_asset, origin_amount_needed, 'EUR')
                if swap_value_eur < MIN_ORDER_VALUE_EUR:
                    logger.warning(
                        f"Swap rechazado: Valor calculado ({swap_value_eur:.2f}€) < mínimo ({MIN_ORDER_VALUE_EUR}€)"
                    )
                    return False
                
                logger.info(
                    f"🎯 Fraccionamiento: Vendiendo {origin_amount_needed:.8f} {origin_asset} "
                    f"({swap_value_eur:.2f}€) de {operable_balance:.8f} operable "
                    f"(remanente: {remaining_balance:.8f} = {remaining_value_eur:.2f}€) "
                    f"→ {target_asset} (objetivo: {position_size_eur:.2f}€)"
                )
                
            except Exception as e:
                logger.error(f"Error calculando cantidad para fraccionamiento: {e}")
                return False
            
            # Buscar trade activo del origen (si existe)
            active_trades = self.db.get_all_active_trades()
            origin_trade = None
            origin_slot_id = None
            
            for trade in active_trades:
                if trade.get('target_asset') == origin_asset:
                    origin_trade = trade
                    origin_slot_id = trade.get('slot_id')
                    break
            
            # Si hay trade activo, usar execute_swap pero con cantidad limitada
            if origin_trade:
                # Crear un trade temporal con la cantidad fraccionada
                temp_trade = origin_trade.copy()
                temp_trade['amount'] = origin_amount_needed
                
                trade_id = origin_trade.get('id')
                success = await self.execute_swap(
                    slot_id=origin_slot_id,
                    trade_id=trade_id,
                    current_trade=temp_trade,
                    new_pair=pair,
                    new_target_asset=target_asset
                )
            else:
                # Si no hay trade activo, ejecutar swap directo desde balance
                try:
                    sell_amount = self.exchange.amount_to_precision(pair, origin_amount_needed)
                    
                    if base == origin_asset:
                        order = self.exchange.create_market_sell_order(pair, sell_amount)
                    else:
                        # Par inverso: necesitamos comprar
                        order = self.exchange.create_market_buy_order(pair, sell_amount)
                    
                    if order and order.get('filled', 0) > 0:
                        filled = order.get('filled', 0)
                        logger.info(
                            f"✅ Swap fraccionado ejecutado: {origin_asset} → {target_asset} "
                            f"(cantidad: {filled:.8f}, valor: {swap_value_eur:.2f}€)"
                        )
                        # Registrar en bitácora si es diversificación (requiere triple_green)
                        try:
                            if require_triple_green:
                                write_bitacora(f"DIVERSIFICACIÓN: Vendiendo {swap_value_eur:.2f}€ de {origin_asset} por {target_asset} debido a sobreexposición")
                        except Exception:
                            pass
                        
                        # Crear nuevo trade para el destino
                        free_slot = None
                        for slot_id in range(100):
                            if slot_id not in {t.get('slot_id') for t in active_trades}:
                                free_slot = slot_id
                                break
                        
                        if free_slot is not None:
                            executed_price = order.get('price', ticker.get('last', 0))
                            target_amount = filled if base == origin_asset else order.get('filled', 0)
                            
                            # 🎯 HUCHA SELECTIVA EN SWAPS DINÁMICOS
                            # Calcular beneficio solo de la porción extraída
                            origin_trade_for_hucha = None
                            if origin_trade:
                                # Calcular valor inicial de la porción extraída
                                origin_initial_value = origin_trade.get('initial_fiat_value', 0)
                                origin_total_amount = origin_trade.get('amount', 0)
                                
                                if origin_total_amount > 0:
                                    # Proporción de la porción extraída respecto al trade original
                                    portion_ratio = origin_amount_needed / origin_total_amount
                                    portion_initial_value = origin_initial_value * portion_ratio
                                    
                                    # Calcular beneficio de la porción extraída
                                    portion_profit_eur = swap_value_eur - portion_initial_value
                                    portion_profit_percent = (portion_profit_eur / portion_initial_value * 100) if portion_initial_value > 0 else 0
                                    
                                    # Si hay beneficio Y el destino está en RESERVE_ASSETS, detraer 5%
                                    hucha_amount = 0.0
                                    if portion_profit_percent > 0 and target_asset in self.RESERVE_ASSETS:
                                        hucha_amount = target_amount * 0.05  # 5% del target recibido
                                        target_amount = target_amount * 0.95  # 95% para el slot
                                        
                                        # Guardar hucha
                                        try:
                                            hucha_value_eur = self.vault.get_asset_value(target_asset, hucha_amount, 'EUR')
                                            if hucha_value_eur > 0.01:
                                                self.db.add_to_treasury(
                                                    amount_eur=hucha_value_eur if target_asset in ['EUR', 'USDC'] else 0.0,
                                                    amount_btc=hucha_amount if target_asset == 'BTC' else 0.0,
                                                    description=f"Hucha Selectiva - Swap {origin_asset} → {target_asset}"
                                                )
                                                # Persistir también en hucha_diversificada.json
                                                try:
                                                    await self._save_hucha_diversificada(target_asset, hucha_amount, hucha_value_eur)
                                                except Exception:
                                                    logger.debug("No se pudo persistir en hucha_diversificada.json (ya en treasury).")

                                                write_bitacora(
                                                    f"[💎 HUCHA_SAVE] {target_asset}: {hucha_value_eur:.2f}€ guardados "
                                                    f"(5% de beneficio de porción extraída: {portion_profit_eur:.2f}%)"
                                                )
                                                
                                                logger.info(
                                                    f"💰 Hucha selectiva: {hucha_value_eur:.2f}€ en {target_asset} "
                                                    f"guardados desde swap fraccionado (beneficio: {portion_profit_percent:.2f}%)"
                                                )
                                        except Exception as e:
                                            logger.error(f"Error guardando hucha selectiva: {e}")
                            
                            # Calcular initial_fiat_value restando el valor de la hucha si existe
                            hucha_value_eur = self.vault.get_asset_value(target_asset, hucha_amount, 'EUR') if hucha_amount > 0 else 0.0
                            initial_fiat_value = swap_value_eur - hucha_value_eur
                            
                            self.db.create_trade(
                                slot_id=free_slot,
                                symbol=pair,
                                base_asset=origin_asset,
                                target_asset=target_asset,
                                amount=target_amount,
                                entry_price=executed_price,
                                initial_fiat_value=initial_fiat_value,
                                path_history=f"{origin_asset} > {target_asset}"
                            )
                            
                            write_bitacora(
                                f"[🔄 SWAP_DIVERSIFICACIÓN] {origin_asset} → {target_asset}: "
                                f"{swap_value_eur:.2f}€ (25% del capital, remanente: {remaining_value_eur:.2f}€ en {origin_asset})"
                            )
                            
                            success = True
                        else:
                            success = False
                    else:
                        success = False
                except Exception as e:
                    logger.error(f"Error ejecutando swap fraccionado: {e}")
                    success = False
            
            if success:
                logger.info(
                    f"✅ Swap dinámico fraccionado ejecutado: {origin_asset} → {target_asset} "
                    f"(Tamaño: {position_size_eur:.2f}€, Remanente: {remaining_value_eur:.2f}€ en {origin_asset})"
                )
            
            return success
            
        except Exception as e:
            logger.error(f"Error en execute_swap_dynamic: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    async def _scan_fiat_entry_dynamic(self) -> bool:
        """
        🎯 ESCANEO DINÁMICO DESDE FIAT: Similar a _scan_fiat_entry pero sin límite de slots.
        """
        try:
            # Calcular saldo real de inversión
            investment_data = self._calculate_real_investment_balance()
            real_investment_balance = investment_data['real_investment_balance_eur']
            
            if real_investment_balance < 10.0:
                return False
            
            # Buscar slot disponible
            active_trades = self.db.get_all_active_trades()
            used_slot_ids = {trade.get('slot_id') for trade in active_trades}
            
            free_slot = None
            for slot_id in range(100):
                if slot_id not in used_slot_ids:
                    free_slot = slot_id
                    break
            
            if free_slot is None:
                return False
            
            # Usar _assign_from_radar con slot dinámico (fallback)
            # Por ahora, retornamos False para que se use el radar primero
            return False
            
        except Exception as e:
            logger.error(f"Error en _scan_fiat_entry_dynamic: {e}")
            return False
    
    async def _check_and_refill_gas(self) -> bool:
        """
        🎯 PROTOCOLO DE GAS BNB (3 NIVELES): Coordinador automático con separación inversión/gas.
        
        Niveles:
        - Nivel Ahorro (>5%): Modo pasivo, retener comisión extra en swaps
        - Nivel Estratégico (<2%): Buscar activamente BNB con Radar (Heat Score > 60)
        - Nivel Emergencia (<1%): Comprar BNB inmediatamente con activo más rentable
        
        Returns:
            True si se ejecutó alguna acción de gas, False en caso contrario
        """
        try:
            gas_separation = self._calculate_gas_reserve_separation()
            current_gas_percent = gas_separation['gas_percentage']
            
            # NIVEL EMERGENCIA (< 1%): Modo pánico
            if current_gas_percent < 1.0:
                logger.warning(f"⛽ GAS CRÍTICO ({current_gas_percent:.2f}%) - Activando modo EMERGENCIA")
                result = await self._refill_gas_emergency()
                if result:
                    write_bitacora(f"[⛽ GAS_EMERGENCIA] Gas reposición: Gas recargado desde {current_gas_percent:.2f}% hasta {self._get_gas_percentage():.2f}%")
                    logger.info(f"✅ Gas emergencia ejecutado. Nuevo nivel: {self._get_gas_percentage():.2f}%")
                    return True
                else:
                    logger.error("❌ Gas emergencia falló")
                    return False
            
            # NIVEL ESTRATÉGICO (< 2%): Modo búsqueda activa
            elif current_gas_percent < 2.0:
                logger.info(f"⛽ Gas bajo ({current_gas_percent:.2f}%) - Activando recarga ESTRATÉGICA (búsqueda activa)")
                result = await self._refill_gas_strategic_improved()
                if result:
                    write_bitacora(f"[⛽ GAS_ESTRATÉGICO] Gas reposición: Gas recargado desde {current_gas_percent:.2f}% hasta {self._get_gas_percentage():.2f}%")
                    logger.info(f"✅ Gas estratégico ejecutado. Nuevo nivel: {self._get_gas_percentage():.2f}%")
                    return True
                else:
                    logger.debug(f"Gas estratégico no se ejecutó (puede que ya esté en proceso o no haya recursos)")
                    return False
            
            # NIVEL AHORRO (>= 5%): Modo pasivo
            # El nivel pasivo se maneja automáticamente durante los swaps
            # Si un swap encuentra ruta óptima a través de BNB, retener comisión extra
            return False
            
        except Exception as e:
            logger.error(f"Error en verificación automática de gas: {e}")
            return False
    
    async def run_bot_cycle(self, monitor_only: bool = False):
        """
        Ejecuta un ciclo del bot.
        
        Args:
            monitor_only: Si True, solo monitorea trades activos (rápido).
                         Si False, también escanea nuevas oportunidades (lento).
        """
        # 🎯 PRIORIDAD 0: Actualizar portfolio value al inicio de cada tick
        # Esto asegura que _detect_overexposure() siempre tenga datos correctos
        try:
            capital_info = self._calculate_real_investment_balance()
            self.total_portfolio_value = capital_info.get('total_portfolio_eur', 0.0)
            if self.total_portfolio_value <= 0:
                # Fallback: calcular desde vault directamente
                self.total_portfolio_value = self.vault.calculate_total_portfolio_value() or 0.0
        except Exception as e:
            logger.debug(f"Error actualizando portfolio value al inicio del tick: {e}")
            try:
                self.total_portfolio_value = self.vault.calculate_total_portfolio_value() or 0.0
            except:
                self.total_portfolio_value = 0.0
        
        # ⛽ PRIORIDAD 1: Verificar y reponer gas (BNB) si es necesario
        # Esto se ejecuta primero para asegurar que hay gas para cualquier operación
        await self._check_and_refill_gas()
        
        # Siempre monitorear trades activos (rápido)
        await self.monitor_active_trades()
        
        # Escanear nuevas oportunidades solo si no es monitor_only
        if not monitor_only:
            await self.scan_new_opportunities()
    
    async def scan_opportunities(self):
        """
        DEPRECATED: Usar run_bot_cycle() en su lugar.
        Mantenido para compatibilidad.
        """
        await self.run_bot_cycle(monitor_only=False)
    
    async def _select_best_origin_asset_improved(self, target_asset: str, target_heat_score: int, max_position_value: float) -> Optional[Tuple[str, str, float, bool]]:
        """
        🎯 SELECCIÓN DE ORIGEN MEJORADA: Prioriza FIAT y activos sobreexpuestos.
        
        Orden de prioridad:
        1. FIAT (EUR/USDC) si hay saldo > 10€
        2. Activo sobreexpuesto (>25%) con menor Heat Score
        3. Activo con menor Heat Score (eslabón más débil)
        
        Args:
            target_asset: Activo destino
            target_heat_score: Heat Score del destino
            max_position_value: Valor máximo permitido por posición (25% del capital)
        
        Returns:
            Tupla (origin_asset, pair, origin_heat_score, is_overexposed) o None
        """
        try:
            # PRIORIDAD 1: Verificar FIAT disponible
            balances = self.exchange.fetch_balance()
            free_balances = balances.get('free', {})
            
            for fiat in self.fiat_assets:
                fiat_balance = free_balances.get(fiat, 0.0)
                if fiat_balance > 0:
                    fiat_value_eur = fiat_balance if fiat == 'EUR' else self.vault.get_asset_value('USDC', fiat_balance, 'EUR')
                    if fiat_value_eur >= 10.0:
                        # Verificar que hay par disponible
                        pair = f"{target_asset}/{fiat}"
                        if get_pair_info(pair):
                            logger.info(
                                f"💰 Origen FIAT seleccionado: {fiat} ({fiat_value_eur:.2f}€) "
                                f"→ {target_asset} (Heat: {target_heat_score})"
                            )
                            return (fiat, pair, 0, False)  # FIAT tiene Heat Score 0
            
            # PRIORIDAD 2: Activos sobreexpuestos (>25%)
            overexposed = self._detect_overexposure()
            if overexposed:
                # Obtener Heat Scores de activos sobreexpuestos
                overexposed_candidates = []
                # Leer hucha para evitar usar activos de reserva
                hucha_amounts = self._get_hucha_amount_per_currency()
                for item in overexposed:
                    currency = item.get('currency')
                    if currency == target_asset or currency == 'BNB':
                        continue
                    # Ignorar moneda si está en la hucha diversificada
                    try:
                        if hucha_amounts.get(currency, 0.0) > 0:
                            logger.debug(f"Ignorando {currency} como origen porque está en hucha")
                            continue
                    except Exception:
                        pass
                    
                    try:
                        origin_heat_score = await self._get_current_asset_heat_score(currency)
                        route = find_swap_route(
                            currency,
                            target_asset,
                            self.strategy["whitelist"],
                            self.fiat_assets,
                            prefer_low_fees=True
                        )
                        
                        if route and origin_heat_score > 0:
                            if isinstance(route, tuple):
                                pair, intermediate = route
                            else:
                                pair = route
                                intermediate = None
                            
                            overexposed_candidates.append({
                                'asset': currency,
                                'heat_score': origin_heat_score,
                                'pair': pair,
                                'excess_value_eur': item.get('excess_value_eur', 0),
                                'intermediate': intermediate
                            })
                    except:
                        continue
                
                if overexposed_candidates:
                    # Seleccionar el sobreexpuesto con menor Heat Score
                    best_overexposed = min(overexposed_candidates, key=lambda x: x['heat_score'])
                    logger.info(
                        f"🔄 Reequilibrio: Origen sobreexpuesto seleccionado: {best_overexposed['asset']} "
                        f"(Heat: {best_overexposed['heat_score']}, Exceso: {best_overexposed['excess_value_eur']:.2f}€) "
                        f"→ {target_asset} (Heat: {target_heat_score})"
                    )
                    return (best_overexposed['asset'], best_overexposed['pair'], best_overexposed['heat_score'], True)
            
            # PRIORIDAD 3: Activo con menor Heat Score (eslabón más débil)
            return await self._select_best_origin_asset(target_asset, target_heat_score)
            
        except Exception as e:
            logger.error(f"Error en _select_best_origin_asset_improved: {e}")
            return None
    
    async def _check_centinela_effect(self) -> bool:
        """
        🎯 EFECTO CENTINELA: Rotación de capital estancado cuando hay oportunidad hirviente.
        
        Si el Radar detecta una oportunidad con Heat Score > 95 (Oportunidad Hirviente)
        y no hay capital libre (FIAT), el bot está autorizado a detraer el capital necesario
        (25% del valor de cartera) del activo más débil de la wallet (menor Heat Score).
        
        Returns:
            True si se ejecutó una rotación centinela, False en caso contrario
        """
        try:
            MIN_HEAT_SCORE_CENTINELA = 95  # Oportunidad hirviente
            MIN_ORDER_VALUE_EUR = 10.0
            
            # 🛡️ VALIDAR COOLDOWN
            import time
            current_time = time.time()
            
            if self.last_centinela_swap_time is not None:
                time_since_last = current_time - self.last_centinela_swap_time
                if time_since_last < self.centinela_cooldown_seconds:
                    remaining_minutes = int((self.centinela_cooldown_seconds - time_since_last) / 60)
                    logger.debug(
                        f"⏳ Efecto Centinela en cooldown: {remaining_minutes} minutos restantes "
                        f"(último swap hace {int(time_since_last/60)} minutos)"
                    )
                    return False
            
            # Leer radar para buscar oportunidades hirvientes
            radar_list = []
            if self.radar_data_cache:
                for currency, data in self.radar_data_cache.items():
                    radar_list.append(data.copy())
                radar_list.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
            else:
                try:
                    if HAS_FILE_UTILS:
                        radar_data = read_json_safe(self.radar_path, {})
                    else:
                        if self.radar_path.exists():
                            with open(self.radar_path, 'r', encoding='utf-8') as f:
                                radar_data = json.load(f)
                        else:
                            radar_data = {}
                    
                    if radar_data and 'radar_data' in radar_data:
                        radar_list = radar_data.get('radar_data', [])
                        radar_list.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
                except:
                    pass
            
            if not radar_list:
                return False
            
            # Buscar oportunidad hirviente (Heat Score > 95)
            hot_opportunity = None
            for currency_data in radar_list:
                currency = currency_data.get('currency', '')
                heat_score = currency_data.get('heat_score', 0)
                
                if heat_score >= MIN_HEAT_SCORE_CENTINELA:
                    if currency not in ['BNB'] and currency in self.strategy.get("whitelist", []):
                        hot_opportunity = currency_data
                        break
            
            if not hot_opportunity:
                return False  # No hay oportunidad hirviente
            
            hot_currency = hot_opportunity.get('currency', '')
            hot_heat_score = hot_opportunity.get('heat_score', 0)
            
            logger.info(
                f"🔥 EFECTO CENTINELA ACTIVADO: Oportunidad hirviente detectada: {hot_currency} "
                f"(Heat Score: {hot_heat_score})"
            )
            
            # Verificar que no hay capital libre (FIAT)
            balances = self.exchange.fetch_balance()
            free_balances = balances.get('free', {})
            has_free_fiat = False
            
            for fiat in self.fiat_assets:
                fiat_balance = free_balances.get(fiat, 0.0)
                if fiat_balance > 0:
                    fiat_value_eur = fiat_balance if fiat == 'EUR' else self.vault.get_asset_value('USDC', fiat_balance, 'EUR')
                    if fiat_value_eur >= MIN_ORDER_VALUE_EUR:
                        has_free_fiat = True
                        break
            
            if has_free_fiat:
                logger.debug("Efecto Centinela: Hay capital libre (FIAT), no se requiere rotación")
                return False
            
            # 🎯 Buscar activo más débil (menor Heat Score)
            active_trades = self.db.get_all_active_trades()
            weakest_asset = None
            weakest_heat_score = 999999
            weakest_trade = None
            
            for trade in active_trades:
                asset = trade.get('target_asset', '')
                if asset == 'BNB' or asset == hot_currency:
                    continue
                
                # Obtener Heat Score del activo
                asset_heat_score = await self._get_current_asset_heat_score(asset)
                
                if asset_heat_score < weakest_heat_score:
                    weakest_heat_score = asset_heat_score
                    weakest_asset = asset
                    weakest_trade = trade
            
            if not weakest_asset or not weakest_trade:
                logger.debug("Efecto Centinela: No se encontró activo débil para rotar")
                return False
            
            # 🛡️ VALIDAR DIFERENCIA MÍNIMA DE HEAT SCORE
            heat_score_diff = hot_heat_score - weakest_heat_score
            
            if heat_score_diff < self.centinela_min_heat_diff:
                logger.info(
                    f"⏸️ Efecto Centinela: Diferencia insuficiente de Heat Score "
                    f"({heat_score_diff} puntos < mínimo {self.centinela_min_heat_diff}). "
                    f"No vale la pena por comisiones: {weakest_asset} ({weakest_heat_score}) → "
                    f"{hot_currency} ({hot_heat_score})"
                )
                return False
            
            logger.info(
                f"✅ Efecto Centinela: Diferencia válida de Heat Score "
                f"({heat_score_diff} puntos >= mínimo {self.centinela_min_heat_diff}). "
                f"Rotación justificada: {weakest_asset} ({weakest_heat_score}) → "
                f"{hot_currency} ({hot_heat_score})"
            )
            
            # Calcular 25% del capital para la nueva posición
            investment_data = self._calculate_real_investment_balance()
            real_investment_balance = investment_data['real_investment_balance_eur']
            position_size_eur = real_investment_balance * 0.25
            
            if position_size_eur < MIN_ORDER_VALUE_EUR:
                logger.debug(f"Efecto Centinela: Posición calculada ({position_size_eur:.2f}€) < mínimo ({MIN_ORDER_VALUE_EUR}€)")
                return False
            
            # Buscar ruta de swap: weakest_asset → hot_currency
            from router import find_swap_route
            route = find_swap_route(
                weakest_asset,
                hot_currency,
                self.strategy["whitelist"],
                self.fiat_assets,
                prefer_low_fees=True
            )
            
            if not route:
                logger.debug(f"Efecto Centinela: No se encontró ruta {weakest_asset} → {hot_currency}")
                return False
            
            if isinstance(route, tuple):
                pair, intermediate = route
            else:
                pair = route
                intermediate = None
            
            logger.info(
                f"🔄 EFECTO CENTINELA: Rotando {weakest_asset} (Heat: {weakest_heat_score}) "
                f"→ {hot_currency} (Heat: {hot_heat_score})"
            )
            
            # Ejecutar swap dinámico (centinela no requiere triple_green)
            success = await self.execute_swap_dynamic(
                origin_asset=weakest_asset,
                target_asset=hot_currency,
                pair=pair,
                position_size_eur=position_size_eur,
                heat_score=hot_heat_score,
                signal_data=None,
                require_triple_green=False
            )
            
            if success:
                # Actualizar timestamp del último swap centinela
                import time
                self.last_centinela_swap_time = time.time()
                
                write_bitacora(
                    f"[🔄 SWAP_CENTINELA] {weakest_asset} (Heat: {weakest_heat_score}) → "
                    f"{hot_currency} (Heat: {hot_heat_score}) | Dif: +{heat_score_diff} | "
                    f"{position_size_eur:.2f}€ rotados"
                )
                logger.info(
                    f"✅ Efecto Centinela ejecutado: {weakest_asset} → {hot_currency} "
                    f"({position_size_eur:.2f}€, diferencia Heat Score: +{heat_score_diff} puntos). "
                    f"Cooldown activado: {int(self.centinela_cooldown_seconds/60)} minutos"
                )
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error en efecto centinela: {e}")
            return False
    
    async def _select_best_origin_asset(self, target_asset: str, target_heat_score: int) -> Optional[Tuple[str, str, float]]:
        """
        Selecciona el mejor activo de origen (el que tiene el Heat Score más bajo) 
        para hacer swap hacia target_asset.
        
        Esta función implementa la filosofía de "vender el eslabón más débil" para 
        comprar el activo con mayor potencial.
        
        Args:
            target_asset: Activo destino (el que queremos comprar)
            target_heat_score: Heat Score del activo destino
        
        Returns:
            Tupla (origin_asset, pair, origin_heat_score) o None si no hay activo adecuado
            - origin_asset: Activo de origen seleccionado (el que tiene menor heat_score)
            - pair: Par de intercambio a usar (source/target o target/source)
            - origin_heat_score: Heat Score del activo de origen
        """
        try:
            # Obtener monedas operables de la wallet (> 10€)
            wallet_currencies = await self._get_wallet_currencies_for_radar()
            
            if not wallet_currencies:
                logger.debug(f"No hay activos operables en wallet para seleccionar origen hacia {target_asset}")
                return None
            
            # Calcular heat_score de cada activo operable
            origin_candidates = []
            
            for currency in wallet_currencies:
                if currency == target_asset or currency == 'BNB':
                    continue  # No podemos usar el mismo activo o BNB como origen
                
                try:
                    # Obtener heat_score actual del activo
                    origin_heat_score = await self._get_current_asset_heat_score(currency)
                    
                    # Verificar que haya una ruta disponible
                    route = find_swap_route(
                        currency,
                        target_asset,
                        self.strategy["whitelist"],
                        self.fiat_assets,
                        prefer_low_fees=True
                    )
                    
                    if route and origin_heat_score > 0:
                        # route puede ser (pair, intermediate) o solo pair
                        if isinstance(route, tuple):
                            pair, intermediate = route
                        else:
                            pair = route
                            intermediate = None
                        
                        origin_candidates.append({
                            'asset': currency,
                            'heat_score': origin_heat_score,
                            'pair': pair,
                            'intermediate': intermediate
                        })
                except Exception as e:
                    logger.debug(f"Error evaluando {currency} como origen: {e}")
                    continue
            
            if not origin_candidates:
                logger.debug(f"No se encontraron candidatos válidos como origen para {target_asset}")
                return None
            
            # Seleccionar el activo con menor heat_score (el "eslabón más débil")
            best_origin = min(origin_candidates, key=lambda x: x['heat_score'])
            
            intermediate_info = f" (vía {best_origin['intermediate']})" if best_origin.get('intermediate') else ""
            logger.info(
                f"🎯 Origen seleccionado: {best_origin['asset']} (Heat: {best_origin['heat_score']}) "
                f"→ {target_asset} (Heat: {target_heat_score}) | "
                f"Par: {best_origin['pair']}{intermediate_info}"
            )
            
            return (best_origin['asset'], best_origin['pair'], best_origin['heat_score'])
            
        except Exception as e:
            logger.error(f"Error seleccionando mejor origen para {target_asset}: {e}")
            return None
    
    async def _assign_from_radar(self, slot_id: int, min_heat_score: int = None) -> bool:
        """
        Asigna automáticamente una moneda del Radar a un slot vacío.
        
        Condiciones:
        - Slot debe estar IDLE (sin trade activo)
        - Moneda debe tener heat_score > 85 (configurable)
        - No debe haber otro slot operando con la misma moneda
        - Debe cumplir validaciones de balance y mínimos
        
        Returns:
            True si se asignó una moneda, False en caso contrario
        """
        try:
            # Obtener umbral de heat_score desde parámetro o configuración
            if min_heat_score is None:
                min_heat_score = self.strategy.get("trading", {}).get("radar_min_heat_score", 85)
            
            # Obtener monedas activas en otros slots
            active_assets = self._get_active_assets()
            
            # Leer radar.json o usar cache del motor
            radar_list = []
            if self.radar_data_cache:
                # Usar cache del radar dinámico
                for currency, data in self.radar_data_cache.items():
                    radar_list.append(data.copy())
                radar_list.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
            else:
                # Intentar leer desde archivo
                try:
                    if HAS_FILE_UTILS:
                        radar_data = read_json_safe(self.radar_path, {})
                    else:
                        if self.radar_path.exists():
                            with open(self.radar_path, 'r', encoding='utf-8') as f:
                                radar_data = json.load(f)
                        else:
                            radar_data = {}
                    
                    if radar_data and 'radar_data' in radar_data:
                        radar_list = radar_data.get('radar_data', [])
                except:
                    pass
            
            if not radar_list:
                return False
            
            # Buscar la mejor moneda disponible del radar
            for currency_data in radar_list:
                currency = currency_data.get('currency', '')
                heat_score = currency_data.get('heat_score', 0)
                
                # Verificar condiciones
                # 🎯 Tratar EUR/USDC como activos normales (solo excluir BNB para gas)
                if currency == 'BNB':
                    continue
                # EUR y USDC ahora se tratan como activos normales
                
                if currency in active_assets:
                    logger.debug(f"Moneda {currency} ya está activa en otro slot")
                    continue
                
                if heat_score < min_heat_score:
                    logger.debug(f"Moneda {currency} tiene heat_score ({heat_score}) menor al mínimo ({min_heat_score})")
                    continue
                
                # Verificar que esté en la whitelist
                if currency not in self.strategy.get("whitelist", []):
                    continue
                
                # 🎯 SELECCIÓN DE ORIGEN POR HEAT SCORE (Eslabón más Débil)
                # Analiza todos los activos operables (>10€) y elige el que tiene el Heat Score más bajo
                # Esto asegura que vendemos el activo con menor potencial de subida inmediata
                origin_result = await self._select_best_origin_asset(currency, heat_score)
                
                if origin_result:
                    origin_asset, pair, origin_heat_score = origin_result
                    base_asset = origin_asset
                    is_fiat_entry = (origin_asset in self.fiat_assets)
                    
                    logger.info(
                        f"🎯 Radar → Slot {slot_id + 1}: Swap {origin_asset} (Heat: {origin_heat_score}) "
                        f"→ {currency} (Heat: {heat_score}) | Par: {pair}"
                    )
                    
                    # Usar execute_swap si el origen no es fiat, execute_buy si es fiat
                    if is_fiat_entry:
                        success = await self.execute_buy(
                            slot_id=slot_id,
                            pair=pair,
                            base_asset=base_asset,
                            target_asset=currency,
                            is_fiat_entry=True,
                            confidence=heat_score / 100.0,
                            signal_data=currency_data
                        )
                    else:
                        # Para swaps entre activos, necesitamos usar execute_swap
                        # Primero necesitamos obtener el trade activo del origen (si existe)
                        # Pero como estamos en un slot vacío, esto es una nueva entrada
                        # Por ahora, usamos execute_buy con el pair encontrado
                        # TODO: Mejorar para usar execute_swap directamente cuando el origen no es fiat
                        success = await self.execute_buy(
                            slot_id=slot_id,
                            pair=pair,
                            base_asset=base_asset,
                            target_asset=currency,
                            is_fiat_entry=False,
                            confidence=heat_score / 100.0,
                            signal_data=currency_data
                        )
                else:
                    # Fallback: Intentar compra desde fiat (comportamiento original)
                    pair = None
                    base_asset = None
                    for fiat in self.fiat_assets:
                        candidate_pair = f"{currency}/{fiat}"
                        if get_pair_info(candidate_pair):
                            pair = candidate_pair
                            base_asset = fiat
                            break
                    
                    if not pair:
                        continue
                    
                    logger.info(
                        f"🎯 Radar → Slot {slot_id + 1}: Asignando {currency} desde fiat "
                        f"(heat_score: {heat_score}, pair: {pair})"
                    )
                    
                    success = await self.execute_buy(
                        slot_id=slot_id,
                        pair=pair,
                        base_asset=base_asset,
                        target_asset=currency,
                        is_fiat_entry=True,
                        confidence=heat_score / 100.0,
                        signal_data=currency_data
                    )
                
                if success:
                    write_bitacora(
                        f"[🛒 COMPRA_SLOT] Slot {slot_id + 1}: {currency} asignada desde Radar "
                        f"(Heat Score: {heat_score})"
                    )
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error en asignación desde radar para slot {slot_id}: {e}")
            return False
    
    async def _scan_fiat_entry(self, slot_id: int):
        """Escanea oportunidades de entrada desde fiat (EUR/USDC)."""
        logger.debug(f"Escaneando entrada fiat para slot {slot_id}")
        
        MIN_ORDER_VALUE_EUR = 10.0  # Mínimo de Binance
        
        active_assets = self._get_active_assets()
        whitelist = self.strategy["whitelist"].copy()
        max_slots = self.strategy["trading"]["max_slots"]
        
        # Obtener balances para calcular disponibilidad
        balances = self.exchange.fetch_balance()
        
        # Calcular el valor total del portfolio
        total_portfolio_eur = self.vault.calculate_total_portfolio_value()
        if total_portfolio_eur <= 0:
            # Si calculate_total_portfolio_value retorna 0, calcular manualmente
            total_portfolio_eur = 0.0
            for asset, balance_data in balances.get('total', {}).items():
                if balance_data > 0:
                    asset_value = self.vault.get_asset_value(asset, balance_data, 'EUR')
                    total_portfolio_eur += asset_value
        
        # Reservar 5% para gas (BNB)
        gas_reserve_eur = total_portfolio_eur * 0.05
        available_for_trading = max(0.0, total_portfolio_eur - gas_reserve_eur)
        
        # Calcular monto por slot
        monto_por_slot_eur = available_for_trading / max_slots if max_slots > 0 else 0.0
        
        logger.debug(
            f"Portfolio total: {total_portfolio_eur:.2f}€, "
            f"Reserva gas (5%): {gas_reserve_eur:.2f}€, "
            f"Disponible trading: {available_for_trading:.2f}€, "
            f"Monto por slot: {monto_por_slot_eur:.2f}€"
        )
        
        # Si el monto por slot es menor al mínimo, no podemos operar
        if monto_por_slot_eur < MIN_ORDER_VALUE_EUR:
            logger.warning(
                f"Monto por slot ({monto_por_slot_eur:.2f}€) menor al mínimo de Binance ({MIN_ORDER_VALUE_EUR}€). "
                f"No se pueden abrir nuevos slots."
            )
            return
        
        # BNB permanece en la whitelist - si se opera con BNB, se reservará 5% para gas
        current_gas_percent = self._get_gas_percentage()
        logger.debug(f"Gas actual: {current_gas_percent:.2f}%, objetivo: {self.gas_max_target}%")
        
        for fiat in self.fiat_assets:
            try:
                available_pairs = get_available_pairs(fiat)
                
                for pair in available_pairs:
                    base, quote = pair.split("/")
                    target_asset = quote if base == fiat else base
                    
                    if target_asset in active_assets:
                        continue
                    
                    # Verificar que el activo esté en la whitelist
                    if target_asset not in whitelist:
                        continue
                    
                    # Verificar que hay suficiente balance disponible para este activo
                    # Si el activo ya está en la wallet, verificar que tenga valor suficiente
                    asset_balance = balances.get('total', {}).get(target_asset, 0)
                    if asset_balance > 0:
                        asset_value_eur = self.vault.get_asset_value(target_asset, asset_balance, 'EUR')
                        
                        # Si es BNB, reservar 5% para gas antes de considerar el valor disponible
                        if target_asset == 'BNB':
                            gas_reserve_required = total_portfolio_eur * 0.05
                            available_bnb_value = max(0.0, asset_value_eur - gas_reserve_required)
                            # Para BNB, el valor disponible debe ser >= 10€ después de reservar el 5%
                            if available_bnb_value < MIN_ORDER_VALUE_EUR:
                                logger.debug(
                                    f"Omitiendo BNB: valor disponible insuficiente después de reservar gas "
                                    f"({available_bnb_value:.2f}€ < {MIN_ORDER_VALUE_EUR}€, valor total: {asset_value_eur:.2f}€, reserva: {gas_reserve_required:.2f}€)"
                                )
                                continue
                        else:
                            # Para otros activos, solo verificar el mínimo
                            if asset_value_eur < MIN_ORDER_VALUE_EUR:
                                logger.debug(f"Omitiendo {target_asset}: balance insuficiente ({asset_value_eur:.2f}€ < {MIN_ORDER_VALUE_EUR}€)")
                        continue
                    
                    signal_result = await self._evaluate_signal(pair)
                    
                    if signal_result:
                        pair_info = get_pair_info(pair)
                        if not pair_info:
                            continue
                        
                        rsi = signal_result.get('rsi')
                        ema200_distance = signal_result.get('ema200_distance')
                        volume_status = signal_result.get('volume_status')
                        triple_green = signal_result.get('triple_green', False)
                        
                        # Verificar Triple Verde explícitamente
                        rsi_compra = self.strategy["indicators"]["rsi_compra"]
                        ema_traditional = self.strategy["indicators"].get("ema200_traditional_threshold", -2.0)
                        ema_buy_dip = self.strategy["indicators"].get("ema200_buy_dip_threshold", 0.0)
                        
                        # Triple Verde: RSI < rsi_compra AND (EMA < traditional OR EMA > buy_dip) AND Volumen alto
                        is_triple_green = False
                        if rsi is not None and ema200_distance is not None and volume_status:
                            rsi_ok = rsi < rsi_compra
                            ema_ok = ema200_distance < ema_traditional or (ema200_distance > ema_buy_dip and rsi < rsi_compra)
                            volume_ok = volume_status == 'high' if isinstance(volume_status, str) else (volume_status is True)
                            is_triple_green = rsi_ok and ema_ok and volume_ok
                        
                        # Buy the Dip: RSI < rsi_compra AND EMA > buy_dip_threshold
                        buy_the_dip = False
                        if ema200_distance is not None and rsi is not None:
                            buy_the_dip = ema200_distance > ema_buy_dip and rsi < rsi_compra
                        
                        # Usar triple_green del signal_result si está disponible, sino usar el calculado
                        final_triple_green = triple_green if triple_green else is_triple_green
                        
                        if final_triple_green or buy_the_dip:
                            potential_profit = signal_result.get('profit_potential', 0)
                            
                            signal_type = "Buy the Dip" if buy_the_dip else "Triple Verde"
                            confidence = 1.0 if (final_triple_green and not buy_the_dip) else 0.75
                            
                            volume_status = signal_result.get('volume_status', 'N/A')
                            rsi_display = f"{rsi:.1f}" if rsi is not None else "N/A"
                            ema_display = f"{ema200_distance:.2f}%" if ema200_distance is not None else "N/A"
                            
                            logger.info(
                                f"[Slot {slot_id}] 🟢 EUR ➔ {target_asset} | "
                                f"Motivo: {signal_type} (RSI: {rsi_display}, EMA: {ema_display}, Vol: {volume_status}) | "
                                f"Confidence: {confidence*100:.0f}%"
                            )
                            
                            success = await self.execute_buy(
                                slot_id=slot_id,
                                pair=pair,
                                base_asset=fiat,
                                target_asset=target_asset,
                                is_fiat_entry=True,
                                confidence=confidence,
                                signal_data=signal_result
                            )
                            
                            if success:
                                logger.info(f"[Slot {slot_id}] Compra ejecutada exitosamente: {pair}")
                                return
                
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.error(f"Error al escanear entrada fiat {fiat} para slot {slot_id}: {e}")
                continue
    
    def _calculate_escalon_info(self, pnl_percent: float, entry_price: float, highest_price: float, 
                                stop_loss_price: float, current_price: float) -> Dict[str, Any]:
        """
        Calcula la información del escalón actual para visualización en el dashboard.
        
        Returns:
            Dict con información del escalón: level, label, stop_loss_percent_from_current
        """
        if pnl_percent <= 0.6:
            return {
                'level': 0,
                'label': 'Sin protección activa',
                'stop_loss_percent_from_current': 0
            }
        elif pnl_percent > 5.0:
            level = 6
            label = f'Trailing 1.0%'
        elif pnl_percent > 4.0:
            level = 5
            label = f'Trailing 0.9%'
        elif pnl_percent > 3.0:
            level = 4
            label = f'Trailing 0.8%'
        elif pnl_percent > 2.0:
            level = 3
            label = f'Trailing 0.7%'
        elif pnl_percent > 1.0:
            level = 2
            label = f'Trailing 0.5%'
        else:  # pnl_percent > 0.6
            level = 1
            label = 'Protección +0.1%'
        
        # Calcular porcentaje del stop loss respecto al precio actual
        if current_price > 0 and stop_loss_price > 0:
            stop_loss_percent_from_current = ((stop_loss_price - current_price) / current_price) * 100
        else:
            stop_loss_percent_from_current = 0
        
        return {
            'level': level,
            'label': label,
            'stop_loss_percent_from_current': stop_loss_percent_from_current
        }
    
    def _calculate_dynamic_stop_loss(self, entry_price: float, highest_price: float, initial_value: float, current_value_eur: float) -> float:
        """
        Calcula el stop loss dinámico con trailing stop del -0.50% respecto al máximo alcanzado.
        Estrategia Gemini: Trailing Stop Loss -0.50% desde el máximo visto
        
        Lógica:
        - Stop Loss fijo al -1.5% cuando PNL <= -1.5%
        - Trailing Stop -0.50% se activa cuando se alcanza +3.0% de ganancia
        - El trailing nunca baja, solo sube (principio de trinquete)
        
        Args:
            entry_price: Precio de entrada del trade
            highest_price: Precio más alto alcanzado
            initial_value: Valor inicial en EUR
            current_value_eur: Valor actual en EUR
        
        Returns:
            Precio de stop loss calculado
        """
        if initial_value <= 0:
            return entry_price * 0.985  # -1.5% por defecto si hay error
        
        pnl_percent = ((current_value_eur - initial_value) / initial_value) * 100
        
        # Obtener trailing stop loss percent de la estrategia
        trailing_stop_pct = self.strategy.get("trading", {}).get("trailing_stop_loss_percent", 0.50)
        
        # Stop Loss fijo al -1.5% cuando PNL <= -1.5%
        if pnl_percent <= -1.5:
            return entry_price * 0.985  # Stop Loss fijo al -1.5%
        
        # Trailing Stop -0.50% se activa al +3.0% de ganancia
        activation_threshold = self.strategy.get("trading", {}).get("trailing_activation", 3.0)
        if pnl_percent > activation_threshold:
            # Trailing Stop: -0.50% respecto al máximo visto
            # El stop loss nunca puede bajar (trinquete)
            stop_loss_price = highest_price * (1 - trailing_stop_pct / 100.0)
            return stop_loss_price
        else:
            # PNL entre -1.5% y +3.0%: Sin trailing stop, usar stop loss inicial al -1.5%
            return entry_price * 0.985  # Stop Loss fijo al -1.5%
    
    async def _check_market_general_trend(self) -> bool:
        """
        Verifica la tendencia general del mercado analizando las últimas 10 monedas del Radar.
        
        Returns:
            True si el mercado es positivo (< 70% de monedas con tendencia negativa), False en caso contrario
        """
        try:
            # Obtener datos del radar
            radar_list = []
            if self.radar_data_cache:
                for currency, data in self.radar_data_cache.items():
                    radar_list.append(data.copy())
                radar_list.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
            else:
                # Intentar leer desde archivo
                try:
                    if HAS_FILE_UTILS:
                        radar_data = read_json_safe(self.radar_path, {})
                    else:
                        if self.radar_path.exists():
                            with open(self.radar_path, 'r', encoding='utf-8') as f:
                                radar_data = json.load(f)
                        else:
                            radar_data = {}
                    
                    if radar_data and 'radar_data' in radar_data:
                        radar_list = radar_data.get('radar_data', [])
                except:
                    pass
            
            if not radar_list or len(radar_list) < 10:
                # Si no hay suficientes datos, permitir rotación (fallback seguro)
                logger.debug("Filtro de tendencia: No hay suficientes datos del radar, permitiendo rotación")
                return True
            
            # Tomar las primeras 10 monedas del radar (las mejores)
            top_currencies = radar_list[:10]
            negative_trend_count = 0
            total_checked = 0
            
            for currency_data in top_currencies:
                currency = currency_data.get('currency', '')
                # 🎯 Tratar EUR/USDC como activos normales (solo excluir BNB para gas)
                if currency == 'BNB':
                    continue
                # EUR y USDC ahora se tratan como activos normales
                
                # Buscar par disponible para obtener precio
                pair = None
                for fiat in self.fiat_assets:
                    candidate_pair = f"{currency}/{fiat}"
                    pair_info = get_pair_info(candidate_pair)
                    if pair_info:
                        pair = candidate_pair
                        # Obtener cambio porcentual de la última hora (si está disponible)
                        # Intentar obtener desde exchange si está disponible
                        try:
                            if self.exchange:
                                ticker = self.exchange.fetch_ticker(pair)
                                # Usar percentage del ticker si está disponible (cambio 24h como aproximación)
                                # O calcular cambio porcentual aproximado
                                percentage = ticker.get('percentage', 0)
                                if percentage < 0:
                                    negative_trend_count += 1
                                total_checked += 1
                        except:
                            # Si no se puede obtener, usar cambio porcentual del pair_info si está disponible
                            change_24h = pair_info.get('change_24h', 0)
                            if change_24h < 0:
                                negative_trend_count += 1
                            total_checked += 1
                        break
            
            if total_checked == 0:
                logger.debug("Filtro de tendencia: No se pudo verificar tendencia, permitiendo rotación")
                return True
            
            negative_percentage = (negative_trend_count / total_checked) * 100
            
            # Si más del 70% tiene tendencia negativa, bloquear rotación
            if negative_percentage > 70:
                logger.info(
                    f"🚫 Filtro anti-falsas alarmas: {negative_percentage:.1f}% de las top monedas tienen tendencia negativa. "
                    f"Rotación bloqueada para evitar caídas generales del mercado."
                )
                return False
            
            logger.debug(f"✅ Filtro de tendencia: {negative_percentage:.1f}% negativo (< 70%). Rotación permitida.")
            return True
            
        except Exception as e:
            logger.error(f"Error al verificar tendencia general del mercado: {e}")
            # En caso de error, permitir rotación (fallback seguro)
            return True
    
    async def _get_current_asset_heat_score(self, target_asset: str) -> int:
        """
        Obtiene el heat_score actual del activo en el trade.
        
        Returns:
            heat_score del activo actual, 0 si no se puede calcular
        """
        try:
            # Buscar par del activo actual
            pair = None
            for fiat in self.fiat_assets:
                candidate_pair = f"{target_asset}/{fiat}"
                if get_pair_info(candidate_pair):
                    pair = candidate_pair
                    break
            
            if not pair:
                return 0
            
            # Evaluar señal del activo actual
            signal_result = await self._evaluate_signal(pair)
            if signal_result:
                heat_score = await self._calculate_heat_score(signal_result)
                return heat_score
            
            return 0
            
        except Exception as e:
            logger.debug(f"Error obteniendo heat_score del activo actual {target_asset}: {e}")
            return 0
    
    async def _attempt_asset_rotation(self, slot_id: int, trade_id: int, current_trade: Dict[str, Any]) -> bool:
        """
        Intenta rotar de un activo a otro mejor del Radar con filtros anti-falsas alarmas.
        
        Filtros aplicados:
        1. Regla de Mercado General: Verifica que < 70% de las top monedas tengan tendencia negativa
        2. Regla de Ganancia Mínima: Solo rota si la nueva moneda tiene heat_score al menos 10 puntos superior
        
        Returns:
            True si la rotación fue exitosa, False en caso contrario
        """
        try:
            current_asset = current_trade.get('target_asset', '')
            
            # FILTRO 1: Verificar tendencia general del mercado
            market_positive = await self._check_market_general_trend()
            if not market_positive:
                logger.info(
                    f"[Slot {slot_id}] 🚫 Rotación bloqueada: Mercado general negativo detectado. "
                    f"Manteniendo posición en {current_asset}"
                )
                return False
            
            # FILTRO 2: Obtener heat_score del activo actual
            current_heat_score = await self._get_current_asset_heat_score(current_asset)
            min_required_heat_score = max(90, current_heat_score + 10)  # Al menos 10 puntos superior o 90 mínimo
            
            logger.debug(
                f"[Slot {slot_id}] Rotación: heat_score actual de {current_asset}: {current_heat_score}, "
                f"mínimo requerido para rotación: {min_required_heat_score}"
            )
            
            # Buscar oportunidad en radar con heat_score superior
            rotation_found = await self._assign_from_radar(slot_id, min_heat_score=min_required_heat_score)
            
            if rotation_found:
                # Si se encontró una oportunidad mejor, vender el activo actual
                logger.info(
                    f"[Slot {slot_id}] 🔄 Rotación activada: Vendiendo {current_asset} (heat_score: {current_heat_score}) "
                    f"para abrir posición en activo del Radar (heat_score >= {min_required_heat_score})"
                )
                success = await self.execute_sell(slot_id, trade_id, current_trade)
                return success
            else:
                logger.debug(
                    f"[Slot {slot_id}] No se encontró oportunidad mejor en el Radar "
                    f"(mínimo requerido: {min_required_heat_score}, actual: {current_heat_score})"
                )
            
            return False
            
        except Exception as e:
            logger.error(f"Error al intentar rotación de activo en slot {slot_id}: {e}")
            return False
    
    async def _evaluate_slot_optimized(self, slot_id: int, active_trade: Dict[str, Any]):
        """
        ⚡ EVALUACIÓN OPTIMIZADA: Evalúa un slot con trailing stop escalonado y rotación activa.
        Esta función se ejecuta en cada tick de vigilancia (5s) para máxima velocidad.
        """
        trade_id = active_trade['id']
        target_asset = active_trade['target_asset']
        entry_price = active_trade.get('entry_price', 0)
        initial_value = active_trade.get('initial_fiat_value', 0)
        
        # ⚠️ VALIDACIÓN: Si el trade tiene valor menor a 10€, cerrarlo (mínimo de Binance)
        MIN_ORDER_VALUE_EUR = 10.0
        trade_value_eur = self.vault.get_asset_value(
            target_asset,
            active_trade['amount'],
            'EUR'
        )
        if trade_value_eur < MIN_ORDER_VALUE_EUR:
            logger.warning(
                f"Cerrando trade en slot {slot_id}: Valor ({trade_value_eur:.2f}€) menor al mínimo de Binance ({MIN_ORDER_VALUE_EUR}€). "
                f"Par: {active_trade.get('symbol', 'N/A')}"
            )
            success = await self.execute_sell(slot_id, trade_id, active_trade)
            if not success:
                logger.warning(f"Venta falló para slot {slot_id}, desactivando trade directamente")
                self.db.deactivate_trade(trade_id)
            return
        
        # Calcular PNL actual
        if initial_value > 0:
            pnl_percent = ((trade_value_eur - initial_value) / initial_value) * 100
        else:
            pnl_percent = 0
        
        current_price = trade_value_eur / active_trade['amount'] if active_trade['amount'] > 0 else 0
        
        # Actualizar highest_price_seen si el precio subió
        highest_price = active_trade.get('highest_price', entry_price)
        previous_highest = highest_price
        if current_price > highest_price:
            self.db.update_highest_price(trade_id, current_price)
            highest_price = current_price
            logger.debug(f"[Slot {slot_id}] Nuevo máximo alcanzado: {current_price:.4f} (anterior: {previous_highest:.4f})")
        
        # 1. GESTIÓN DE PÉRDIDAS Y ROTACIÓN
        if -1.5 <= pnl_percent < -0.5:
            # PNL entre -0.5% y -1.5%: Intentar rotación activa
            logger.info(
                f"[Slot {slot_id}] 📊 Rotación activa: PNL {pnl_percent:.2f}% en zona de rotación. "
                f"Buscando oportunidad mejor en Radar..."
            )
            
            # Buscar oportunidad en radar con heat_score > 90
            rotation_success = await self._attempt_asset_rotation(slot_id, trade_id, active_trade)
            if rotation_success:
                logger.info(f"[Slot {slot_id}] ✅ Rotación exitosa: {target_asset} ➔ Nuevo activo")
                return  # Rotación completada, salir
        elif pnl_percent < -1.5:
            # PNL < -1.5%: Hard Stop Loss - Venta inmediata
            logger.warning(
                f"[Slot {slot_id}] 🛑 HARD STOP LOSS: PNL {pnl_percent:.2f}% < -1.5%. Venta inmediata."
            )
            await self.execute_sell(slot_id, trade_id, active_trade)
            return
        
        # 2. TRAILING STOP ESCALONADO (solo si PNL > 0.6%)
        if pnl_percent > 0.6:
            # Calcular stop loss dinámico
            calculated_stop_loss = self._calculate_dynamic_stop_loss(
                entry_price, highest_price, initial_value, trade_value_eur
            )
            
            # Obtener stop loss actual de la BD (necesitamos recargar el trade)
            updated_trade = self.db.get_active_trade(slot_id)
            current_stop_loss = updated_trade.get('stop_loss') if updated_trade else None
            if current_stop_loss is None:
                current_stop_loss = entry_price * 0.999  # Default inicial
            
            # PRINCIPIO DE TRINQUETE: El stop loss solo puede subir, nunca bajar
            if calculated_stop_loss > current_stop_loss:
                # Actualizar stop loss en la BD
                try:
                    cursor = self.db.conn.cursor()
                    cursor.execute(
                        "UPDATE trades SET stop_loss = ? WHERE id = ?",
                        (calculated_stop_loss, trade_id)
                    )
                    self.db.conn.commit()
                except Exception as e:
                    logger.error(f"Error al actualizar stop_loss para trade {trade_id}: {e}")
                
                # Detectar cambio de escalón para logging
                pnl_thresholds = [0.6, 1.0, 2.0, 3.0, 4.0, 5.0]
                current_escalon = None
                for threshold in reversed(pnl_thresholds):
                    if pnl_percent > threshold:
                        current_escalon = threshold
                        break
                
                # Calcular escalón anterior basado en el stop loss previo
                if current_stop_loss > entry_price * 1.001:
                    prev_stop_diff_percent = ((current_stop_loss - entry_price) / entry_price) * 100
                    prev_escalon = None
                    if prev_stop_diff_percent > 0.5:
                        for threshold in [5.0, 4.0, 3.0, 2.0, 1.0]:
                            if prev_stop_diff_percent >= threshold * 0.8:
                                prev_escalon = threshold
                                break
                else:
                    prev_escalon = None
                
                # Logging: Detectar si subimos de escalón
                if prev_escalon is None or (current_escalon is not None and current_escalon > prev_escalon):
                    if current_escalon is not None:
                        logger.info(
                            f"[Slot {slot_id}] 📈 Escalón de {current_escalon:.1f}% alcanzado. "
                            f"Nuevo Stop Loss ajustado: {calculated_stop_loss:.4f} "
                            f"({((calculated_stop_loss - entry_price) / entry_price * 100):+.2f}% desde entrada)"
                        )
                else:
                    logger.debug(
                        f"[Slot {slot_id}] Stop Loss actualizado: {calculated_stop_loss:.4f} "
                        f"(anterior: {current_stop_loss:.4f})"
                    )
                
                current_stop_loss = calculated_stop_loss
            
            # Verificar si el precio actual tocó el stop loss
            if current_price <= current_stop_loss:
                logger.info(
                    f"[Slot {slot_id}] 🏁 Trailing Stop activado: Precio {current_price:.4f} <= Stop Loss {current_stop_loss:.4f}. "
                    f"PNL final: {pnl_percent:.2f}%"
                )
                await self.execute_sell(slot_id, trade_id, active_trade)
                return
        
        # 3. ESCANEAR OPORTUNIDADES DE SALTO (solo si no hay problemas)
        await self._scan_jump_opportunity(slot_id, active_trade)
    
    async def _evaluate_slot(self, slot_id: int, active_trade: Dict[str, Any]):
        """
        DEPRECATED: Usar _evaluate_slot_optimized() en su lugar.
        Mantenido para compatibilidad con código legacy.
        """
        await self._evaluate_slot_optimized(slot_id, active_trade)
    
    async def _check_trailing_stop(self, trade_id: int, trade: Dict[str, Any]) -> bool:
        """Verifica si se debe activar el trailing stop o Safe Exit."""
        try:
            current_value_eur = self.vault.get_asset_value(
                trade['target_asset'],
                trade['amount'],
                'EUR'
            )
            
            initial_value = trade['initial_fiat_value']
            highest_price = trade.get('highest_price', trade['entry_price'])
            
            if initial_value > 0:
                profit_percent = ((current_value_eur - initial_value) / initial_value) * 100
            else:
                profit_percent = 0
            
            current_price = current_value_eur / trade['amount'] if trade['amount'] > 0 else 0
            if current_price > highest_price:
                self.db.update_highest_price(trade_id, current_price)
                highest_price = current_price
            
            # Safe Exit: Si el profit alcanza >= 1.5%, activar stop loss virtual en +0.5%
            # Si luego cae por debajo de 0.5%, vender para proteger ganancias
            safe_exit_threshold = self.strategy["trading"].get("safe_exit_threshold", 1.5)
            safe_exit_stop_loss = self.strategy["trading"].get("safe_exit_stop_loss", 0.5)
            
            # Calcular el profit máximo histórico desde el highest_price
            # Si alguna vez alcanzamos >= safe_exit_threshold, activamos el stop loss
            max_profit_from_highest = ((highest_price * trade['amount'] - initial_value) / initial_value * 100) if initial_value > 0 else 0
            
            # Si el profit máximo alcanzó el threshold Y ahora está por debajo del stop loss
            if max_profit_from_highest >= safe_exit_threshold and profit_percent < safe_exit_stop_loss:
                profit_eur = current_value_eur - initial_value
                slot_id = trade.get('slot_id', '?')
                target_asset = trade['target_asset']
                
                profit_sign = "+" if profit_percent >= 0 else ""
                write_bitacora(
                    f"[💰 VENTA_SLOT] Slot {slot_id + 1}: {target_asset} | Resultado: {profit_sign}{profit_percent:.2f}%"
                )
                
                logger.info(
                    f"[Slot {slot_id}] 🏁 {target_asset} ➔ EUR | "
                    f"Resultado: {profit_percent:+.2f}% ({profit_eur:+,.2f}€) | "
                    f"Motivo: Safe Exit (Alcanzó {max_profit_from_highest:.2f}%, cayó a {profit_percent:.2f}%)"
                )
                return True
            
            # Trailing Stop
            # ⚡ VOLATILIDAD DINÁMICA: Ajustar trailing stop para monedas volátiles
            base_trailing_activation = self.strategy["trading"]["trailing_activation"]
            base_trailing_drop = self.strategy["trading"]["trailing_drop"]
            
            # Verificar si el activo es volátil (SUI, APT, FET, RNDR)
            volatile_config = self.strategy.get("volatile_assets", {})
            target_asset = trade.get('target_asset', '')
            adjustment = volatile_config.get(target_asset, {}).get("trailing_stop_adjustment", 0.0)
            
            trailing_activation = base_trailing_activation
            trailing_drop = base_trailing_drop + adjustment  # Añadir 0.5% más para monedas volátiles
            
            if adjustment > 0:
                logger.debug(
                    f"⚡ Volatilidad dinámica aplicada para {target_asset}: "
                    f"trailing_drop ajustado de {base_trailing_drop}% a {trailing_drop}%"
                )
            
            # 🎯 TRAILING STOP CORREGIDO: Usar lógica de beneficio asegurado
            # Calcular PNL máximo alcanzado desde highest_price
            max_pnl_reached = ((highest_price * trade['amount'] - initial_value) / initial_value * 100) if initial_value > 0 else 0
            
            # Si el trailing está activado (max_pnl >= 0.6%)
            if max_pnl_reached >= trailing_activation:
                # Calcular valor protegido: max_pnl - 0.5%
                trailing_stop_value = max_pnl_reached - trailing_drop
                
                # Asegurar que el trailing_stop_value nunca sea negativo
                if trailing_stop_value < 0:
                    trailing_stop_value = 0.0
                
                # 🚨 CONDICIÓN CRÍTICA: Si PNL actual <= valor protegido, VENDER INMEDIATAMENTE
                if profit_percent <= trailing_stop_value:
                    profit_eur = current_value_eur - initial_value
                    slot_id = trade.get('slot_id', '?')
                    target_asset = trade['target_asset']
                    
                    # 📊 LOG DE AUDITORÍA: Trailing Stop roto
                    logger.warning(
                        f"[🔴 TRAILING STOP ROTO] Slot {slot_id} | {target_asset} | "
                        f"PNL Actual: {profit_percent:.2f}% <= Valor Protegido: {trailing_stop_value:.2f}% | "
                        f"Max PNL Alcanzado: {max_pnl_reached:.2f}% | "
                        f"Ejecutando VENTA INMEDIATA sin bloqueos"
                    )
                    
                    profit_sign = "+" if profit_percent >= 0 else ""
                    write_bitacora(
                        f"[💰 VENTA_SLOT] Slot {slot_id + 1}: {target_asset} | Resultado: {profit_sign}{profit_percent:.2f}% | "
                        f"Trailing Stop: {max_pnl_reached:.2f}% → {trailing_stop_value:.2f}% → {profit_percent:.2f}%"
                    )
                    
                    logger.info(
                        f"[Slot {slot_id}] 🏁 {target_asset} ➔ EUR | "
                        f"Resultado: {profit_percent:+.2f}% ({profit_eur:+,.2f}€) | "
                        f"Motivo: Trailing Stop (Max PNL: {max_pnl_reached:.2f}%, Protegido: {trailing_stop_value:.2f}%, Actual: {profit_percent:.2f}%)"
                    )
                    # ⚡ VENTA INMEDIATA: Sin bloqueos de tiempo mínimo o confirmación
                    return True
            
            return False
        
        except Exception as e:
            logger.error(f"Error al verificar trailing stop para trade {trade_id}: {e}")
            return False
    
    async def _calculate_heat_score(self, signal_result: Dict[str, Any]) -> int:
        """Calcula el heat_score de una señal."""
        if not signal_result:
            return 0
        
        # Componentes y pesos
        WEIGHTS = {
            'rsi': 0.55,   # Dar más peso al momentum inmediato (RSI)
            'ema': 0.25,
            'vol': 0.15,
            'bonus': 0.05
        }

        # Offset para evitar que todos los activos se queden anclados en valores bajos
        BASE_SCORE = 5.0

        # Valores raw
        rsi = signal_result.get('rsi')
        ema_dist = signal_result.get('ema200_distance')
        volume_status = signal_result.get('volume_status')
        currency = signal_result.get('currency') or signal_result.get('pair')

        # 1) RSI: máximo si RSI entre 45-65
        rsi_score = 0.0
        rsi_boost = 0.0
        if rsi is not None:
            distance = abs(rsi - 50.0)

            if 45.0 <= rsi <= 65.0:
                rsi_score = 100.0
            else:
                # Penalizar de forma más agresiva conforme se aleja del punto dulce
                rsi_score = max(0.0, 100.0 - distance * 3.0)

            # Boost extra cerca del neutro para romper empates de heat planos
            rsi_boost = max(0.0, 20.0 - distance * 1.5)

        # 2) EMA distance: máximo si por encima de EMA y < 2%
        ema_score = 0.0
        if ema_dist is not None:
            try:
                # Si precio está por encima (positivo) y dentro de 2%
                if ema_dist > 0 and ema_dist <= 2.0:
                    ema_score = 100.0
                elif ema_dist > 2.0:
                    # Penalizar cuanto más alejado por encima (0 en 10%)
                    ema_score = max(0.0, 100.0 - ((ema_dist - 2.0) / 8.0) * 100.0)
                else:
                    # Por debajo de EMA: penalizar según distancia (0 en -5%)
                    ema_score = max(0.0, 100.0 - (abs(ema_dist) / 5.0) * 100.0)
            except Exception:
                ema_score = 0.0

        # 3) Volumen: según incremento relativo / etiquetas
        vol_score = 0.0
        if volume_status is True or (isinstance(volume_status, str) and volume_status.lower() == 'high'):
            vol_score = 100.0
        elif isinstance(volume_status, str) and volume_status.lower() in ('normal', 'medium'):
            vol_score = 50.0
        else:
            vol_score = 0.0

        # 4) Bonus por estar en RESERVE_ASSETS
        bonus_score = 0.0
        try:
            if currency and isinstance(currency, str):
                # currency puede ser 'BTC' o 'BTC/EUR' dependiendo del origen
                short_curr = currency.split('/')[0]
                if short_curr in self.RESERVE_ASSETS:
                    bonus_score = 100.0
        except Exception:
            bonus_score = 0.0

        # Contribuciones (puntos reales sobre 100)
        contrib_rsi = rsi_score * WEIGHTS['rsi']
        contrib_ema = ema_score * WEIGHTS['ema']
        contrib_vol = vol_score * WEIGHTS['vol']
        contrib_bonus = bonus_score * WEIGHTS['bonus']

        raw_total = BASE_SCORE + contrib_rsi + contrib_ema + contrib_vol + contrib_bonus + rsi_boost
        total = min(max(raw_total, 0.0), 100.0)

        # Guardar desglose en el resultado para que el radar lo exponga
        try:
            signal_result['heat_components'] = {
                'rsi_raw': round(rsi_score, 2),
                'ema_raw': round(ema_score, 2),
                'vol_raw': round(vol_score, 2),
                'bonus_raw': round(bonus_score, 2),
                'rsi': round(contrib_rsi),
                'ema': round(contrib_ema),
                'vol': round(contrib_vol),
                'bonus': round(contrib_bonus),
                'rsi_boost': round(rsi_boost, 2),
                'base': BASE_SCORE,
                'total': int(round(total))
            }
        except Exception:
            pass

        return int(round(total))
    
    async def _scan_jump_opportunity(self, slot_id: int, active_trade: Dict[str, Any]):
        """Escanea oportunidades de salto desde el activo actual."""
        current_asset = active_trade['target_asset']
        trade_id = active_trade['id']
        
        active_assets = self._get_active_assets()
        
        try:
            available_pairs = get_available_pairs(current_asset)
            
            current_profit = await self._calculate_current_profit(trade_id, active_trade)
            
            current_pair = None
            for pair in available_pairs:
                if current_asset in pair:
                    current_pair = pair
                    break
            
            current_heat_score = 0
            if current_pair:
                current_signal = await self._evaluate_signal(current_pair)
                current_heat_score = await self._calculate_heat_score(current_signal) if current_signal else 0
            
            best_pair = None
            best_profit = current_profit
            best_signal = None
            best_heat_score = current_heat_score
            
            # ⚠️ UMBRAL DE SALTO - PARÁMETRO CRÍTICO PARA EVITAR OVERTRADING
            # Si este valor es muy bajo (ej: 15), el bot saltará frecuentemente entre monedas
            # Esto puede generar muchas comisiones y pérdidas por overtrading
            # Recomendación: Si ves muchos saltos, aumentar a 25-30
            jump_heat_diff = self.strategy["trading"].get("jump_heat_score_difference", 15)
            min_profit_step = self.strategy["trading"]["min_profit_step"]
            
            logger.debug(
                f"[Slot {slot_id}] Umbral de salto: {jump_heat_diff} puntos "
                f"(Heat score actual: {current_heat_score})"
            )
            
            for pair in available_pairs:
                base, quote = pair.split("/")
                target_asset = quote if base == current_asset else base
                
                if target_asset in active_assets:
                    continue
                
                signal_result = await self._evaluate_signal(pair)
                
                if signal_result:
                    dest_heat_score = await self._calculate_heat_score(signal_result)
                    
                    # Solo saltar si el heat score destino es suficientemente superior
                    # Esto previene overtrading (saltos excesivos que generan comisiones)
                    if dest_heat_score < current_heat_score + jump_heat_diff:
                        logger.debug(
                            f"Salto rechazado: {target_asset} heat_score ({dest_heat_score}) "
                            f"no es suficientemente superior al actual ({current_heat_score}). "
                            f"Necesario: +{jump_heat_diff} puntos (umbral actual: {jump_heat_diff})"
                        )
                        continue
                    
                    potential_profit = signal_result.get('profit_potential', 0)
                    
                    if potential_profit > best_profit:
                        best_pair = pair
                        best_profit = potential_profit
                        best_signal = signal_result
                        best_heat_score = dest_heat_score
            
            if best_pair and best_profit > current_profit + min_profit_step:
                mejora_score = best_heat_score - current_heat_score
                base, quote = best_pair.split("/")
                new_target = quote if base == current_asset else base
                
                logger.info(
                    f"[Slot {slot_id}] 🔄 {current_asset} ➔ {new_target} | "
                    f"Motivo: Salto por mejor señal (Mejora Score: +{mejora_score:.0f}) | "
                    f"Beneficio potencial: {best_profit:.2f}% vs actual: {current_profit:.2f}% | "
                    f"Umbral salto: {jump_heat_diff} puntos"
                )
                
                # Advertencia si el umbral es muy bajo (riesgo de overtrading)
                if jump_heat_diff < 20:
                    logger.warning(
                        f"⚠️ ADVERTENCIA: Umbral de salto bajo ({jump_heat_diff}). "
                        f"Si ves muchos saltos, considera aumentar 'jump_heat_score_difference' "
                        f"a 25-30 en strategy.json para evitar overtrading."
                    )
                
                await self.execute_swap(
                    slot_id=slot_id,
                    trade_id=trade_id,
                    current_trade=active_trade,
                    new_pair=best_pair,
                    new_target_asset=new_target
                )
        
        except Exception as e:
            logger.error(f"Error al escanear salto en slot {slot_id}: {e}")
    
    async def _calculate_current_profit(self, trade_id: int, trade: Dict[str, Any]) -> float:
        """Calcula el beneficio actual de un trade en porcentaje."""
        try:
            current_value = self.vault.get_asset_value(
                trade['target_asset'],
                trade['amount'],
                'EUR'
            )
            initial_value = trade['initial_fiat_value']
            
            if initial_value > 0:
                return ((current_value - initial_value) / initial_value) * 100
            return 0.0
        except Exception as e:
            logger.error(f"Error al calcular beneficio actual: {e}")
            return 0.0
    
    async def _evaluate_signal(self, pair: str) -> Optional[Dict[str, Any]]:
        """Evalúa la señal de Triple Confluencia para un par."""
        if not HAS_SIGNALS:
            pair_info = get_pair_info(pair)
            if pair_info and pair_info.get('price_change_percent', 0) > 0:
                return {
                    'triple_green': True,
                    'profit_potential': abs(pair_info.get('price_change_percent', 0))
                }
            return None
        
        try:
            # Incluir información de par/moneda para que _calculate_heat_score pueda usarla
            base_currency = pair.split('/')[0] if '/' in pair else pair

            if hasattr(signals, 'evaluate_triple_confluence'):
                result = signals.evaluate_triple_confluence(pair, self.exchange)
                if result and isinstance(result, dict):
                    result.setdefault('pair', pair)
                    result.setdefault('currency', base_currency)
                    return result
            elif hasattr(signals, 'evaluate_signal'):
                result = signals.evaluate_signal(pair, self.exchange)
                if result and isinstance(result, dict):
                    result.setdefault('pair', pair)
                    result.setdefault('currency', base_currency)
                    return result
            elif hasattr(signals, 'get_technical_indicators'):
                indicators = signals.get_technical_indicators(pair, self.exchange)
                rsi = indicators.get('rsi')
                ema200_distance = indicators.get('ema200_distance')
                volume_status = indicators.get('volume_status')
                
                rsi_compra = self.strategy["indicators"]["rsi_compra"]
                ema_traditional = self.strategy["indicators"].get("ema200_traditional_threshold", -2.0)
                ema_buy_dip = self.strategy["indicators"].get("ema200_buy_dip_threshold", 0.0)
                
                triple_green = False
                if rsi is not None and ema200_distance is not None and volume_status:
                    rsi_ok = rsi < rsi_compra
                    ema_ok = ema200_distance < ema_traditional or (ema200_distance > ema_buy_dip and rsi < rsi_compra)
                    volume_ok = volume_status == 'high' if isinstance(volume_status, str) else volume_status
                    triple_green = rsi_ok and ema_ok and volume_ok
                
                return {
                    'pair': pair,
                    'currency': base_currency,
                    'rsi': rsi,
                    'ema200_distance': ema200_distance,
                    'volume_status': volume_status,
                    'triple_green': triple_green,
                    'profit_potential': abs(indicators.get('profit_potential', 0))
                }
        except Exception as e:
            logger.error(f"Error al evaluar señal para {pair}: {e}")
        
        return {
            'pair': None,
            'currency': None,
            'signal': 'neutral',
            'rsi': None,
            'ema200': None,
            'volume': None,
            'profit_potential': 0.0,
            'heat_score': 0
        }
    
    async def execute_buy(self, slot_id: int, pair: str, base_asset: str,
                         target_asset: str, is_fiat_entry: bool = False, confidence: float = 1.0,
                         signal_data: Optional[Dict[str, Any]] = None) -> bool:
        """Ejecuta una orden de compra."""
        try:
            # Constante: mínimo de 10€ para operar en Binance
            MIN_ORDER_VALUE_EUR = 10.0
            
            balance = self.exchange.fetch_balance()
            base_balance = balance.get(base_asset, {}).get('free', 0)
            
            if base_asset in self.fiat_assets:
                treasury_total = self.db.get_total_treasury()
                treasury_eur = treasury_total.get('total_eur', 0.0)
                if base_asset == 'EUR':
                    base_balance = max(0.0, base_balance - treasury_eur)
                else:
                    usdc_eur_rate = self.vault.get_asset_value('USDC', 1.0, 'EUR')
                    if usdc_eur_rate > 0:
                        treasury_usdc = treasury_eur / usdc_eur_rate
                        base_balance = max(0.0, base_balance - treasury_usdc)
            
            if base_balance <= 0:
                logger.warning(f"Balance insuficiente de {base_asset} para slot {slot_id}")
                return False
            
            # Calcular el valor total del portfolio y monto por slot
            total_portfolio_eur = self.vault.calculate_total_portfolio_value()
            if total_portfolio_eur <= 0:
                # Si calculate_total_portfolio_value retorna 0, calcular manualmente
                total_portfolio_eur = 0.0
                for asset, balance_data in balance.get('total', {}).items():
                    if balance_data > 0:
                        asset_value = self.vault.get_asset_value(asset, balance_data, 'EUR')
                        total_portfolio_eur += asset_value
            
            # Reservar 5% para gas (BNB)
            gas_reserve_eur = total_portfolio_eur * 0.05
            available_for_trading = max(0.0, total_portfolio_eur - gas_reserve_eur)
            
            # Si el target_asset es BNB, reservar 5% para gas antes de calcular el capital a usar
            if target_asset == 'BNB':
                # Calcular cuánto BNB necesitamos para el 5% del portfolio
                bnb_price_eur = self.vault.get_asset_value('BNB', 1.0, 'EUR')
                if bnb_price_eur > 0:
                    gas_reserve_bnb = gas_reserve_eur / bnb_price_eur
                    # Reducir el balance disponible de BNB por la reserva de gas
                    bnb_total_balance = balance.get('BNB', {}).get('total', 0)
                    base_balance = max(0.0, bnb_total_balance - gas_reserve_bnb)
                    logger.debug(
                        f"Operación con BNB: reservando {gas_reserve_bnb:.8f} BNB ({gas_reserve_eur:.2f}€) para gas. "
                        f"Balance disponible: {base_balance:.8f} BNB"
                    )
            
            # Calcular monto por slot: (total - gas_reserve) / max_slots
            max_slots = self.strategy["trading"]["max_slots"]
            monto_por_slot_eur = available_for_trading / max_slots if max_slots > 0 else 0.0
            
            # Convertir monto por slot a la moneda base
            if base_asset == 'EUR':
                monto_por_slot_base = monto_por_slot_eur
            elif base_asset == 'USDC':
                # USDC ≈ EUR (1:1)
                monto_por_slot_base = monto_por_slot_eur
            else:
                # Para otras monedas, convertir a la moneda base
                base_price_eur = self.vault.get_asset_value(base_asset, 1.0, 'EUR')
                monto_por_slot_base = monto_por_slot_eur / base_price_eur if base_price_eur > 0 else 0
            
            # Usar el mínimo entre el balance disponible y el monto por slot
            capital_to_use = min(base_balance, monto_por_slot_base) * confidence
            
            logger.debug(
                f"Monto por slot: {monto_por_slot_eur:.2f}€ ({monto_por_slot_base:.2f} {base_asset}), "
                f"Balance disponible: {base_balance:.2f} {base_asset}, "
                f"Capital a usar: {capital_to_use:.2f} {base_asset}"
            )
            emergency_reserve = base_balance * (1.0 - confidence)
            
            if confidence < 1.0:
                logger.info(
                    f"Modo Conservador activado: Usando {confidence*100:.0f}% del capital "
                    f"({capital_to_use:.2f} {base_asset}), reservando {emergency_reserve:.2f} {base_asset}"
                )
            
            ticker = self.exchange.fetch_ticker(pair)
            price = ticker['last']
            
            # Calcular valor de la operación en EUR
            if base_asset == 'EUR':
                order_value_eur = capital_to_use
            elif base_asset == 'USDC':
                # USDC ≈ EUR (1:1 aproximadamente)
                order_value_eur = capital_to_use
            else:
                # Para otras monedas, convertir a EUR
                base_price_eur = self.vault.get_asset_value(base_asset, 1.0, 'EUR')
                order_value_eur = capital_to_use * base_price_eur if base_price_eur > 0 else 0
            
            # ⚠️ VALIDAR MÍNIMO DE BINANCE: 10€
            if order_value_eur < MIN_ORDER_VALUE_EUR:
                logger.warning(
                    f"Operación rechazada: Valor ({order_value_eur:.2f}€) menor al mínimo de Binance ({MIN_ORDER_VALUE_EUR}€). "
                    f"Par: {pair}, Base disponible: {base_balance:.2f} {base_asset}"
                )
                return False
            
            amount = capital_to_use / price
            amount = self.exchange.amount_to_precision(pair, amount)
            
            logger.info(f"Ejecutando compra: {pair}, cantidad: {amount}, precio: {price}")
            order = self.exchange.create_market_buy_order(pair, amount)
            
            executed_price = order.get('price', price)
            executed_amount = order.get('filled', amount)
            
            if is_fiat_entry:
                initial_fiat_value = self.vault.get_asset_value(
                    target_asset, executed_amount, 'EUR'
                )
            else:
                initial_fiat_value = 0
            
            path_history = f"{base_asset} > {target_asset}" if is_fiat_entry else ""
            
            trade_id = self.db.create_trade(
                slot_id=slot_id,
                symbol=pair,
                base_asset=base_asset,
                target_asset=target_asset,
                amount=executed_amount,
                entry_price=executed_price,
                initial_fiat_value=initial_fiat_value,
                path_history=path_history
            )
            
            if is_fiat_entry and signal_data:
                rsi = signal_data.get('rsi')
                ema200_distance = signal_data.get('ema200_distance')
                volume_status = signal_data.get('volume_status', 'N/A')
                rsi_display = f"{rsi:.1f}" if rsi is not None else "N/A"
                ema_display = f"{ema200_distance:.2f}%" if ema200_distance is not None else "N/A"
                heat_score = signal_data.get('heat_score', 'N/A') if signal_data else 'N/A'
                write_bitacora(
                    f"[🛒 COMPRA_SLOT] Slot {slot_id + 1}: {target_asset} | "
                    f"RSI: {rsi_display} | EMA: {ema_display} | Vol: {volume_status} | Heat: {heat_score}"
                )
            
            logger.info(f"Compra ejecutada exitosamente. Trade ID: {trade_id}")
            
            # ⛽ GESTIÓN DE GAS POR INERCIA: Si se compra BNB por oportunidad, rellenar hasta 3.5%
            if target_asset == 'BNB':
                current_gas_percent = self._get_gas_percentage()
                if current_gas_percent < 3.5:
                    # Retener BNB adicional para alcanzar 3.5%
                    bnb_retained = await self._refill_gas_passive(executed_amount, 3.5)
                    if bnb_retained > 0:
                        # Ajustar la cantidad del trade
                        executed_amount = executed_amount - bnb_retained
                        # Actualizar el trade con la cantidad ajustada
                        self.db.update_trade(trade_id, amount=executed_amount)
                        logger.info(f"⛽ Gas activo: Retenidos {bnb_retained:.4f} BNB para alcanzar 3.5%")
            
            return True
        
        except Exception as e:
            logger.error(f"Error al ejecutar compra en slot {slot_id}: {e}")
            return False
    
    async def _calculate_route_value(self, route_type: str, target_asset: str, amount: float, 
                                     pair: Optional[str] = None, intermediate: Optional[str] = None) -> float:
        """
        Calcula el valor esperado en EUR después de ejecutar una ruta de venta.
        
        Args:
            route_type: 'direct' o 'intermediate'
            target_asset: Activo a vender
            amount: Cantidad del activo
            pair: Par de trading (para ruta directa o primer par de ruta intermedia)
            intermediate: Moneda intermedia (solo para ruta intermedia)
        
        Returns:
            Valor esperado en EUR después de comisiones y spreads
        """
        try:
            if route_type == 'direct' and pair:
                # Ruta directa: ALT/EUR
                pair_info = get_pair_info(pair)
                if not pair_info:
                    return 0.0
                
                ticker = self.exchange.fetch_ticker(pair)
                if not ticker:
                    return 0.0
                
                # Usar precio bid (precio de venta) para calcular valor recibido
                price = ticker.get('bid', ticker.get('last', 0))
                if price <= 0:
                    return 0.0
                
                # Calcular valor antes de comisiones
                value_before_fee = amount * price
                
                # Aplicar comisión taker
                taker_fee = pair_info.get('taker', 0.001)  # 0.1% por defecto
                value_after_fee = value_before_fee * (1 - taker_fee)
                
                # Convertir a EUR si el fiat no es EUR
                fiat_asset = pair.split('/')[1]
                if fiat_asset == 'EUR':
                    return value_after_fee
                else:
                    # Convertir a EUR (USDC ≈ EUR 1:1)
                    return value_after_fee
                    
            elif route_type == 'intermediate' and pair and intermediate:
                # Ruta intermedia: ALT/INTERMEDIATE -> INTERMEDIATE/EUR
                pair1_info = get_pair_info(pair)
                if not pair1_info:
                    return 0.0
                
                # Primer swap: ALT -> INTERMEDIATE
                ticker1 = self.exchange.fetch_ticker(pair)
                if not ticker1:
                    return 0.0
                
                price1 = ticker1.get('bid', ticker1.get('last', 0))
                if price1 <= 0:
                    return 0.0
                
                # Calcular cantidad de intermediate recibida después de comisión
                taker_fee1 = pair1_info.get('taker', 0.001)
                intermediate_amount = (amount * price1) * (1 - taker_fee1)
                
                # Segundo swap: INTERMEDIATE -> EUR
                pair2 = f"{intermediate}/EUR"
                pair2_info = get_pair_info(pair2)
                if not pair2_info:
                    return 0.0
                
                ticker2 = self.exchange.fetch_ticker(pair2)
                if not ticker2:
                    return 0.0
                
                price2 = ticker2.get('bid', ticker2.get('last', 0))
                if price2 <= 0:
                    return 0.0
                
                # Calcular valor final en EUR después de segunda comisión
                taker_fee2 = pair2_info.get('taker', 0.001)
                value_final = (intermediate_amount * price2) * (1 - taker_fee2)
                
                return value_final
            
        except Exception as e:
            logger.debug(f"Error calculando valor de ruta {route_type}: {e}")
        
        return 0.0
    
    async def _analyze_btc_trend(self) -> Dict[str, Any]:
        """
        Analiza la tendencia macro de BTC para decidir almacenamiento de hucha.
        
        Returns:
            Dict con información de tendencia:
            - trend: 'bullish', 'bearish', o 'neutral'
            - change_24h: Cambio porcentual en 24h
            - change_7d: Cambio porcentual en 7 días
            - prefer_btc: True si se debe preferir BTC sobre EUR
        """
        try:
            # Obtener precio actual
            current_price = self.vault.get_asset_value('BTC', 1.0, 'EUR')
            if current_price <= 0:
                return {'trend': 'neutral', 'change_24h': 0, 'change_7d': 0, 'prefer_btc': False}
            
            # Obtener datos históricos
            btc_pair = None
            for fiat in self.fiat_assets:
                pair = f"BTC/{fiat}"
                if get_pair_info(pair):
                    btc_pair = pair
                    break
            
            if not btc_pair:
                return {'trend': 'neutral', 'change_24h': 0, 'change_7d': 0, 'prefer_btc': False}
            
            try:
                # Obtener precio de hace 24h (usando último ticker disponible y cálculo aproximado)
                ticker = self.exchange.fetch_ticker(btc_pair)
                change_24h = ticker.get('percentage', 0)  # Cambio porcentual en 24h del ticker
                
                # Obtener datos OHLCV para análisis de 7 días
                ohlcv_7d = self.exchange.fetch_ohlcv(btc_pair, '1d', limit=8)
                
                change_7d = 0
                if len(ohlcv_7d) >= 8:
                    price_7d_ago = ohlcv_7d[0][4]  # Cierre de hace 7 días
                    if price_7d_ago > 0:
                        change_7d = ((current_price - price_7d_ago) / price_7d_ago) * 100
                
                # Determinar tendencia
                # Alcista: sube >1% en 24h Y >2% en 7d
                # Bajista: baja <-1% en 24h O <-2% en 7d
                # Neutral: resto de casos
                
                if change_24h > 1.0 and change_7d > 2.0:
                    trend = 'bullish'
                    prefer_btc = True
                elif change_24h < -1.0 or change_7d < -2.0:
                    trend = 'bearish'
                    prefer_btc = False
                else:
                    trend = 'neutral'
                    prefer_btc = False
                
                return {
                    'trend': trend,
                    'change_24h': change_24h,
                    'change_7d': change_7d,
                    'prefer_btc': prefer_btc
                }
                
            except Exception as e:
                logger.debug(f"Error obteniendo datos históricos de BTC: {e}")
                return {'trend': 'neutral', 'change_24h': 0, 'change_7d': 0, 'prefer_btc': False}
                
        except Exception as e:
            logger.debug(f"Error analizando tendencia BTC: {e}")
            return {'trend': 'neutral', 'change_24h': 0, 'change_7d': 0, 'prefer_btc': False}
    
    async def _find_best_destination_from_radar(self, exclude_assets: list = None, source_asset: str = None) -> Optional[Tuple[str, int]]:
        """
        🎯 Busca el mejor destino en el radar priorizando swaps directos entre activos.
        
        NO busca EUR por defecto. Prioriza activos de la whitelist con pares directos disponibles.
        
        Args:
            exclude_assets: Lista de activos a excluir (ej: el activo que estamos vendiendo)
            source_asset: Activo de origen (para verificar par directo disponible)
        
        Returns:
            Tupla (destination_asset, heat_score) o None si no hay destino adecuado
        """
        try:
            exclude_assets = exclude_assets or []
            # 🎯 Tratar EUR/USDC como activos normales (no excluirlos automáticamente)
            # Solo excluir BNB para gas, y activos explícitamente en exclude_assets
            # El bot debe poder diversificar hacia cualquier activo de la whitelist, incluyendo FIAT
            
            # Leer radar.json o usar cache del motor
            radar_list = []
            if self.radar_data_cache:
                # Usar cache del radar dinámico
                for currency, data in self.radar_data_cache.items():
                    if currency not in exclude_assets:
                        radar_list.append(data.copy())
                radar_list.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
            else:
                # Intentar leer desde archivo
                try:
                    if HAS_FILE_UTILS:
                        radar_data = read_json_safe(self.radar_path, {})
                    else:
                        if self.radar_path.exists():
                            with open(self.radar_path, 'r', encoding='utf-8') as f:
                                radar_data = json.load(f)
                        else:
                            radar_data = {}
                    
                    if radar_data and 'radar_data' in radar_data:
                        for currency_data in radar_data.get('radar_data', []):
                            currency = currency_data.get('currency', '')
                            if currency not in exclude_assets:
                                radar_list.append(currency_data)
                        radar_list.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
                except:
                    pass
            
            # 🎯 Si no hay datos en radar, buscar directamente en whitelist
            if not radar_list:
                logger.debug("No hay datos en radar, buscando en whitelist directamente")
                whitelist = self.strategy.get("whitelist", [])
                for currency in whitelist:
                    if currency not in exclude_assets:
                        # Crear entrada básica con heat_score neutro
                        radar_list.append({
                            'currency': currency,
                            'heat_score': 50  # Score neutro para activos sin radar
                        })
            
            if not radar_list:
                return None
            
            # 🎯 PRIORIZAR activos con par directo disponible (si source_asset está disponible)
            prioritized_list = []
            other_list = []
            
            for currency_data in radar_list:
                currency = currency_data.get('currency', '')
            
            # Verificar que esté en la whitelist
                if currency not in self.strategy.get("whitelist", []):
                    continue
                
                # Si tenemos source_asset, verificar par directo
                if source_asset:
                    direct_pair_candidates = [
                        f"{source_asset}/{currency}",
                        f"{currency}/{source_asset}"
                    ]
                    has_direct_pair = False
                    for pair_candidate in direct_pair_candidates:
                        pair_info = get_pair_info(pair_candidate)
                        if pair_info:
                            has_direct_pair = True
                            break
                    
                    if has_direct_pair:
                        prioritized_list.append(currency_data)
                    else:
                        other_list.append(currency_data)
                else:
                    # Sin source_asset, todos van a other_list
                    other_list.append(currency_data)
            
            # Combinar: primero los que tienen par directo, luego los demás
            sorted_list = prioritized_list + other_list
            
            if not sorted_list:
                return None
            
            # Seleccionar el mejor (mayor heat_score, priorizando pares directos)
            best_destination = sorted_list[0]
            destination_asset = best_destination.get('currency', '')
            heat_score = best_destination.get('heat_score', 0)
            
            # 🎯 Umbral más bajo: aceptar cualquier oportunidad de diversificación (heat_score > 50)
            # Esto permite diversificar incluso si el radar no muestra heat_score alto
            if heat_score < 50:
                # Si el heat_score es muy bajo pero hay par directo, aceptarlo igual
                if source_asset and destination_asset in prioritized_list:
                    logger.info(
                        f"🎯 Aceptando diversificación {source_asset} -> {destination_asset} "
                        f"(Heat: {heat_score}, par directo disponible)"
                    )
                    return (destination_asset, heat_score)
                return None
            
            return (destination_asset, heat_score)
            
        except Exception as e:
            logger.error(f"Error buscando mejor destino en radar: {e}")
            return None
    
    async def _find_best_swap_route(self, source_asset: str, target_asset: str, amount: float) -> Tuple[str, Optional[str], float]:
        """
        Encuentra la mejor ruta para hacer swap desde source_asset hacia target_asset.
        
        Prioriza pares directos sobre rutas intermedias para minimizar comisiones.
        
        Args:
            source_asset: Activo de origen
            target_asset: Activo de destino (puede ser cualquier activo, no solo EUR)
            amount: Cantidad del activo de origen
        
        Returns:
            (best_pair, intermediate_asset, expected_target_value_eur)
            - best_pair: Par a usar para el swap (None si no hay ruta)
            - intermediate_asset: Moneda intermedia si es ruta intermedia, None si es directa
            - expected_target_value_eur: Valor esperado del destino en EUR después de comisiones
        """
        try:
            # PRIORIDAD 1: Buscar par directo source_asset/target_asset
            direct_pair_candidates = [
                f"{source_asset}/{target_asset}",
                f"{target_asset}/{source_asset}"
            ]
            
            direct_pair = None
            direct_value_eur = 0.0
            
            for pair_candidate in direct_pair_candidates:
                pair_info = get_pair_info(pair_candidate)
                if pair_info:
                    direct_pair = pair_candidate
                    try:
                        # Obtener ticker para calcular valor recibido
                        ticker = self.exchange.fetch_ticker(pair_candidate)
                        if ticker:
                            base, quote = pair_candidate.split('/')
                            
                            if base == source_asset:
                                # Par directo: source/target - vender source para recibir target
                                price = ticker.get('bid', ticker.get('last', 0))  # Precio de venta
                                if price > 0:
                                    taker_fee = pair_info.get('taker', 0.001)
                                    target_amount = (amount * price) * (1 - taker_fee)
                                    direct_value_eur = self.vault.get_asset_value(target_asset, target_amount, 'EUR')
                            else:
                                # Par inverso: target/source - comprar target con source
                                price = ticker.get('ask', ticker.get('last', 0))  # Precio de compra
                                if price > 0:
                                    # Calcular cuánto target podemos comprar con amount de source
                                    source_value_eur = self.vault.get_asset_value(source_asset, amount, 'EUR')
                                    taker_fee = pair_info.get('taker', 0.001)
                                    target_amount = (source_value_eur / price) * (1 - taker_fee)
                                    direct_value_eur = self.vault.get_asset_value(target_asset, target_amount, 'EUR')
                    except Exception as e:
                        # 🔄 FALLBACK: Si hay error de liquidez o par no encontrado, intentar EUR
                        error_msg = str(e).lower()
                        if 'liquidity' in error_msg or 'not found' in error_msg or 'insufficient' in error_msg:
                            logger.debug(
                                f"⚠️ Par directo {pair_candidate} no disponible (error: {e}). "
                                f"Se intentará ruta a través de EUR como fallback."
                            )
                        else:
                            logger.debug(f"Error calculando valor de ruta directa {pair_candidate}: {e}")
                            direct_value_eur = 0.0
                    
                    if direct_value_eur > 0:
                        break
            
            # PRIORIDAD 2: Si no hay par directo, usar find_swap_route para buscar ruta óptima
            # 🔄 FALLBACK: Si el destino no es EUR y no hay par directo, intentar ruta a través de EUR
            best_intermediate_pair = None
            best_intermediate = None
            best_intermediate_value_eur = 0.0
            
            if not direct_pair or direct_value_eur <= 0:
                # Usar router para encontrar mejor ruta
                route = find_swap_route(
                    source_asset,
                    target_asset,
                    self.strategy["whitelist"],
                    self.fiat_assets,
                    prefer_low_fees=True
                )
                
                if route:
                    best_intermediate_pair, best_intermediate = route
                    
                    # Calcular valor aproximado usando _calculate_route_value
                    if best_intermediate:
                        # Ruta de dos pasos: source -> intermediate -> target
                        # Usamos aproximación: calcular primer paso y estimar segundo
                        intermediate_value_eur = await self._calculate_route_value(
                            'direct', source_asset, amount, pair=best_intermediate_pair
                        )
                        # Aproximación: asumimos que el segundo swap mantiene el valor en EUR
                        best_intermediate_value_eur = intermediate_value_eur * 0.998  # Segunda comisión aproximada
                    else:
                        # Ruta directa encontrada por router (fallback)
                        direct_pair = best_intermediate_pair
                        best_intermediate_value_eur = await self._calculate_route_value(
                            'direct', source_asset, amount, pair=best_intermediate_pair
                        )
                elif target_asset not in self.fiat_assets:
                    # 🚫 ÚLTIMO RECURSO: Solo usar EUR como puente si NO hay otra opción
                    # Primero intentar otros activos de la whitelist como puente
                    logger.debug(
                        f"🔄 No se encontró ruta directa {source_asset} -> {target_asset}. "
                        f"Buscando activos intermedios en whitelist..."
                    )
                    
                    # Buscar activos intermedios en whitelist (NO EUR)
                    whitelist = self.strategy.get("whitelist", [])
                    best_intermediate_candidate = None
                    best_intermediate_value_candidate = 0.0
                    
                    for intermediate_candidate in whitelist:
                        if intermediate_candidate in [source_asset, target_asset, 'EUR', 'USDC', 'BNB']:
                            continue
                        
                        # Verificar ruta: source -> intermediate -> target
                        route1 = find_swap_route(
                            source_asset,
                            intermediate_candidate,
                            self.strategy["whitelist"],
                            self.fiat_assets,
                            prefer_low_fees=True
                        )
                        route2 = find_swap_route(
                            intermediate_candidate,
                            target_asset,
                            self.strategy["whitelist"],
                            self.fiat_assets,
                            prefer_low_fees=True
                        )
                        
                        if route1 and route2:
                            # Calcular valor estimado de la ruta de dos pasos
                            intermediate_pair1, _ = route1
                            intermediate_value_eur = await self._calculate_route_value(
                                'direct', source_asset, amount, pair=intermediate_pair1
                            )
                            # Aproximación: segunda comisión
                            final_value_eur = intermediate_value_eur * 0.998
                            
                            if final_value_eur > best_intermediate_value_candidate:
                                best_intermediate_candidate = intermediate_candidate
                                best_intermediate_pair = intermediate_pair1
                                best_intermediate = intermediate_candidate
                                best_intermediate_value_eur = final_value_eur
                    
                    # Solo si NO se encontró ningún puente en whitelist, usar EUR como último recurso
                    if not best_intermediate_candidate:
                        logger.warning(
                            f"⚠️ No se encontró puente en whitelist. Usando EUR como último recurso."
                        )
                        route_via_eur = find_swap_route(
                            source_asset,
                            'EUR',
                            self.strategy["whitelist"],
                            self.fiat_assets,
                            prefer_low_fees=True
                        )
                        if route_via_eur:
                            best_intermediate_pair, _ = route_via_eur
                            best_intermediate = 'EUR'
                            intermediate_value_eur = await self._calculate_route_value(
                                'direct', source_asset, amount, pair=best_intermediate_pair
                            )
                            best_intermediate_value_eur = intermediate_value_eur * 0.998
            
            # Comparar rutas: priorizar par directo siempre (menos comisiones)
            if direct_pair and direct_value_eur > 0:
                logger.debug(
                    f"✅ Ruta directa seleccionada: {direct_pair} "
                    f"(Esperado: {direct_value_eur:.2f}€ en {target_asset})"
                )
                return (direct_pair, None, direct_value_eur)
            elif best_intermediate_pair and best_intermediate_value_eur > 0:
                logger.info(
                    f"🔄 Ruta intermedia seleccionada: {source_asset} -> {best_intermediate or 'direct'} -> {target_asset} "
                    f"(Esperado: {best_intermediate_value_eur:.2f}€ en {target_asset})"
                )
                return (best_intermediate_pair, best_intermediate, best_intermediate_value_eur)
            else:
                logger.warning(f"❌ No se encontró ruta para swap {source_asset} -> {target_asset}")
                return (None, None, 0.0)
                    
        except Exception as e:
            logger.error(f"Error buscando mejor ruta de swap {source_asset} -> {target_asset}: {e}")
            return (None, None, 0.0)
    
    async def _find_best_sell_route(self, target_asset: str, amount: float) -> Tuple[str, Optional[str], float]:
        """
        DEPRECATED: Usar _find_best_swap_route en su lugar.
        Mantenido para compatibilidad con código existente que vende a EUR.
        
        Encuentra la mejor ruta para vender un activo y retornar a EUR.
        
        Returns:
            (best_pair, intermediate_asset, expected_eur_value)
            - best_pair: Par a usar para la venta
            - intermediate_asset: Moneda intermedia si es ruta intermedia, None si es directa
            - expected_eur_value: Valor esperado en EUR después de comisiones
        """
        # Delegar a la nueva función con destino EUR
        return await self._find_best_swap_route(target_asset, 'EUR', amount)
    
    async def execute_sell(self, slot_id: int, trade_id: int, trade: Dict[str, Any]) -> bool:
        """Ejecuta una orden de venta optimizada y cierra el trade."""
        try:
            target_asset = trade['target_asset']
            amount = trade['amount']
            initial_fiat_value = trade['initial_fiat_value']
            
            # 🎯 PRIORIDAD: Buscar activamente el mejor destino en whitelist (NO EUR por defecto)
            destination_result = await self._find_best_destination_from_radar(
                exclude_assets=[target_asset],
                source_asset=target_asset
            )
            
            if destination_result:
                destination_asset, destination_heat_score = destination_result
                logger.info(
                    f"[Slot {slot_id}] 🎯 Destino seleccionado desde Radar/Whitelist: {destination_asset} "
                    f"(Heat Score: {destination_heat_score})"
                )
                # Usar _find_best_swap_route para ir directamente al destino (prioriza par directo)
                best_pair, intermediate, expected_value = await self._find_best_swap_route(
                    target_asset, destination_asset, amount
                )
                final_destination = destination_asset
            else:
                # 🎯 ÚLTIMO RECURSO: Buscar en whitelist directamente (sin radar)
                logger.info(
                    f"[Slot {slot_id}] No hay destino en radar, buscando directamente en whitelist "
                    f"para diversificar desde {target_asset}..."
                )
                
                # Buscar mejor oportunidad en whitelist
                whitelist_destination = await self._find_best_whitelist_destination(
                    source_asset=target_asset,
                    exclude_assets=[target_asset]
                )
                
                if whitelist_destination:
                    destination_asset = whitelist_destination
                    logger.info(
                        f"[Slot {slot_id}] 🎯 Destino encontrado en whitelist: {destination_asset}"
                    )
                    best_pair, intermediate, expected_value = await self._find_best_swap_route(
                        target_asset, destination_asset, amount
                    )
                    final_destination = destination_asset
                else:
                    # 🚫 ÚLTIMO RECURSO ABSOLUTO: Solo usar EUR si NO hay ninguna otra opción
                    logger.warning(
                        f"[Slot {slot_id}] ⚠️ No se encontró ningún destino en whitelist con par disponible. "
                        f"Usando EUR como último recurso."
                    )
                best_pair, intermediate, expected_value = await self._find_best_sell_route(target_asset, amount)
                final_destination = 'EUR'
            
            if not best_pair:
                logger.error(f"No se encontró ruta para vender {target_asset}")
                return False
            
            # 💎 HUCHA SELECTIVA: Determinar activo de destino
            # Si hay ruta intermedia, el destino es el intermediate; si no, es el destino final
            if intermediate:
                target_asset_for_hucha = intermediate
            else:
                # Ruta directa: el destino es el activo final (puede ser del radar o EUR)
                target_asset_for_hucha = final_destination
            
            # 💎 HUCHA SELECTIVA: Calcular si debemos guardar 5% (solo si destino está en RESERVE_ASSETS)
            hucha_amount = 0.0
            amount_to_sell = amount
            
            # Calcular profit estimado antes de vender
            current_value_eur = self.vault.get_asset_value(target_asset, amount, 'EUR')
            estimated_profit_eur = expected_value - initial_fiat_value
            estimated_profit_percent = (estimated_profit_eur / initial_fiat_value * 100) if initial_fiat_value > 0 else 0
            
            # Si profit > 1% Y el destino está en RESERVE_ASSETS, guardar 5%
            if estimated_profit_percent > 1.0 and target_asset_for_hucha in self.RESERVE_ASSETS:
                hucha_amount = amount * 0.05  # 5% del total
                amount_to_sell = amount * 0.95  # 95% para vender
                
                # Verificar que el 95% cubra el capital inicial
                estimated_final_value_eur = expected_value * 0.95  # Valor estimado del 95%
                if estimated_final_value_eur < initial_fiat_value:
                    # Si el 95% no cubre el capital, no guardamos hucha y vendemos todo
                    logger.warning(
                        f"[Slot {slot_id}] El 95% ({estimated_final_value_eur:.2f}€) no cubre el capital inicial "
                        f"({initial_fiat_value:.2f}€). No se guardará hucha."
                    )
                    hucha_amount = 0.0
                    amount_to_sell = amount
            else:
                # Si no es activo de reserva o profit <= 1%, transferir 100% (maximizar interés compuesto)
                if estimated_profit_percent > 1.0:
                    logger.info(
                        f"[Slot {slot_id}] Profit {estimated_profit_percent:.2f}% pero destino {target_asset_for_hucha} "
                        f"no está en RESERVE_ASSETS. Transferencia 100% para maximizar interés compuesto."
                    )
                else:
                    logger.debug(f"[Slot {slot_id}] Profit {estimated_profit_percent:.2f}% <= 1%. No se guarda hucha.")
            
            # Verificar si la cantidad a vender es menor al mínimo de Binance
            try:
                market = self.exchange.market(best_pair)
                min_amount = market.get('limits', {}).get('amount', {}).get('min', 0)
                if min_amount > 0 and amount_to_sell < min_amount:
                    logger.warning(
                        f"Cantidad a vender ({amount_to_sell}) menor al mínimo de Binance ({min_amount}) para {best_pair}. "
                        f"No se puede vender. El trade será desactivado directamente."
                    )
                    # Si no podemos vender, tampoco guardamos hucha
                    return False
            except Exception as e:
                logger.debug(f"Error verificando mínimo de Binance: {e}")
            
            amount_to_sell = self.exchange.amount_to_precision(best_pair, amount_to_sell)
            
            hucha_info = f" (Hucha: {hucha_amount:.8f} {target_asset} guardado)" if hucha_amount > 0 else ""
            logger.info(f"Ejecutando venta optimizada: {best_pair}, cantidad: {amount_to_sell} (de {amount} total){hucha_info}")
            order1 = self.exchange.create_market_sell_order(best_pair, amount_to_sell)
            
            executed_price1 = order1.get('price', 0)
            executed_amount1 = order1.get('filled', amount_to_sell)
            
            # Si hay ruta intermedia, ejecutar segundo swap
            final_destination_amount = executed_amount1
            if intermediate:
                # El primer swap nos dio intermediate, ahora hacer swap al destino final
                if final_destination != 'EUR':
                    # Destino es del radar (no EUR) - intentar par directo
                    intermediate_pair_candidates = [
                        f"{intermediate}/{final_destination}",
                        f"{final_destination}/{intermediate}"
                    ]
                    intermediate_pair = None
                    for candidate in intermediate_pair_candidates:
                        if candidate in [p['symbol'] for p in self.exchange.markets.values()]:
                            intermediate_pair = candidate
                            break
                    
                    # Si el par no existe, intentar EUR como fallback
                    if not intermediate_pair:
                        intermediate_pair = f"{intermediate}/EUR"
                        final_destination = 'EUR'
                else:
                    # Fallback tradicional: vender a EUR
                    intermediate_pair = f"{intermediate}/EUR"
                
                intermediate_amount = executed_amount1  # Cantidad recibida del primer swap
                
                try:
                    intermediate_amount = self.exchange.amount_to_precision(intermediate_pair, intermediate_amount)
                    logger.info(f"Ejecutando segundo swap: {intermediate_pair}, cantidad: {intermediate_amount}")
                    # Determinar si es compra o venta según el par
                    if intermediate_pair.startswith(f"{intermediate}/"):
                        order2 = self.exchange.create_market_sell_order(intermediate_pair, intermediate_amount)
                    else:
                        # Par inverso: necesitamos comprar
                        order2 = self.exchange.create_market_buy_order(intermediate_pair, intermediate_amount)
                    final_destination_amount = order2.get('filled', intermediate_amount)
                except Exception as e:
                    logger.error(f"Error en segundo swap {intermediate_pair}: {e}")
                    # Si falla el segundo swap, usar el valor del intermediate
                    final_destination_amount = self.vault.get_asset_value(intermediate, executed_amount1, final_destination)
            
            # Calcular valor final (convertir a EUR para métricas)
            if intermediate:
                # Ya tenemos el activo del segundo swap
                final_asset = final_destination
                final_value_eur = self.vault.get_asset_value(final_asset, final_destination_amount, 'EUR')
            else:
                # Ruta directa: el destino puede ser del radar o EUR
                final_asset = final_destination
                final_value_eur = self.vault.get_asset_value(final_asset, final_destination_amount, 'EUR')
            
            # Calcular profit basado en lo que realmente se vendió (95% o 100%)
            profit_eur = final_value_eur - initial_fiat_value
            profit_percent = (profit_eur / initial_fiat_value * 100) if initial_fiat_value > 0 else 0
            
            # 💎 HUCHA SELECTIVA: Guardar hucha diversificada si se calculó
            if hucha_amount > 0:
                # Calcular valor en EUR de la hucha al momento de guardar
                hucha_value_eur = self.vault.get_asset_value(target_asset, hucha_amount, 'EUR')
                await self._save_hucha_diversificada(target_asset, hucha_amount, hucha_value_eur)
                logger.info(
                    f"💎 Hucha diversificada guardada: {hucha_amount:.8f} {target_asset} "
                    f"(valor: {hucha_value_eur:.2f}€)"
                )
            write_bitacora(
                    f"[💎 HUCHA_SAVE] Hucha diversificada: Guardados {hucha_amount:.8f} {target_asset} "
                    f"({hucha_value_eur:.2f}€) desde venta con profit {profit_percent:.2f}%"
                )
            
            if intermediate:
                route_info = f"{best_pair} -> {intermediate_pair if 'intermediate_pair' in locals() else f'{intermediate}/{final_destination}'}"
            else:
                route_info = f"{best_pair} (directo a {final_destination})"
            hucha_info_msg = f" (Hucha: {hucha_amount:.8f} {target_asset} guardado)" if hucha_amount > 0 else ""
            profit_sign = "+" if profit_percent >= 0 else ""
            write_bitacora(
                f"[💰 VENTA_SLOT] Slot {slot_id + 1}: {target_asset} (Ruta: {route_info}){hucha_info_msg} | "
                f"Resultado: {profit_sign}{profit_percent:.2f}%"
            )
            
            logger.info(
                f"[Slot {slot_id}] Venta optimizada ejecutada: {route_info}{hucha_info_msg} | "
                f"Vendido: {amount_to_sell:.8f} {target_asset} | Ganancia: {profit_eur:+.2f} EUR ({profit_percent:+.2f}%)"
            )
            
            # 🔄 CONTINUIDAD DE INVENTARIO: Si el destino no es EUR, crear nuevo trade para mantener el slot activo
            # Esto evita el retorno automático a EUR y mantiene el capital en movimiento
            if final_destination != 'EUR' and final_destination_amount > 0:
                # Obtener precio de entrada del nuevo activo
                try:
                    # Buscar par para obtener precio
                    destination_pair = None
                    for base in self.fiat_assets:
                        pair_candidate = f"{final_destination}/{base}"
                        if get_pair_info(pair_candidate):
                            destination_pair = pair_candidate
                            break
                    
                    if not destination_pair:
                        # Intentar par inverso
                        for base in self.fiat_assets:
                            pair_candidate = f"{base}/{final_destination}"
                            if get_pair_info(pair_candidate):
                                destination_pair = pair_candidate
                                break
                    
                    if destination_pair:
                        ticker = self.exchange.fetch_ticker(destination_pair)
                        entry_price = ticker.get('last', 0)
                    else:
                        # Calcular precio desde valor EUR
                        entry_price = final_value_eur / final_destination_amount if final_destination_amount > 0 else 0
                    
                    # Obtener path_history del trade original
                    path_history = trade.get('path_history', target_asset) + f" > {final_destination}"
                    
                    # Crear nuevo trade con el activo de destino
                    # Mantener initial_fiat_value para arrastrar el PNL a través de los swaps
                    new_trade_id = self.db.create_trade(
                        slot_id=slot_id,
                        symbol=destination_pair if destination_pair else f"{final_destination}/EUR",
                        base_asset=final_destination if destination_pair and final_destination in destination_pair.split('/') else 'EUR',
                        target_asset=final_destination,
                        amount=final_destination_amount,
                        entry_price=entry_price,
                        initial_fiat_value=initial_fiat_value,  # ✅ Mantener PNL original
                        path_history=path_history
                    )
                    
                    logger.info(
                        f"🔄 Continuidad de inventario: Nuevo trade creado en slot {slot_id} "
                        f"con {final_destination} (Trade ID: {new_trade_id}). "
                        f"PNL arrastrado desde {target_asset} (initial_fiat_value: {initial_fiat_value:.2f}€)"
                    )
                    
                    # Desactivar el trade original
                    self.db.deactivate_trade(trade_id)
                except Exception as e:
                    logger.error(f"Error creando nuevo trade para continuidad de inventario: {e}")
                    # Si falla, desactivar el trade original
                    self.db.deactivate_trade(trade_id)
            else:
                # Si el destino es EUR o no hay cantidad, solo desactivar el trade
                self.db.deactivate_trade(trade_id)
            
            # 💰 HUCHA OPORTUNISTA (ANTIGUA - DESHABILITADA)
            # NOTA: Esta lógica está deshabilitada porque ahora usamos Hucha Diversificada
            # (guardar 5% del activo mismo, no convertirlo a EUR/BTC)
            # Para reactivar esta lógica, cambiar hucha_antigua_deshabilitada a True:
            hucha_antigua_deshabilitada = False  # Cambiar a True para reactivar hucha antigua
            if hucha_antigua_deshabilitada and self.hucha_enabled and final_value_eur > 0:
                # Distribución dinámica según tendencia macro de BTC
                # Si BTC está alcista, preferir más BTC; si está bajista, preferir más EUR
                # Analizar tendencia de BTC
                btc_trend = await self._analyze_btc_trend()
                prefer_btc = btc_trend.get('prefer_btc', False)
                
                # Ajustar distribución según tendencia
                if prefer_btc:
                    # Tendencia alcista: 70% BTC, 30% EUR
                    hucha_btc_pct_adjusted = (self.hucha_eur_pct + self.hucha_btc_pct) * 0.7
                    hucha_eur_pct_adjusted = (self.hucha_eur_pct + self.hucha_btc_pct) * 0.3
                    logger.info(
                        f"📈 Tendencia BTC alcista detectada (24h: {btc_trend.get('change_24h', 0):+.2f}%, "
                        f"7d: {btc_trend.get('change_7d', 0):+.2f}%) - "
                        f"Ajustando Hucha: {hucha_btc_pct_adjusted:.1f}% BTC, {hucha_eur_pct_adjusted:.1f}% EUR"
                    )
                else:
                    # Tendencia bajista o neutral: distribución estándar o más EUR
                    if btc_trend.get('trend') == 'bearish':
                        # Tendencia bajista: 70% EUR, 30% BTC
                        hucha_eur_pct_adjusted = (self.hucha_eur_pct + self.hucha_btc_pct) * 0.7
                        hucha_btc_pct_adjusted = (self.hucha_eur_pct + self.hucha_btc_pct) * 0.3
                        logger.info(
                            f"📉 Tendencia BTC bajista detectada (24h: {btc_trend.get('change_24h', 0):+.2f}%, "
                            f"7d: {btc_trend.get('change_7d', 0):+.2f}%) - "
                            f"Ajustando Hucha: {hucha_eur_pct_adjusted:.1f}% EUR, {hucha_btc_pct_adjusted:.1f}% BTC"
                        )
                    else:
                        # Neutral: distribución estándar (50/50)
                        hucha_eur_pct_adjusted = self.hucha_eur_pct
                        hucha_btc_pct_adjusted = self.hucha_btc_pct
                
                hucha_total_pct = hucha_eur_pct_adjusted + hucha_btc_pct_adjusted
                hucha_total_eur = final_value_eur * (hucha_total_pct / 100.0)
                hucha_eur_amount = final_value_eur * (hucha_eur_pct_adjusted / 100.0)
                hucha_btc_amount_eur = final_value_eur * (hucha_btc_pct_adjusted / 100.0)
                
                if hucha_total_eur > 0.01:  # Mínimo 1 céntimo
                    try:
                        # Obtener precio BTC para calcular cantidad equivalente
                        btc_price_eur = self.vault.get_asset_value('BTC', 1.0, 'EUR')
                        hucha_btc_amount = hucha_btc_amount_eur / btc_price_eur if btc_price_eur > 0 else 0
                        
                        # Guardar hucha EUR en treasury
                        self.db.add_to_treasury(
                            amount_eur=hucha_eur_amount,
                            amount_btc=hucha_btc_amount,
                            description=f"Hucha Oportunista (Tax-on-Exit) - Venta {target_asset} a {fiat_asset}"
                        )
                        
                        logger.info(
                            f"💰 Hucha Oportunista aplicada: {hucha_eur_amount:.2f} EUR + "
                            f"{hucha_btc_amount:.8f} BTC ({hucha_btc_amount_eur:.2f} EUR) = "
                            f"{hucha_total_eur:.2f} EUR total ({hucha_total_pct}%)"
                        )
                        
                        write_bitacora(
                            f"[💎 HUCHA_SAVE] Hucha oportunista: {hucha_eur_amount:.2f}€ EUR + {hucha_btc_amount:.8f} BTC "
                            f"({hucha_btc_amount_eur:.2f}€) guardados desde venta de {target_asset}"
                        )
                        
                        # Comprar BTC con la parte correspondiente (optimización: solo 1 operación extra)
                        if hucha_btc_amount_eur > 0.01:
                            try:
                                btc_pair = None
                                for fiat in self.fiat_assets:
                                    pair = f"BTC/{fiat}"
                                    if get_pair_info(pair):
                                        btc_pair = pair
                                        break
                                
                                if btc_pair:
                                    btc_amount_to_buy = hucha_btc_amount_eur / btc_price_eur
                                    btc_amount_to_buy = self.exchange.amount_to_precision(btc_pair, btc_amount_to_buy)
                                    
                                    if btc_amount_to_buy > 0:
                                        btc_order = self.exchange.create_market_buy_order(btc_pair, btc_amount_to_buy)
                                        filled_btc = btc_order.get('filled', 0)
                                        logger.info(f"💰 BTC comprado para hucha: {filled_btc:.8f} BTC")
                            except Exception as e:
                                logger.debug(f"Error al comprar BTC para hucha: {e}")
                                # No es crítico, el EUR ya está guardado en treasury
                    except Exception as e:
                        logger.error(f"Error al aplicar Hucha Oportunista: {e}")
            
            # ⛽ GESTIÓN DE GAS POR INERCIA: Mantenimiento Pasivo
            # Si la venta es a BNB y el gas < 5%, retener BNB para rellenar
            if fiat_asset == 'BNB' or target_asset == 'BNB':
                current_gas_percent = self._get_gas_percentage()
                if current_gas_percent < self.gas_max_target:
                    # Si recibimos BNB, retener para gas
                    if fiat_asset == 'BNB':
                        bnb_received = final_fiat_amount  # Cantidad recibida en BNB
                        bnb_retained = await self._refill_gas_passive(bnb_received, self.gas_max_target)
                        if bnb_retained > 0:
                            # Ajustar final_value_eur para excluir el BNB retenido
                            bnb_price_eur = self.vault.get_asset_value('BNB', 1.0, 'EUR')
                            final_value_eur = final_value_eur - (bnb_retained * bnb_price_eur)
            
            savings_mode = self.strategy["risk"].get("savings_mode", True)
            if profit_eur > 0 and savings_mode:
                savings_result = self.vault.apply_savings(profit_eur)
                if savings_result.get('applied'):
                    savings_eur = savings_result.get('savings_amount_eur', 0.0)
                    write_bitacora(f"[💎 HUCHA_SAVE] Tesoro: Se han enviado {savings_eur:.2f}€ al Tesoro Guardado.")
            
            # Mantener lógica antigua de BNB como fallback (se puede eliminar después)
            bnb_status = self.vault.check_and_refill_bnb()
            if bnb_status.get('needs_refill', False) and final_value_eur > 0:
                total_portfolio = self.vault.calculate_total_portfolio_value()
                bnb_config = self.strategy.get("bnb_management", {})
                target_bnb_percent = bnb_config.get("min_target_percent", 3.0)
                target_bnb_value = total_portfolio * (target_bnb_percent / 100.0)
                current_bnb_value = self.vault.get_asset_value('BNB', 
                    self.exchange.fetch_balance().get('BNB', {}).get('total', 0), 'EUR')
                needed_bnb_value = max(0, target_bnb_value - current_bnb_value)
                
                if needed_bnb_value > 0 and needed_bnb_value <= final_value_eur * 0.1:
                    try:
                        bnb_price_eur = self.vault.get_asset_value('BNB', 1.0, 'EUR')
                        if bnb_price_eur > 0:
                            bnb_amount = needed_bnb_value / bnb_price_eur
                            bnb_pair = None
                            for fiat in self.fiat_assets:
                                pair = f"BNB/{fiat}"
                                if get_pair_info(pair):
                                    bnb_pair = pair
                                    break
                            
                            if bnb_pair:
                                bnb_amount = self.exchange.amount_to_precision(bnb_pair, bnb_amount)
                                order = self.exchange.create_market_buy_order(bnb_pair, bnb_amount)
                                
                                filled_bnb = order.get('filled', 0)
                                new_bnb_percent = (target_bnb_value / total_portfolio * 100) if total_portfolio > 0 else 0
                                write_bitacora(
                                    f"[⛽ GAS_RETENIDO] Gas reposición: Comprado {needed_bnb_value:.2f}€ en BNB. "
                                    f"El fondo para comisiones se ha restablecido a {new_bnb_percent:.2f}%."
                                )
                                
                                logger.info(f"⛽ BNB recargado desde venta: {filled_bnb:.8f} BNB ({needed_bnb_value:.2f} EUR)")
                    except Exception as e:
                        logger.debug(f"Error al recargar BNB desde venta: {e}")
            
            self.db.deactivate_trade(trade_id)
            
            path_history = trade.get('path_history', '') + f" > {fiat_asset}"
            self.db.update_trade(trade_id, path_history=path_history)
            
            logger.info(f"Trade {trade_id} cerrado exitosamente en slot {slot_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error al ejecutar venta en slot {slot_id}: {e}")
            return False
    
    async def _rebalance_to_whitelist_asset(self, currency: str, excess_value_eur: float, destination: str) -> bool:
        """
        🎯 Reequilibra exceso directamente a un activo de la whitelist.
        Versión optimizada que usa el destino ya encontrado.
        """
        try:
            balances = self.exchange.fetch_balance()
            total_balance = balances.get('total', {}).get(currency, 0.0)
            
            if total_balance <= 0:
                return False
            
            # Calcular cantidad a vender (exceso)
            current_value_eur = self.vault.get_asset_value(currency, total_balance, 'EUR')
            if current_value_eur <= 0:
                return False
            
            excess_percent = (excess_value_eur / current_value_eur) if current_value_eur > 0 else 0
            excess_amount = total_balance * excess_percent
            
            # Asegurar mínimo de 10€
            excess_value_check = self.vault.get_asset_value(currency, excess_amount, 'EUR')
            if excess_value_check < 10.0:
                min_amount_eur = 10.0
                excess_amount = (min_amount_eur / current_value_eur * total_balance) if current_value_eur > 0 else 0
            
            excess_amount = min(excess_amount, total_balance)
            
            if excess_amount <= 0:
                return False
            
            # Buscar ruta óptima (prioriza par directo)
            best_pair, intermediate, expected_value = await self._find_best_swap_route(
                currency, destination, excess_amount
            )
            
            if best_pair:
                try:
                    sell_amount = self.exchange.amount_to_precision(best_pair, excess_amount)
                    order = self.exchange.create_market_sell_order(best_pair, sell_amount)
                    
                    if order and order.get('filled', 0) > 0:
                        filled = order.get('filled', 0)
                        logger.info(
                            f"✅ Exceso intercambiado: {currency} → {destination} "
                            f"usando par {best_pair} (cantidad: {filled:.8f})"
                        )
                        
                        write_bitacora(
                            f"[🔄 SWAP_DIVERSIFICACIÓN] {currency} → {destination}: "
                            f"{excess_value_eur:.2f}€ vendidos (Diversificación automática)"
                        )
                        
                        return True
                except Exception as e:
                    logger.debug(f"Error en swap {currency} → {destination}: {e}")
            
            return False
            
        except Exception as e:
            logger.error(f"Error en reequilibrio a whitelist: {e}")
            return False
    
    async def _rebalance_overexposed_asset(self, currency: str, excess_value_eur: float) -> bool:
        """
        🎯 RE-EQUILIBRIO AUTOMÁTICO: Vende el exceso de un activo sobreexpuesto.
        
        Cuando un activo supera el 25% del portfolio, vende solo el exceso y lo convierte
        a FIAT o redistribuye según las oportunidades del radar.
        
        Args:
            currency: Activo sobreexpuesto
            excess_value_eur: Valor en EUR que excede el 25% (capital a vender)
        
        Returns:
            True si el reequilibrio fue exitoso, False en caso contrario
        """
        try:
            # Buscar trade activo del activo sobreexpuesto
            active_trades = self.db.get_all_active_trades()
            overexposed_trade = None
            overexposed_slot_id = None
            
            for trade in active_trades:
                if trade.get('target_asset') == currency:
                    overexposed_trade = trade
                    overexposed_slot_id = trade.get('slot_id')
                    break
            
            # Obtener balance actual
            balances = self.exchange.fetch_balance()
            total_balance = balances.get('total', {}).get(currency, 0.0)
            
            if total_balance <= 0:
                logger.warning(f"No hay balance de {currency} para reequilibrar")
                return False
            
            # Calcular cantidad a vender (exceso)
            current_value_eur = self.vault.get_asset_value(currency, total_balance, 'EUR')
            if current_value_eur <= 0:
                logger.warning(f"No se puede calcular valor de {currency}")
                return False
            
            excess_percent = (excess_value_eur / current_value_eur) if current_value_eur > 0 else 0
            excess_amount = total_balance * excess_percent
            
            # Asegurar mínimo de 10€
            excess_value_check = self.vault.get_asset_value(currency, excess_amount, 'EUR')
            if excess_value_check < 10.0:
                # Si el exceso es muy pequeño, vender más para llegar a 10€
                min_amount_eur = 10.0
                excess_amount = (min_amount_eur / current_value_eur * total_balance) if current_value_eur > 0 else 0
            
            # Limitar a balance disponible
            excess_amount = min(excess_amount, total_balance)
            
            if excess_amount <= 0:
                logger.warning(f"No se puede calcular cantidad a vender para {currency}")
                return False
            
            logger.info(
                f"🔄 Reequilibrio: Vendiendo {excess_amount:.8f} {currency} "
                f"({excess_value_eur:.2f}€) para reducir exposición del {current_value_eur:.2f}€ total"
            )
            
            # 🎯 ESTRATEGIA DE RE-EQUILIBRIO:
            # 1. Prioridad: Convertir a FIAT (EUR/USDC) para tener capital disponible
            # 2. Si hay oportunidad caliente en radar, convertir directamente a ese activo
            
            # Buscar mejor destino en radar
            destination_result = await self._find_best_destination_from_radar(exclude_assets=[currency])
            
            if destination_result:
                destination_asset, destination_heat_score = destination_result
                logger.info(
                    f"🎯 Reequilibrio hacia oportunidad caliente: {currency} → {destination_asset} "
                    f"(Heat: {destination_heat_score})"
                )
                
                # Usar _find_best_swap_route para encontrar ruta óptima
                best_pair, intermediate, expected_value = await self._find_best_swap_route(
                    currency, destination_asset, excess_amount
                )
                
                if best_pair:
                    try:
                        # Ejecutar swap
                        sell_amount = self.exchange.amount_to_precision(best_pair, excess_amount)
                        order = self.exchange.create_market_sell_order(best_pair, sell_amount)
                        
                        if order and order.get('filled', 0) > 0:
                            filled = order.get('filled', 0)
                            logger.info(
                                f"✅ Exceso intercambiado: {currency} → {destination_asset} "
                                f"usando par {best_pair} (cantidad: {filled:.8f})"
                            )
                            
                            # Registrar en bitácora
                            write_bitacora(
                                f"[🔄 SWAP_DIVERSIFICACIÓN] {currency} → {destination_asset}: "
                                f"{excess_value_eur:.2f}€ vendidos (Heat: {destination_heat_score})"
                            )
                            # Mensaje estandar requerido por auditoría
                            try:
                                write_bitacora(f"DIVERSIFICACIÓN: Vendiendo {excess_value_eur:.2f}€ de {currency} por {destination_asset} debido a sobreexposición")
                            except Exception:
                                pass
                            
                            return True
                    except Exception as e:
                        logger.debug(f"Error en swap directo {currency} → {destination_asset}: {e}")
            
            # Fallback: Vender a FIAT (EUR)
            logger.info(f"💰 Reequilibrio a FIAT: {currency} → EUR")
            
            # Buscar par EUR
            for fiat in self.fiat_assets:
                pair = f"{currency}/{fiat}"
                pair_info = get_pair_info(pair)
                
                if pair_info:
                    try:
                        sell_amount = self.exchange.amount_to_precision(pair, excess_amount)
                        order = self.exchange.create_market_sell_order(pair, sell_amount)
                        
                        if order and order.get('filled', 0) > 0:
                            filled = order.get('filled', 0)
                            filled_value_eur = self.vault.get_asset_value(currency, filled, 'EUR')
                            logger.info(
                                f"✅ Exceso vendido: {filled:.8f} {currency} → {fiat} "
                                f"(valor: {filled_value_eur:.2f}€)"
                            )
                            
                            # Registrar en bitácora
                            write_bitacora(
                                f"[🔄 SWAP_DIVERSIFICACIÓN] {currency} → {fiat}: "
                                f"{filled_value_eur:.2f}€ vendidos para reequilibrio"
                            )
                            
                            return True
                    except Exception as e:
                        logger.debug(f"Error vendiendo {currency} a {fiat}: {e}")
                        continue
            
            logger.warning(f"No se pudo ejecutar reequilibrio de {currency}")
            return False
            
        except Exception as e:
            logger.error(f"Error en reequilibrio de {currency}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    async def execute_swap(self, slot_id: int, trade_id: int, current_trade: Dict[str, Any],
                         new_pair: str, new_target_asset: str) -> bool:
        """Ejecuta un swap: vende el activo actual y compra el nuevo."""
        try:
            # Constante: mínimo de 10€ para operar en Binance
            MIN_ORDER_VALUE_EUR = 10.0
            
            current_asset = current_trade['target_asset']
            current_amount = current_trade['amount']  # Cantidad del trade (puede ser menos que el balance total)
            initial_fiat_value = current_trade['initial_fiat_value']
            
            # Obtener balance total de la moneda en la wallet
            balances = self.exchange.fetch_balance()
            total_balance = balances.get('total', {}).get(current_asset, 0.0)
            
            # Calcular tamaño de orden según nuevas reglas
            swap_amount = self._calculate_swap_order_size(current_asset, total_balance)
            
            if swap_amount <= 0:
                logger.warning(
                    f"Swap rechazado: Tamaño de orden calculado es 0 para {current_asset}. "
                    f"Slot {slot_id}, Trade ID: {trade_id}"
                )
                return False
            
            # Validar que el valor del swap sea >= 10€
            swap_value_eur = self.vault.get_asset_value(current_asset, swap_amount, 'EUR')
            if swap_value_eur < MIN_ORDER_VALUE_EUR:
                logger.warning(
                    f"Swap rechazado: Valor del swap ({swap_value_eur:.2f}€) menor al mínimo de Binance ({MIN_ORDER_VALUE_EUR}€). "
                    f"Slot {slot_id}, Trade ID: {trade_id}"
                )
                return False
            
            logger.info(
                f"[Slot {slot_id}] Calculado tamaño de swap para {current_asset}: "
                f"{swap_amount:.8f} (valor: {swap_value_eur:.2f}€) de {total_balance:.8f} total"
            )
            
            base, quote = new_pair.split("/")
            needed_base = base if base != current_asset else quote
            
            if current_asset == base:
                ticker_buy = self.exchange.fetch_ticker(new_pair)
                buy_amount = self.exchange.amount_to_precision(new_pair, swap_amount)  # Usar swap_amount calculado
                order_buy = self.exchange.create_market_buy_order(new_pair, buy_amount)
                
                final_amount = order_buy.get('filled', 0)
                final_price = order_buy.get('price', ticker_buy['last'])
                
                # ⛽ NIVEL PASIVO (< 5.0%): Si el swap es hacia BNB y el gas < 5%, retener BNB
                if new_target_asset == 'BNB':
                    current_gas_percent = self._get_gas_percentage()
                    if current_gas_percent < 5.0:
                        target_percent = 5.0  # Objetivo: 5%
                        bnb_retained = await self._refill_gas_passive(final_amount, target_percent)
                        if bnb_retained > 0:
                            final_amount = final_amount - bnb_retained
                            logger.info(
                                f"⛽ Gas PASIVO: Retenidos {bnb_retained:.8f} BNB "
                                f"para alcanzar {target_percent}% (actual: {current_gas_percent:.2f}%)"
                            )
                
                # 💰 HUCHA OPORTUNISTA: Si el swap es hacia BTC, detraer 5% antes de asignar al slot
                if self.hucha_enabled and new_target_asset == 'BTC' and final_amount > 0:
                    hucha_total_pct = self.hucha_eur_pct + self.hucha_btc_pct  # Total: 5%
                    hucha_btc_amount = final_amount * (hucha_total_pct / 100.0)
                    
                    if hucha_btc_amount > 0.00000001:  # Mínimo para evitar errores de precisión
                        try:
                            # Calcular valor en EUR para guardar en treasury
                            btc_price_eur = self.vault.get_asset_value('BTC', 1.0, 'EUR')
                            hucha_btc_value_eur = hucha_btc_amount * btc_price_eur
                            hucha_eur_equivalent = hucha_btc_value_eur * (self.hucha_eur_pct / (self.hucha_eur_pct + self.hucha_btc_pct))
                            
                            # Guardar en treasury
                            self.db.add_to_treasury(
                                amount_eur=hucha_eur_equivalent,
                                amount_btc=hucha_btc_amount,
                                description=f"Hucha Oportunista (Tax-on-Exit) - Swap hacia BTC"
                            )
                            
                            # Reducir la cantidad asignada al slot
                            final_amount = final_amount - hucha_btc_amount
                            
                            logger.info(
                                f"💰 Hucha Oportunista aplicada en swap: {hucha_btc_amount:.8f} BTC "
                                f"({hucha_btc_value_eur:.2f} EUR) guardados. "
                                f"Cantidad restante para slot: {final_amount:.8f} BTC"
                            )
                            
                            write_bitacora(
                                f"[💎 HUCHA_SAVE] Hucha oportunista: {hucha_btc_amount:.8f} BTC ({hucha_btc_value_eur:.2f}€) "
                                f"guardados desde swap hacia BTC"
                            )
                        except Exception as e:
                            logger.error(f"Error al aplicar Hucha Oportunista en swap: {e}")
            else:
                # ⚡ OPTIMIZACIÓN: Usar router optimizado para encontrar mejor ruta
                gas_percentage = self._get_gas_percentage()
                route = find_swap_route(
                    from_asset=current_asset,
                    to_asset=needed_base,
                    whitelist=self.strategy["whitelist"],
                    fiat_assets=self.fiat_assets,
                    prefer_low_fees=(gas_percentage >= 2.5)  # Priorizar menos comisiones si hay suficiente gas
                )
                
                if not route:
                    logger.error(
                        f"No se encontró ruta de swap desde {current_asset} "
                        f"hacia {needed_base} (necesario para {new_pair})"
                    )
                    return False
                
                swap_pair, intermediate = route
                
                # Si es ruta directa, usar el par directamente
                if intermediate is None:
                    # Par directo encontrado - ejecutar swap directo
                    ticker_sell = self.exchange.fetch_ticker(swap_pair)
                    sell_amount = self.exchange.amount_to_precision(swap_pair, swap_amount)  # Usar swap_amount calculado
                    order_sell = self.exchange.create_market_sell_order(swap_pair, sell_amount)
                    
                    base_sell, quote_sell = swap_pair.split("/")
                    received_asset = quote_sell if base_sell == current_asset else base_sell
                    received_amount = order_sell.get('filled', 0)
                    
                    # Si recibimos directamente el activo necesario, comprar el nuevo par
                    if received_asset == needed_base:
                        ticker_buy = self.exchange.fetch_ticker(new_pair)
                        buy_amount = self.exchange.amount_to_precision(new_pair, received_amount)
                        order_buy = self.exchange.create_market_buy_order(new_pair, buy_amount)
                        
                        final_amount = order_buy.get('filled', 0)
                        final_price = order_buy.get('price', ticker_buy['last'])
                    else:
                        logger.error(f"Error: Par directo {swap_pair} no resultó en {needed_base}")
                        return False
                else:
                    # Ruta con intermediario: ejecutar dos swaps
                    ticker_sell = self.exchange.fetch_ticker(swap_pair)
                    sell_amount = self.exchange.amount_to_precision(swap_pair, swap_amount)  # Usar swap_amount calculado
                    order_sell = self.exchange.create_market_sell_order(swap_pair, sell_amount)
                    
                    base_sell, quote_sell = swap_pair.split("/")
                    received_asset = quote_sell if base_sell == current_asset else base_sell
                    received_amount = order_sell.get('filled', 0)
                    
                    # Segundo swap: desde intermediate hacia needed_base
                    if received_asset == intermediate:
                        # Buscar el segundo par
                        pair2_candidates = [
                            f"{intermediate}/{needed_base}",
                            f"{needed_base}/{intermediate}"
                        ]
                        swap_pair2 = None
                        for pair2 in pair2_candidates:
                            if get_pair_info(pair2):
                                swap_pair2 = pair2
                                break
                        
                        if not swap_pair2:
                            logger.error(f"No se encontró segundo par desde {intermediate} hacia {needed_base}")
                            return False
                        
                        ticker_buy2 = self.exchange.fetch_ticker(swap_pair2)
                        buy_amount2 = self.exchange.amount_to_precision(swap_pair2, received_amount)
                        order_buy2 = self.exchange.create_market_buy_order(swap_pair2, buy_amount2)
                        
                        base_buy2, quote_buy2 = swap_pair2.split("/")
                        received_asset2 = quote_buy2 if base_buy2 == intermediate else base_buy2
                        received_amount2 = order_buy2.get('filled', 0)
                        
                        if received_asset2 == needed_base:
                            # Ahora comprar el par final
                            ticker_buy = self.exchange.fetch_ticker(new_pair)
                            buy_amount = self.exchange.amount_to_precision(new_pair, received_amount2)
                            order_buy = self.exchange.create_market_buy_order(new_pair, buy_amount)
                            
                            final_amount = order_buy.get('filled', 0)
                            final_price = order_buy.get('price', ticker_buy['last'])
                        else:
                            logger.error(f"Error en segundo swap: recibido {received_asset2}, esperado {needed_base}")
                            return False
                    else:
                        logger.error(f"Error en primer swap: recibido {received_asset}, esperado {intermediate}")
                        return False
                
                # Verificar que tenemos final_amount y final_price definidos
                if 'final_amount' not in locals() or 'final_price' not in locals():
                    logger.error("Error: No se pudo completar el swap")
                    return False
                    
                    # ⛽ GESTIÓN DE GAS POR INERCIA: Mantenimiento Pasivo
                    # Si el swap es hacia BNB y el gas < 5%, retener BNB
                    if new_target_asset == 'BNB':
                        current_gas_percent = self._get_gas_percentage()
                        if current_gas_percent < self.gas_max_target:
                            bnb_retained = await self._refill_gas_passive(final_amount, self.gas_max_target)
                            if bnb_retained > 0:
                                final_amount = final_amount - bnb_retained
                    
                    # 💰 HUCHA OPORTUNISTA: Si el swap es hacia BTC, detraer 5% antes de asignar al slot
                    if self.hucha_enabled and new_target_asset == 'BTC' and final_amount > 0:
                        hucha_total_pct = self.hucha_eur_pct + self.hucha_btc_pct  # Total: 5%
                        hucha_btc_amount = final_amount * (hucha_total_pct / 100.0)
                        
                        if hucha_btc_amount > 0.00000001:  # Mínimo para evitar errores de precisión
                            try:
                                # Calcular valor en EUR para guardar en treasury
                                btc_price_eur = self.vault.get_asset_value('BTC', 1.0, 'EUR')
                                hucha_btc_value_eur = hucha_btc_amount * btc_price_eur
                                hucha_eur_equivalent = hucha_btc_value_eur * (self.hucha_eur_pct / (self.hucha_eur_pct + self.hucha_btc_pct))
                                
                                # Guardar en treasury
                                self.db.add_to_treasury(
                                    amount_eur=hucha_eur_equivalent,
                                    amount_btc=hucha_btc_amount,
                                    description=f"Hucha Oportunista (Tax-on-Exit) - Swap hacia BTC"
                                )
                                
                                # Reducir la cantidad asignada al slot
                                final_amount = final_amount - hucha_btc_amount
                                
                                logger.info(
                                    f"💰 Hucha Oportunista aplicada en swap: {hucha_btc_amount:.8f} BTC "
                                    f"({hucha_btc_value_eur:.2f} EUR) guardados. "
                                    f"Cantidad restante para slot: {final_amount:.8f} BTC"
                                )
                                
                                write_bitacora(
                                    f"[💎 HUCHA_SAVE] Hucha oportunista: {hucha_btc_amount:.8f} BTC ({hucha_btc_value_eur:.2f}€) "
                                    f"guardados desde swap hacia BTC"
                                )
                            except Exception as e:
                                logger.error(f"Error al aplicar Hucha Oportunista en swap: {e}")
                else:
                    logger.warning(
                        f"Swap requiere múltiples pasos: {current_asset} -> {received_asset} -> {needed_base} -> {new_target_asset}"
                    )
                    return False
            
            path_history = current_trade.get('path_history', '') + f" > {new_target_asset}"
            
            self.db.deactivate_trade(trade_id)
            
            # Determinar base_asset para el nuevo trade
            if current_asset == base:
                base_asset_for_new_trade = current_asset
            else:
                base_asset_for_new_trade = received_asset if 'received_asset' in locals() else needed_base
            
            # 🔄 ACTUALIZACIÓN DE ENTRY_PRICE: Tras un salto directo, el entry_price debe ser el precio
            # de mercado del nuevo activo en ese instante, no el precio anterior. Esto permite que
            # el Trailing Stop empiece a contar desde cero.
            # Verificar que final_price sea válido (precio actual del nuevo activo)
            if final_price <= 0:
                # Si no tenemos precio válido, obtener precio de mercado actual
                try:
                    ticker = self.exchange.fetch_ticker(new_pair)
                    final_price = ticker.get('last', ticker.get('ask', 0))
                    if final_price <= 0:
                        logger.warning(
                            f"⚠️ No se pudo obtener precio válido para {new_pair}. "
                            f"Usando precio estimado basado en valor EUR."
                        )
                        final_value_eur = self.vault.get_asset_value(new_target_asset, final_amount, 'EUR')
                        final_price = final_value_eur / final_amount if final_amount > 0 else 0
                except Exception as e:
                    logger.error(f"Error obteniendo precio de mercado para {new_pair}: {e}")
                    # Fallback: calcular precio desde valor EUR
                    final_value_eur = self.vault.get_asset_value(new_target_asset, final_amount, 'EUR')
                    final_price = final_value_eur / final_amount if final_amount > 0 else 0
            
            new_trade_id = self.db.create_trade(
                slot_id=slot_id,
                symbol=new_pair,
                base_asset=base_asset_for_new_trade,
                target_asset=new_target_asset,
                amount=final_amount,
                entry_price=final_price,  # ✅ Precio actual del nuevo activo (resetea trailing stop)
                initial_fiat_value=initial_fiat_value,
                path_history=path_history
            )
            
            logger.info(
                f"✅ Swap exitoso en slot {slot_id}: {current_asset} -> {new_target_asset}. "
                f"Nuevo Trade ID: {new_trade_id}, Entry Price: {final_price:.8f} "
                f"(precio de mercado actual - trailing stop reseteado)"
            )
            return True
        
        except Exception as e:
            logger.error(f"Error al ejecutar swap en slot {slot_id}: {e}")
            return False
    
    def _create_initial_shared_state(self):
        """Crea el archivo state.json con datos básicos al arrancar el bot."""
        try:
            initial_state = {
                'timestamp': datetime.now().isoformat(),
                'market_status': {
                    'status': 'unknown',
                    'message': 'Estado: ⚪ Inicializando...',
                    'color': '#888',
                    'btc_change': None
                },
                'prices': {
                    'btc_price': None,
                    'eth_price': None,
                    'btc_error': True,
                    'eth_error': True
                },
                'balances': {'total': {}},
                'radar_data': [],
                'open_trades': [],
                'total_portfolio_value': 0.0
            }
            
            # Asegurar que el directorio existe
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(initial_state, f, indent=2, default=str)
            
            # Establecer permisos: 664 (rw-rw-r--) para que motor y dashboard puedan leer/escribir
            # Esto evita problemas si el motor se ejecuta con sudo y el dashboard sin él
            try:
                self.state_path.chmod(0o664)
            except Exception as e:
                logger.debug(f"No se pudieron establecer permisos en state.json: {e}")
            
            logger.info(f"Estado inicial creado en {self.state_path}")
        except Exception as e:
            logger.error(f"Error al crear estado inicial: {e}")
    
    async def _evaluate_currency_signal_for_radar(self, currency: str) -> Dict[str, Any]:
        """Evalúa las señales técnicas de una moneda para el radar."""
        result = {
            'currency': currency,
            'rsi': None,
            'ema200_distance': None,
            'volume_status': None,
            'triple_green': False,
            'conditions_met': 0,
            'missing_condition': None,
            'heat_score': 0,
            'buy_the_dip': False
        }
        
        if currency in ['EUR', 'USDC']:
            return result
        
        try:
            pair = None
            for base in ['EUR', 'USDC']:
                candidate_pairs = get_available_pairs(base)
                for p in candidate_pairs:
                    if currency in p:
                        pair = p
                        break
                if pair:
                    break
            
            if not pair:
                return result
            
            try:
                import signals
                if hasattr(signals, 'get_technical_indicators'):
                    indicators = signals.get_technical_indicators(pair, self.exchange)
                    result['rsi'] = indicators.get('rsi')
                    ema_dist = indicators.get('ema200_distance')
                    if ema_dist is not None:
                        result['ema200_distance'] = ema_dist
                    else:
                        result['ema200_distance'] = None
                    result['volume_status'] = indicators.get('volume_status')
                elif hasattr(signals, 'evaluate_signal'):
                    signal_data = signals.evaluate_signal(pair, self.exchange)
                    if signal_data:
                        result['rsi'] = signal_data.get('rsi')
                        ema_dist = signal_data.get('ema200_distance')
                        if ema_dist is not None:
                            result['ema200_distance'] = ema_dist
                        else:
                            result['ema200_distance'] = None
                        result['volume_status'] = signal_data.get('volume_status')
                        result['triple_green'] = signal_data.get('triple_green', False)
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"Error al obtener señales para {currency}: {e}")
                result['ema200_distance'] = None
            
            if result['rsi'] is None:
                pair_info = get_pair_info(pair)
                if pair_info:
                    price_change = pair_info.get('price_change_percent', 0)
                    result['rsi'] = 50 - (price_change * 2)
            
            if result['volume_status'] is None:
                result['volume_status'] = 'medium'
            
            rsi_threshold = self.strategy["indicators"].get("rsi_radar_threshold", 48)
            ema_traditional = self.strategy["indicators"].get("ema200_traditional_threshold", -2.0)
            ema_buy_dip = self.strategy["indicators"].get("ema200_buy_dip_threshold", 0.0)
            
            rsi_ok = result['rsi'] < rsi_threshold if result['rsi'] is not None else False
            ema_ok = False
            if result['ema200_distance'] is not None:
                ema_ok = result['ema200_distance'] < ema_traditional or result['ema200_distance'] > ema_buy_dip
            volume_ok = result['volume_status'] == 'high' if result['volume_status'] else False
            
            result['conditions_met'] = sum([rsi_ok, ema_ok, volume_ok])
            result['triple_green'] = result['conditions_met'] == 3
            # Calcular heat_score usando la función completa (se recalcula después)
            result['heat_score'] = (result['conditions_met'] * 33) + (10 if result['triple_green'] else 0)
            
        except Exception as e:
            logger.debug(f"Error al evaluar señal para {currency}: {e}")
        
        return result
    
    def _get_radar_zone(self, heat_score: int) -> str:
        """Determina la zona del radar según el heat_score."""
        if heat_score > 85:
            return 'muy_caliente'
        elif heat_score >= 70:
            return 'caliente'
        elif heat_score >= 40:
            return 'fria'
        else:
            return 'muy_fria'
    
    async def _update_radar_zone(self, zone: str, currencies: List[str]):
        """
        Actualiza el radar para una zona específica de monedas.
        
        Args:
            zone: Zona del radar ('muy_caliente', 'caliente', 'fria', 'muy_fria')
            currencies: Lista de monedas a actualizar en esta zona
        """
        frequency = self.radar_frequencies.get(zone, 60)
        zone_name_display = {
            'muy_caliente': 'Muy Caliente',
            'caliente': 'Caliente',
            'fria': 'Fría',
            'muy_fria': 'Muy Fría'
        }.get(zone, zone)
        
        while self.running:
            try:
                updated_count = 0
                for currency in currencies:
                    if not self.running:
                        break
                    
                    try:
                        # Evaluar señal de la moneda
                        signal_data = await self._evaluate_currency_signal_for_radar(currency)
                        heat_score = signal_data.get('heat_score', 0)
                        
                        # Recalcular heat_score usando la función completa
                        heat_score = await self._calculate_heat_score(signal_data)
                        signal_data['heat_score'] = heat_score
                        
                        # Recortar historiales y actualizar cache
                        try:
                            signal_data = self._trim_price_history(signal_data)
                        except Exception:
                            pass
                        self.radar_data_cache[currency] = signal_data
                        self.radar_last_update[currency] = time.time()
                        updated_count += 1
                        
                        logger.debug(f"Radar [{zone_name_display}]: {currency} actualizado (heat: {heat_score})")

                        # Si la moneda cumple criterios de persecución (heat alto o slot activo),
                        # lanzar tarea per-pair para polling más frecuente (5s) sin bloquear la zona.
                        try:
                            active_assets = self._get_active_assets()
                        except Exception:
                            active_assets = []

                        try:
                            if (heat_score >= 90 or currency in active_assets) and currency not in self.persecution_tasks:
                                # Crear tarea de persecución concurrente
                                task = asyncio.create_task(self._persecute_currency(currency))
                                self.persecution_tasks[currency] = task
                                logger.info(f"MODE: PERSECUCIÓN activada para {currency} (heat: {heat_score})")
                        except Exception as e:
                            logger.debug(f"Error iniciando persecución para {currency}: {e}")
                        
                        # Pequeño delay entre monedas para no saturar la API
                        await asyncio.sleep(0.1)
                    except Exception as e:
                        logger.debug(f"Error actualizando {currency} en zona {zone}: {e}")
                        continue
                
                if updated_count > 0:
                    # Guardar radar actualizado
                    await self._save_radar_data()
                    logger.debug(f"Radar [{zone_name_display}]: {updated_count} monedas actualizadas")
                
                # Esperar según la frecuencia de la zona
                await asyncio.sleep(frequency)
                
            except asyncio.CancelledError:
                logger.info(f"Tarea de radar zona {zone} cancelada")
                break
            except Exception as e:
                logger.error(f"Error en actualización de radar zona {zone}: {e}")
                await asyncio.sleep(frequency)
    
    async def _save_radar_data(self):
        """Guarda los datos del radar en shared/radar.json con control de frecuencia."""
        try:
            # Control de frecuencia: solo guardar cada 30 segundos para reducir I/O
            current_time = time.time()
            if current_time - self.radar_last_save_time < self.radar_save_interval:
                self.radar_pending_save = True  # Marcar que hay cambios pendientes
                return  # Saltar guardado si no ha pasado el intervalo
            
            # Resetear flags
            self.radar_last_save_time = current_time
            self.radar_pending_save = False
            
            # Convertir cache a lista y ordenar por heat_score
            radar_list = []
            for currency, data in self.radar_data_cache.items():
                radar_list.append(data)
            
            # Ordenar por heat_score descendente
            radar_list.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
            
            # Añadir información de zona y última actualización
            for item in radar_list:
                heat_score = item.get('heat_score', 0)
                item['zone'] = self._get_radar_zone(heat_score)
                currency = item.get('currency', '')
                if currency in self.radar_last_update:
                    item['last_update'] = datetime.fromtimestamp(
                        self.radar_last_update[currency]
                    ).isoformat()
                # Indicar si la moneda tiene una tarea de persecución activa
                try:
                    item['in_persecution'] = currency in getattr(self, 'persecution_tasks', {})
                except Exception:
                    item['in_persecution'] = False
            
            radar_data = {
                'timestamp': datetime.now().isoformat(),
                'radar_data': radar_list,
                'zones': {
                    'muy_caliente': {
                        'threshold': '>85',
                        'frequency': self.radar_frequencies['muy_caliente'],
                        'color': '#00FF88'  # Verde Neón
                    },
                    'caliente': {
                        'threshold': '70-85',
                        'frequency': self.radar_frequencies['caliente'],
                        'color': '#00CC66'  # Verde Esmeralda
                    },
                    'fria': {
                        'threshold': '40-69',
                        'frequency': self.radar_frequencies['fria'],
                        'color': '#888888'  # Estándar
                    },
                    'muy_fria': {
                        'threshold': '<40',
                        'frequency': self.radar_frequencies['muy_fria'],
                        'color': '#444444'  # Atenuado
                    }
                }
            }

            # Añadir flag in_persecution si existe
            try:
                for it in radar_list:
                    cur = it.get('currency')
                    it['in_persecution'] = cur in getattr(self, 'persecution_tasks', {})
            except Exception:
                pass
            
            # Limpiar cache en memoria si se ha vuelto demasiado grande
            try:
                MAX_CACHE_ENTRIES = 1000
                if isinstance(self.radar_data_cache, dict) and len(self.radar_data_cache) > MAX_CACHE_ENTRIES:
                    # Ordenar por última actualización (desc) y mantener las más recientes
                    items = sorted(
                        [(k, self.radar_last_update.get(k, 0)) for k in self.radar_data_cache.keys()],
                        key=lambda x: x[1],
                        reverse=True
                    )
                    keep_keys = set([k for k, _ in items[:MAX_CACHE_ENTRIES]])
                    for k in list(self.radar_data_cache.keys()):
                        if k not in keep_keys:
                            try:
                                del self.radar_data_cache[k]
                            except Exception:
                                pass
                    for k in list(self.radar_last_update.keys()):
                        if k not in keep_keys:
                            try:
                                del self.radar_last_update[k]
                            except Exception:
                                pass
            except Exception:
                pass

            # Guardar usando file locking si está disponible
            if HAS_FILE_UTILS:
                write_json_safe(self.radar_path, radar_data)
            else:
                # Fallback: escritura estándar
                self.radar_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.radar_path, 'w', encoding='utf-8') as f:
                    json.dump(radar_data, f, indent=2, default=str)
                try:
                    self.radar_path.chmod(0o664)
                except:
                    pass

            # Guardar también en SQLite (market_data)
            try:
                if 'save_market_data' in globals():
                    save_market_data(radar_list, ts=int(current_time))
                    # Bypass de emergencia: exportar CSV en paralelo
                    try:
                        import pandas as _pd
                        df_radar = _pd.DataFrame(radar_list)
                        if not df_radar.empty:
                            emergency_csv = ROOT_DIR / 'shared' / 'radar_emergency.csv'
                            df_radar.to_csv(emergency_csv, index=False)
                    except Exception as _csv_err:
                        logger.debug(f"No se pudo exportar radar_emergency.csv: {_csv_err}")
            except Exception as db_err:
                logger.debug(f"No se pudo guardar market_data en SQLite: {db_err}")
            
        except Exception as e:
            logger.error(f"Error guardando radar.json: {e}")

    async def _persecute_currency(self, currency: str):
        """
        Tarea per-pair: actualiza la `currency` con mayor frecuencia (5s)
        mientras cumpla el criterio de persecución (heat>=90 o slot activo).
        """
        try:
            LOG_TAG = f"Persecución:{currency}"
            while self.running:
                try:
                    # Evaluar señal y heat
                    signal_data = await self._evaluate_currency_signal_for_radar(currency)
                    heat_score = signal_data.get('heat_score', 0)
                    heat_score = await self._calculate_heat_score(signal_data)
                    signal_data['heat_score'] = heat_score

                    # Trim historiales y actualizar cache
                    try:
                        signal_data = self._trim_price_history(signal_data)
                    except Exception:
                        pass
                    self.radar_data_cache[currency] = signal_data
                    self.radar_last_update[currency] = time.time()

                    # Verificar condición de salida: si ya no cumple persecución, terminar
                    try:
                        active_assets = self._get_active_assets()
                    except Exception:
                        active_assets = []

                    if not (heat_score >= 90 or currency in active_assets):
                        logger.info(f"MODE: CRUCERO reanudado para {currency} (heat: {heat_score})")
                        break

                    # Esperar periodo de persecución (5s)
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    logger.info(f"Tarea de persecución cancelada para {currency}")
                    break
                except Exception as e:
                    logger.debug(f"{LOG_TAG} Error intern|o: {e}")
                    await asyncio.sleep(5)
        finally:
            try:
                if currency in self.persecution_tasks:
                    del self.persecution_tasks[currency]
            except Exception:
                pass
    
    async def _get_wallet_currencies_for_radar(self) -> List[str]:
        """
        Obtiene las monedas de la wallet que tienen un saldo OPERABLE > 10€ para el radar.
        Saldo Operable = Saldo Total - Saldo en Hucha - BNB (reservado para gas)
        
        Este es el nuevo enfoque: radar basado en inventario, solo monedas operables.
        
        Returns:
            Lista de monedas (símbolos) con saldo operable > 10€
        """
        try:
            if not self.exchange:
                return []
            
            balances = self.exchange.fetch_balance()
            if not balances or 'total' not in balances:
                return []
            
            wallet_currencies = []
            # 🔒 FILTRO DE FANTASMAS: Solo usar saldo 'free', no 'frozen' o 'locked' (staking, etc.)
            # Binance puede tener activos en staking que aparecen en 'total' pero no en 'free'
            free_balances = balances.get('free', {})
            total_balances = balances.get('total', {})
            
            # Usar free_balances como fuente de verdad para evitar activos congelados
            # Si un activo no está en 'free', no está disponible para trading
            
            # Obtener saldos en hucha para calcular saldo operable
            hucha_amounts = self._get_hucha_amount_per_currency()
            
            # Filtrar monedas con saldo OPERABLE > 10€
            MIN_VALUE_EUR = 10.0
            
            for currency, total_amount in total_balances.items():
                # 🔒 FILTRO DE FANTASMAS: Solo procesar activos con saldo 'free' > 0
                # Ignorar activos que están frozen, locked o en staking
                free_amount = free_balances.get(currency, 0.0)
                if free_amount <= 0:
                    continue  # Activo no disponible (puede estar en staking, frozen, etc.)
                
                if total_amount <= 0:
                    continue
                
                # Ignorar EUR, USDC (ya están en fiat)
                if currency in ['EUR', 'USDC']:
                    continue
                
                # Ignorar BNB (reservado para gas, no operable)
                if currency == 'BNB':
                    continue
                
                try:
                    # Calcular saldo operable (excluyendo hucha)
                    # Usar free_amount en lugar de total_amount para evitar activos congelados
                    hucha_amount = hucha_amounts.get(currency, 0.0)
                    operable_amount = max(0.0, free_amount - hucha_amount)
                    
                    if operable_amount <= 0:
                        continue
                    
                    # Calcular valor en EUR del saldo operable
                    value_eur = 0.0
                    
                    # Intentar par directo con EUR
                    try:
                        pair_info = get_pair_info(f"{currency}/EUR")
                        if pair_info:
                            price_eur = pair_info.get('last_price', 0)
                            value_eur = operable_amount * price_eur
                    except:
                        pass
                    
                    # Si no hay par EUR, intentar USD y convertir (1 USD ≈ 0.91 EUR)
                    if value_eur == 0:
                        try:
                            pair_info = get_pair_info(f"{currency}/USD")
                            if pair_info:
                                price_usd = pair_info.get('last_price', 0)
                                value_usd = operable_amount * price_usd
                                value_eur = value_usd * 0.91  # Aproximación USD -> EUR
                        except:
                            pass
                    
                    # Si el valor OPERABLE es > 10€, incluir en el radar
                    if value_eur > MIN_VALUE_EUR:
                        wallet_currencies.append(currency)
                        logger.debug(
                            f"Moneda operable añadida al radar: {currency} "
                            f"(saldo operable: {operable_amount:.8f}, valor: {value_eur:.2f}€)"
                        )
                
                except Exception as e:
                    logger.debug(f"Error calculando valor operable de {currency} para radar: {e}")
                    continue
            
            logger.info(
                f"Radar de Inventario: {len(wallet_currencies)} monedas operables encontradas "
                f"con saldo > {MIN_VALUE_EUR}€"
            )
            return wallet_currencies
            
        except Exception as e:
            logger.error(f"Error obteniendo monedas operables de wallet para radar: {e}")
            return []
    
    async def _generate_swap_pairs_for_radar(self, origin_currency: str) -> List[Dict[str, Any]]:
        """
        Genera pares de intercambio (ORIGEN/DESTINO) para una moneda de origen.
        
        Args:
            origin_currency: Moneda que poseo en la wallet (origen del swap)
        
        Returns:
            Lista de diccionarios con información de pares de intercambio
        """
        try:
            swap_pairs = []
            
            # Obtener pares disponibles desde la moneda de origen
            available_pairs = get_available_pairs(origin_currency)
            
            if not available_pairs:
                return []
            
            # Obtener whitelist para filtrar destinos válidos
            whitelist = self.strategy.get("whitelist", [])
            
            for pair in available_pairs:
                base, quote = pair.split("/")
                
                # Determinar moneda de destino
                if base == origin_currency:
                    dest_currency = quote
                elif quote == origin_currency:
                    dest_currency = base
                else:
                    continue  # Este par no incluye nuestra moneda de origen
                
                # Filtrar por whitelist (si está configurada)
                if whitelist and dest_currency not in whitelist:
                    continue
                
                # Ignorar destinos que no tienen sentido (EUR, USDC como destino de swap)
                if dest_currency in ['EUR', 'USDC']:
                    continue
                
                # Ignorar BNB como destino (reservado para gas)
                if dest_currency == 'BNB':
                    continue
                
                # Verificar que el par existe en Binance
                pair_info = get_pair_info(pair)
                if not pair_info:
                    continue
                
                swap_pairs.append({
                    'pair': pair,
                    'origin': origin_currency,
                    'destination': dest_currency,
                    'pair_info': pair_info
                })
            
            return swap_pairs
            
        except Exception as e:
            logger.error(f"Error generando pares de intercambio para {origin_currency}: {e}")
            return []
    
    async def _evaluate_swap_opportunity(self, origin_currency: str, dest_currency: str, pair: str) -> Optional[Dict[str, Any]]:
        """
        Evalúa la oportunidad de un swap desde origin_currency hacia dest_currency.
        
        Args:
            origin_currency: Moneda que poseo (origen)
            dest_currency: Moneda de destino (oportunidad)
            pair: Par de intercambio (ej: "XRP/BTC")
        
        Returns:
            Diccionario con información de la oportunidad de swap, o None si no es válida
        """
        try:
            # Evaluar señal del par de destino
            signal_data = await self._evaluate_signal(pair)
            
            # RELAJADO: Permitir pares incluso sin signal_data para diagnóstico
            # Antes: if not signal_data: return None
            # Ahora: Crear signal_data mínima si está vacía
            if not signal_data:
                signal_data = {
                    'pair': pair,
                    'rsi': None,
                    'ema200_distance': None,
                    'volume_status': 'normal',
                    'triple_green': False,
                    'profit_potential': 0
                }
            
            # Calcular heat score del destino
            dest_heat_score = await self._calculate_heat_score(signal_data)
            
            # Obtener información del par
            pair_info = get_pair_info(pair)
            if not pair_info:
                return None
            
            # Calcular oportunidad de mejora (comparar destino vs origen)
            # Para esto, necesitamos evaluar también la señal del origen
            origin_signal = None
            origin_heat_score = 0
            
            # Buscar un par que incluya el origen para evaluar su estado actual
            origin_pairs = get_available_pairs(origin_currency)
            for origin_pair in origin_pairs:
                if origin_currency in origin_pair:
                    origin_signal = await self._evaluate_signal(origin_pair)
                    if origin_signal:
                        origin_heat_score = await self._calculate_heat_score(origin_signal)
                        break
            
            # Calcular mejora potencial
            improvement_score = dest_heat_score - origin_heat_score
            improvement_percent = improvement_score  # El heat score ya es un porcentaje aproximado
            
            # INYECTAR TICKER COMPLETO DE BINANCE para obtener datos precisos
            ticker = None
            try:
                # BYPASS AGRESIVO: Ir directamente a OHLCV si ticker no existe
                ticker = self.exchange.fetch_ticker(pair)  # fetch_ticker es SYNC, no async
            except Exception as e:
                logger.debug(f"❌ {pair}: fetch_ticker falló ({type(e).__name__}), usando OHLCV")
                ticker = None  # Forzar fallback inmediato
                # Intentar par inverso automáticamente (ej: XRP/MATIC → MATIC/XRP)
                try:
                    if '/' in pair:
                        base, quote = pair.split('/')
                        inverse_pair = f"{quote}/{base}"
                        ticker = self.exchange.fetch_ticker(inverse_pair)
                        logger.info(f"✅ {pair}: Fallback inverso usando {inverse_pair}")
                except Exception as inv_err:
                    logger.debug(f"Fallback inverso también falló para {pair}: {inv_err}")
            
            # Obtener precio actual del par
            current_price = pair_info.get('last_price', 0)
            if ticker:
                current_price = ticker.get('last') or ticker.get('close') or current_price
            
            # Obtener cambio 24h desde ticker (prioridad 1: percentage, 2: change, 3: calcular, 4: OHLCV)
            price_change_24h = 0.0
            if ticker:
                # Prioridad 1: ticker['percentage'] (ya viene calculado)
                price_change_24h = ticker.get('percentage')
                
                # Prioridad 2: ticker['change'] (diferencia absoluta, necesita conversión)
                if price_change_24h is None:
                    price_change_24h = ticker.get('change')
                
                # Prioridad 3: Calcular manualmente desde last y open
                if price_change_24h is None:
                    last_price = ticker.get('last') or ticker.get('close')
                    open_price = ticker.get('open') or ticker.get('previousClose')
                    if last_price and open_price and open_price > 0:
                        price_change_24h = ((last_price - open_price) / open_price) * 100
                        logger.debug(
                            f"📊 {pair}: ticker.percentage=None, calculado manualmente: "
                            f"{price_change_24h:.2f}% (last={last_price}, open={open_price})"
                        )
                    else:
                        price_change_24h = 0.0
                        logger.debug(f"⚠️ {pair}: No se pudo calcular percentage (last={last_price}, open={open_price})")
            else:
                # FALLBACK AGRESIVO: Usar OHLCV para precio y cambio 24h
                logger.info(f"🔄 {pair}: Sin ticker, usando OHLCV fallback...")
                try:
                    ohlcv_24h = self.exchange.fetch_ohlcv(pair, timeframe='1h', limit=25)
                    if ohlcv_24h and len(ohlcv_24h) >= 2:
                        price_24h_ago = ohlcv_24h[0][4]  # Close de hace 24h
                        current_price = ohlcv_24h[-1][4]  # Close actual
                        if price_24h_ago > 0:
                            price_change_24h = ((current_price - price_24h_ago) / price_24h_ago) * 100
                            logger.info(f"✅ {pair}: OHLCV 24h: {price_change_24h:+.2f}% (precio: {current_price:.8f})")
                except Exception as ohlcv_error:
                    logger.warning(f"❌ {pair}: OHLCV fallback falló: {ohlcv_error}")
            
            # VOLUMEN: Extraer de ticker o OHLCV
            quote_volume_raw = 0.0
            if ticker:
                quote_volume_raw = float(ticker.get('quoteVolume', 0) or ticker.get('baseVolume', 0) or 0)
                if quote_volume_raw == 0.0:
                    logger.debug(f"⚠️ {pair}: ticker.quoteVolume=0.0, intentando OHLCV volumen...")
            
            # FALLBACK DE VOLUMEN: Si ticker no tiene volumen, usar última vela de OHLCV
            if quote_volume_raw == 0.0:
                try:
                    ohlcv_1h = self.exchange.fetch_ohlcv(pair, timeframe='1h', limit=1)
                    if ohlcv_1h and len(ohlcv_1h) > 0:
                        quote_volume_raw = float(ohlcv_1h[-1][5])  # Volumen de última vela 1h
                        logger.info(f"📊 {pair}: Volumen desde OHLCV: {quote_volume_raw:.8f}")
                except Exception as vol_error:
                    logger.debug(f"⚠️ {pair}: No se pudo obtener volumen de OHLCV: {vol_error}")
            
            # Calcular volume_change_24h (movido desde abajo para consolidar lógica)
            volume_change_24h = 0.0
            try:
                prev_vol = self.last_volumes.get(pair)
                if isinstance(prev_vol, (int, float)) and prev_vol and prev_vol > 0 and quote_volume_raw and quote_volume_raw > 0:
                    prev_based_pct = ((quote_volume_raw - float(prev_vol)) / float(prev_vol)) * 100.0
                    volume_change_24h = round(prev_based_pct, 4)  # 4 decimales de precisión
                    
                    # INYECCIÓN DE RUIDO TÉCNICO: Si vol_pct == 0.0 exactamente, añadir 0.0001% para "respirar"
                    if volume_change_24h == 0.0 and prev_vol > 0 and quote_volume_raw > 0:
                        volume_change_24h = 0.0001  # Micro-variación para romper el cero
                        logger.debug(f"🔬 {pair}: vol_pct era 0.0%, inyectado ruido técnico: +0.0001%")
                    
                    # Forzar mínimo visible si cambio muy pequeño
                    if abs(volume_change_24h) < 0.001 and volume_change_24h != 0:
                        volume_change_24h = 0.001 if volume_change_24h > 0 else -0.001
                
                # Actualizar cache para siguiente ciclo
                self.last_volumes[pair] = quote_volume_raw
            except Exception as vol_calc_error:
                logger.debug(f"⚠️ {pair}: Error calculando vol_pct: {vol_calc_error}")
                try:
                    self.last_volumes[pair] = quote_volume_raw
                except Exception:
                    pass
            
            # PERSISTENCIA FORZADA: Escribir last_volumes.json SIEMPRE tras cada par
            try:
                if HAS_FILE_UTILS:
                    write_json_safe(self.last_volumes_path, self.last_volumes)
                else:
                    with open(self.last_volumes_path, 'w', encoding='utf-8') as f:
                        json.dump(self.last_volumes, f, ensure_ascii=False)
            except Exception as e:
                logger.debug(f"Error guardando last_volumes: {e}")
            
            # Log de depuración solo por consola (no guardar en archivo)
            logger.debug(f"Procesando {pair} - Vol: {quote_volume_raw:.2f} ({volume_change_24h:+.4f}%) - 24h: {price_change_24h:+.2f}%")
            

            # DEBUG: Verificar que ticker tenga percentage
            if ticker:
                ticker_pct = ticker.get('percentage')
                if ticker_pct is None or ticker_pct == 0:
                    logger.debug(
                        f"⚠️  {pair}: ticker.percentage={ticker_pct} | "
                        f"usando price_change_24h={price_change_24h}%"
                    )
            
            # Forzar 0.0 si price_change_24h es None para evitar errores en float()
            if price_change_24h is None:
                price_change_24h = 0.0
                logger.debug(f"⚠️ {pair}: price_change_24h era None, forzado a 0.0")
            
            # Forzar 0.0 si volume_change_24h es None
            if volume_change_24h is None:
                volume_change_24h = 0.0
            
            return {
                'pair': pair,
                'origin': origin_currency,
                'destination': dest_currency,
                'heat_score': dest_heat_score,
                'origin_heat_score': origin_heat_score,
                'improvement_score': improvement_score,
                'improvement_percent': improvement_percent,
                'rsi': signal_data.get('rsi'),
                'ema200_distance': signal_data.get('ema200_distance'),
                'volume_status': signal_data.get('volume_status', 'N/A'),
                'volume_change_24h': volume_change_24h,
                # CLAVES FORZADAS PARA DASHBOARD (nombres cortos)
                '24h': float(price_change_24h),  # Cambio 24h desde ticker
                'vol': float(quote_volume_raw),  # Volumen bruto desde ticker
                'vol_pct': float(volume_change_24h),  # Cambio porcentual de volumen
                # Mantener claves antiguas para compatibilidad
                'change_24h': float(price_change_24h),
                'volume_change': float(volume_change_24h),
                'quote_volume': quote_volume_raw,
                'triple_green': signal_data.get('triple_green', False),
                'current_price': current_price,
                'price_change_24h': price_change_24h,
                'priceChangePercent': price_change_24h,
                'profit_potential': signal_data.get('profit_potential', 0)
            }
            
        except Exception as e:
            logger.debug(f"Error evaluando oportunidad de swap {origin_currency} -> {dest_currency}: {e}")
            return None

    async def _scan_whitelist_against_base(self, base_asset: str = 'XRP'):
        """Asegura que el radar incluya entradas para todos los activos de la whitelist comparados contra `base_asset`.
        
        Versión RÁPIDA: usa solo datos de caché (get_pair_info) sin hacer nuevas API calls.
        """
        try:
            whitelist = self.strategy.get('whitelist', [])
            if not whitelist:
                return

            entries_added = 0
            for target in whitelist:
                try:
                    if target == base_asset or target in ['EUR', 'USDC', 'BNB']:
                        continue

                    # Intentar encontrar par en caché
                    pair_found = None
                    pair_info = None
                    
                    # 1. Intentar pares directos
                    for p in [f"{base_asset}/{target}", f"{target}/{base_asset}"]:
                        info = get_pair_info(p)
                        if info and info.get('last_price'):
                            pair_found = p
                            pair_info = info
                            break
                    
                    # 2. Si no hay par directo, usar par vs USDT para datos técnicos
                    if not pair_found:
                        usdt_pair = f"{target}/USDT"
                        info = get_pair_info(usdt_pair)
                        if info and info.get('last_price'):
                            pair_found = usdt_pair
                            pair_info = info
                    
                    # 3. Si tampoco hay USDT, usar EUR
                    if not pair_found:
                        eur_pair = f"{target}/EUR"
                        info = get_pair_info(eur_pair)
                        if info and info.get('last_price'):
                            pair_found = eur_pair
                            pair_info = info
                    
                    # Si encontramos algún par, crear entrada con datos de caché
                    if pair_found and pair_info:
                        # Calcular proxy RSI basado en cambio 24h
                        change_24h = pair_info.get('price_change_percent', 0) or 0
                        proxy_rsi = max(1.0, min(99.0, 50.0 + (change_24h * 2)))  # Heurística simple
                        
                        # Heat score básico basado en tendencia
                        heat_proxy = 0
                        if change_24h > 5:
                            heat_proxy = min(100, 50 + change_24h * 5)
                        elif change_24h > 0:
                            heat_proxy = 40
                        elif change_24h > -5:
                            heat_proxy = 20
                        else:
                            heat_proxy = 0
                        
                        key = f"{base_asset}/{target}"
                        entry = {
                            'pair': pair_found,
                            'origin': base_asset,
                            'destination': target,
                            'swap_label': f"{base_asset} → {target}",
                            'heat_score': heat_proxy,
                            'rsi': proxy_rsi,
                            'ema200_distance': 0.0,
                            'volume_status': 'normal',
                            'triple_green': False,
                            'current_price': pair_info.get('last_price', 0),
                            'price_change_24h': change_24h,
                            '24h': float(change_24h),
                            'vol': float(pair_info.get('quote_volume', 0) or 0),
                            'vol_pct': 0.0,
                            'profit_potential': abs(change_24h),
                            'note': f"proxy_from_{pair_found}" if '/' in pair_found and base_asset not in pair_found else 'direct'
                        }
                        self.radar_data_cache[key] = entry
                        self.radar_last_update[key] = time.time()
                        entries_added += 1
                        await asyncio.sleep(0.001)  # Yield control mínimo
                    
                except Exception as e:
                    logger.warning(f"Error procesando {target} en whitelist scan: {e}")
                    continue
            
            logger.info(f"✅ Whitelist scan completado: {entries_added} pares actualizados (usando caché)")
            
        except Exception as e:
            logger.error(f"Error en _scan_whitelist_against_base: {e}", exc_info=True)

    async def _classify_whitelist_by_heat(self) -> Dict[str, List[str]]:
        """Clasifica la whitelist en 3 niveles de prioridad según heat_score almacenado en SQLite.
        
        Returns:
            Dict con keys 'hot' (Top 10), 'warm' (11-20), 'cold' (resto)
        """
        try:
            from storage import get_latest_market_data
            whitelist = self.strategy.get('whitelist', [])
            
            # Obtener heat_score de todos los activos desde SQLite
            db_entries = get_latest_market_data(limit=200)
            heat_map = {}  # destination -> heat_score
            
            for entry in db_entries:
                dest = entry.get('destination')
                heat = entry.get('heat_score', 0) or 0
                if dest and dest in whitelist:
                    # Mantener el heat más alto si hay múltiples pares para el mismo activo
                    if dest not in heat_map or heat > heat_map[dest]:
                        heat_map[dest] = heat
            
            # Ordenar por heat_score descendente
            sorted_assets = sorted(heat_map.items(), key=lambda x: x[1], reverse=True)
            
            # Clasificar en niveles
            hot = [asset for asset, _ in sorted_assets[:10]]  # Top 10
            warm = [asset for asset, _ in sorted_assets[10:20]]  # Posiciones 11-20
            cold_candidates = [asset for asset, _ in sorted_assets[20:]]  # Resto con heat conocido
            
            # Añadir activos de whitelist sin datos al nivel frío
            for asset in whitelist:
                if asset not in heat_map and asset not in ['EUR', 'USDC', 'BNB']:
                    cold_candidates.append(asset)
            
            result = {
                'hot': hot,
                'warm': warm,
                'cold': cold_candidates
            }
            
            logger.debug(f"🔥 Clasificación: Hot={len(hot)}, Warm={len(warm)}, Cold={len(cold_candidates)}")
            return result
            
        except Exception as e:
            logger.debug(f"Error clasificando whitelist: {e}")
            # Fallback: toda la whitelist va al nivel hot
            whitelist = self.strategy.get('whitelist', [])
            return {'hot': whitelist, 'warm': [], 'cold': []}

    async def _scan_whitelist_multi_bases(self, bases: List[str] = None, target_assets: List[str] = None) -> int:
        """Escanea un subset de la whitelist contra múltiples bases (USDT, BTC, ETH).

        - Usa get_pair_info para evitar llamadas pesadas (aprovecha el cache/ticker).
        - Construye entradas con proxy RSI y heat basados en change_24h.
        - Devuelve el número de activos distintos actualizados.
        
        Args:
            bases: Lista de bases a usar (default: ['USDT', 'BTC', 'ETH'])
            target_assets: Subset de whitelist a escanear (default: toda la whitelist)
        """
        try:
            if bases is None:
                bases = ['USDT', 'BTC', 'ETH']

            # Si no se especifica subset, usar toda la whitelist
            if target_assets is None:
                target_assets = self.strategy.get('whitelist', [])
            
            if not target_assets:
                return 0

            updated_destinations: set = set()
            for target in target_assets:
                try:
                    # Saltar activos que no aportan al radar
                    if target in ['EUR', 'USDC', 'BNB']:
                        continue

                    # Buscar el par más líquido en orden de preferencia
                    pair_found = None
                    pair_info = None
                    base_used = None

                    for base in bases:
                        candidate = f"{target}/{base}"
                        info = get_pair_info(candidate)
                        if info and info.get('last_price'):
                            pair_found = candidate
                            pair_info = info
                            base_used = base
                            break

                    # Si encontramos algún par válido, construir entrada
                    if pair_found and pair_info and base_used:
                        change_24h = float(pair_info.get('price_change_percent', 0) or 0)
                        proxy_rsi = max(1.0, min(99.0, 50.0 + (change_24h * 2)))

                        # Heat simple por tendencia (mismo esquema que la versión rápida)
                        if change_24h > 5:
                            heat_proxy = min(100, 50 + change_24h * 5)
                        elif change_24h > 0:
                            heat_proxy = 40
                        elif change_24h > -5:
                            heat_proxy = 20
                        else:
                            heat_proxy = 0

                        key = f"{base_used}/{target}"
                        entry = {
                            'pair': pair_found,
                            'origin': base_used,
                            'destination': target,
                            'swap_label': f"{base_used} → {target}",
                            'heat_score': int(heat_proxy),
                            'rsi': float(proxy_rsi),
                            'ema200_distance': 0.0,
                            'volume_status': 'normal',
                            'triple_green': False,
                            'current_price': float(pair_info.get('last_price', 0) or 0),
                            'price_change_24h': change_24h,
                            '24h': float(change_24h),
                            'vol': float(pair_info.get('quote_volume', 0) or 0),
                            'vol_pct': 0.0,
                            'profit_potential': abs(change_24h),
                            'note': f"proxy_from_{pair_found}"
                        }
                        self.radar_data_cache[key] = entry
                        self.radar_last_update[key] = time.time()
                        updated_destinations.add(target)

                        # Pequeño yield para no bloquear el loop
                        await asyncio.sleep(0.001)

                    # Criterio: intentar rellenar al menos 10 activos distintos con datos
                    if len(updated_destinations) >= 10:
                        break

                except Exception as e:
                    logger.debug(f"Error en scan multi-bases para {target}: {e}")
                    continue

            logger.info(f"✅ Escáner multi-bases completado: {len(updated_destinations)} activos actualizados")
            return len(updated_destinations)
        except Exception as e:
            logger.error(f"Error en _scan_whitelist_multi_bases: {e}", exc_info=True)
            return 0
    async def _save_active_trades(self, open_trades: List[Dict[str, Any]]):
        """
        Guarda los trades activos en shared/active_trades.json para recuperación tras reinicio.
        """
        try:
            active_trades_data = {
                'timestamp': datetime.now().isoformat(),
                'trades': open_trades
            }
            
            # Guardar usando file locking si está disponible
            if HAS_FILE_UTILS:
                write_json_safe(self.active_trades_path, active_trades_data)
            else:
                # Fallback: escritura estándar
                self.active_trades_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.active_trades_path, 'w', encoding='utf-8') as f:
                    json.dump(active_trades_data, f, indent=2, default=str)
                try:
                    self.active_trades_path.chmod(0o664)
                except:
                    pass
            
        except Exception as e:
            logger.error(f"Error guardando active_trades.json: {e}")
    
    async def _recover_active_trades(self):
        """
        Recupera trades activos desde shared/active_trades.json tras un reinicio.
        Verifica que los trades existan en la base de datos y estén activos.
        """
        try:
            if not self.active_trades_path.exists():
                logger.debug("No existe active_trades.json, no hay trades para recuperar")
                return
            
            # Leer archivo
            active_trades_data = None
            if HAS_FILE_UTILS:
                active_trades_data = read_json_safe(self.active_trades_path, {})
            else:
                try:
                    with open(self.active_trades_path, 'r', encoding='utf-8') as f:
                        active_trades_data = json.load(f)
                except:
                    active_trades_data = {}
            
            if not active_trades_data or 'trades' not in active_trades_data:
                logger.debug("active_trades.json vacío o inválido")
                return
            
            trades_to_recover = active_trades_data.get('trades', [])
            if not trades_to_recover:
                logger.debug("No hay trades para recuperar")
                return
            
            logger.info(f"Recuperando {len(trades_to_recover)} trades desde active_trades.json...")
            
            recovered_count = 0
            for trade_data in trades_to_recover:
                try:
                    slot_id = trade_data.get('slot_id')
                    trade_id = trade_data.get('trade_id')
                    
                    if slot_id is None or trade_id is None:
                        continue
                    
                    # Verificar que el trade existe en la base de datos y está activo
                    db_trade = self.db.get_active_trade(slot_id)
                    if db_trade and db_trade.get('id') == trade_id:
                        # El trade ya está activo en la BD, no hay nada que hacer
                        recovered_count += 1
                        logger.debug(
                            f"Trade recuperado: Slot {slot_id}, Trade ID {trade_id}, "
                            f"{trade_data.get('target_asset', 'N/A')}"
                        )
                    else:
                        # El trade no está activo en la BD, puede haber sido cerrado manualmente
                        logger.debug(
                            f"Trade no encontrado en BD (puede haber sido cerrado): "
                            f"Slot {slot_id}, Trade ID {trade_id}"
                        )
                        
                except Exception as e:
                    logger.error(f"Error recuperando trade: {e}")
                    continue
            
            logger.info(f"✅ Recuperación completada: {recovered_count}/{len(trades_to_recover)} trades activos")
            
        except Exception as e:
            logger.error(f"Error en recuperación de trades: {e}")
    
    async def _save_shared_state(self):
        """Guarda el estado compartido en shared/state.json."""
        try:
            logger.debug("Iniciando guardado de estado compartido...")
            whitelist = self.strategy.get("whitelist", [])
            
            # 1. Estado del mercado (BTC) - cálculo real vía ticker
            btc_change = 0.0
            btc_price = 0.0
            eth_price = 0.0
            btc_error = False
            eth_error = False
            try:
                # Priorizar USDT por liquidez; fallback a EUR si no existe
                btc_info = get_pair_info('BTC/USDT') or get_pair_info('BTC/EUR')
                if btc_info:
                    btc_change = float(btc_info.get('price_change_percent') or 0.0)
                    btc_price = float(btc_info.get('last_price') or 0.0)
                else:
                    btc_error = True
            except Exception as e:
                logger.debug(f"Error obteniendo ticker BTC: {e}")
                btc_error = True
            try:
                eth_info = get_pair_info('ETH/USDT') or get_pair_info('ETH/EUR')
                if eth_info:
                    eth_price = float(eth_info.get('last_price') or 0.0)
                else:
                    eth_error = True
            except Exception as e:
                logger.debug(f"Error obteniendo ticker ETH: {e}")
                eth_error = True

            # Semáforo simple por variación BTC 24h
            try:
                if btc_change >= 2.0:
                    market_status = {'status': 'safe', 'message': '🟢 SEGURO', 'color': '#00FF88', 'btc_change': btc_change}
                elif btc_change <= -2.0:
                    market_status = {'status': 'danger', 'message': '🔴 PELIGRO', 'color': '#FF3344', 'btc_change': btc_change}
                else:
                    market_status = {'status': 'neutral', 'message': '🟡 NEUTRAL', 'color': '#FFCC00', 'btc_change': btc_change}
            except Exception:
                market_status = {'status': 'neutral', 'message': '🟡 NEUTRAL', 'color': '#FFCC00', 'btc_change': 0.0}

            # 2. Precios BTC/ETH reales
            prices = {
                'btc_price': btc_price,
                'eth_price': eth_price,
                'btc_error': btc_error,
                'eth_error': eth_error
            }
            
            # 3. Balances
            balances_data = {'total': {}}
            try:
                if self.exchange:
                    balances = self.exchange.fetch_balance()
                    if balances and 'total' in balances:
                        balances_data = {'total': balances['total']}
            except Exception as e:
                logger.debug(f"Error al obtener balances: {e}")
            
            # 4. RADAR DATA - PERSISTENCIA INTELIGENTE: cache > BD > valores por defecto
            radar_data = []
            origin = 'XRP'  # Moneda origen por defecto
            
            # Obtener monedas de wallet si es posible
            try:
                wallet_currencies = await self._get_wallet_currencies_for_radar()
                if wallet_currencies:
                    origin = wallet_currencies[0]
            except:
                pass
            
            # 1. PRIORIDAD: Usar cache del radar (datos recién calculados)
            cached_pairs = {}
            if hasattr(self, 'radar_data_cache') and self.radar_data_cache:
                for key, entry in self.radar_data_cache.items():
                    if isinstance(entry, dict) and 'destination' in entry:
                        cached_pairs[entry['destination']] = entry
                        radar_data.append(entry)
                logger.info(f"🔄 Cache del radar: {len(cached_pairs)} pares cargados")
            
            # 2. RECUPERAR datos persistidos en SQLite para activos que no están en cache
            try:
                from storage import get_latest_market_data
                db_entries = get_latest_market_data(limit=50)  # Obtener últimos 50 registros
                for db_entry in db_entries:
                    dest = db_entry.get('destination')
                    if dest and dest not in cached_pairs and dest not in ['EUR', 'USDC', 'BNB']:
                        # Solo agregar si tiene datos útiles (heat_score > 0 o rsi calculado)
                        if db_entry.get('heat_score', 0) > 0 or db_entry.get('rsi') is not None:
                            radar_data.append(db_entry)
                            cached_pairs[dest] = db_entry
                logger.info(f"📊 SQLite: {len(db_entries)} registros recuperados, {len(radar_data) - len(self.radar_data_cache if hasattr(self, 'radar_data_cache') else {})} agregados")
            except Exception as db_error:
                logger.debug(f"No se pudieron recuperar datos de SQLite: {db_error}")
            
            # 3. LLENAR HUECOS: Crear entradas por defecto solo para activos faltantes
            covered_destinations = set(cached_pairs.keys())
            missing_count = 0
            for whitelist_asset in whitelist:
                # Saltar FIAT y BNB
                if whitelist_asset in ['EUR', 'USDC', 'BNB']:
                    continue
                # Saltar el origen
                if whitelist_asset == origin:
                    continue
                # Saltar si ya está cubierto
                if whitelist_asset in covered_destinations:
                    continue
                
                try:
                    # Crear entrada placeholder con valores por defecto
                    placeholder_entry = {
                        'pair': f"{origin}/{whitelist_asset}",
                        'origin': origin,
                        'destination': whitelist_asset,
                        'from_currency': origin,
                        'to_currency': whitelist_asset,
                        'swap_label': f"{origin} → {whitelist_asset}",
                        'heat_score': 0,
                        'rsi': None,
                        'ema200_distance': None,
                        'volume_status': '-',
                        'volume_change_24h': 0.0,
                        '24h': 0.0,
                        'vol': 0.0,
                        'vol_pct': 0.0,
                        'triple_green': False,
                        'current_price': 0,
                        'price_change_24h': 0.0,
                        'update_group': 'D',
                        'update_frequency': 60,
                        'last_update_ts': time.time()
                    }
                    radar_data.append(placeholder_entry)
                    missing_count += 1
                except Exception as e:
                    logger.debug(f"Error creando placeholder para {whitelist_asset}: {e}")
                    continue
            
            if missing_count > 0:
                logger.info(f"🔧 Placeholders creados: {missing_count} activos sin datos")
            logger.info(f"✅ Radar generado: {len(radar_data)} pares (cache: {len(cached_pairs)}, placeholders: {missing_count})")
            
            # PERSISTIR EN SQLITE (usando save_market_data)
            if radar_data:
                try:
                    save_market_data(radar_data, ts=int(time.time()))
                    logger.info(f"✅ Persistidos {len(radar_data)} pares en SQLite")
                except Exception as db_err:
                    logger.error(f"❌ Error persistiendo en SQLite: {db_err}")

            # 4. Persistencia de vigilancia: elegir líder por heat_score
            try:
                vig_path = ROOT_DIR / 'shared' / 'vigilancia_state.json'
                leader = None
                if radar_data:
                    # Ordenar por heat_score descendente y elegir el primero con heat > 0
                    try:
                        sorted_radar = sorted(radar_data, key=lambda e: (e.get('heat_score') or 0), reverse=True)
                    except Exception:
                        sorted_radar = radar_data
                    for e in sorted_radar:
                        hs = float(e.get('heat_score') or 0)
                        if hs > 0:
                            leader = e
                            break
                if leader:
                    origin_lead = leader.get('origin') or leader.get('from_currency')
                    dest_lead = leader.get('destination') or leader.get('to_currency')
                    pair_lead = leader.get('pair') or (f"{origin_lead}/{dest_lead}" if origin_lead and dest_lead else None)
                    if pair_lead:
                        # Leer estado previo para mantener start_ts si el líder no cambia
                        prev = {}
                        if vig_path.exists():
                            try:
                                with open(vig_path, 'r', encoding='utf-8') as vf:
                                    prev = json.load(vf) or {}
                            except Exception:
                                prev = {}
                        prev_pair = prev.get('current_pair')
                        prev_start_ts = prev.get('start_ts')

                        # Normalización básica para comparar
                        def _norm(p: str) -> str:
                            try:
                                return ''.join([ch for ch in p.upper() if ch.isalnum() or ch == '/'])
                            except Exception:
                                return p or ''

                        if _norm(prev_pair or '') == _norm(pair_lead):
                            start_ts_val = prev_start_ts if prev_start_ts is not None else time.time()
                        else:
                            start_ts_val = time.time()

                        buffer_prev = prev.get('buffer') or []
                        buffer_new = (buffer_prev + [pair_lead])[-3:]
                        vig_state = {
                            'vigilante_timers': {pair_lead: datetime.utcnow().isoformat()},
                            'current_pair': pair_lead,
                            'buffer': buffer_new,
                            'start_ts': start_ts_val,
                            'last_updated': datetime.utcnow().isoformat()
                        }
                        try:
                            vig_path.parent.mkdir(parents=True, exist_ok=True)
                            with open(vig_path, 'w', encoding='utf-8') as vf:
                                json.dump(vig_state, vf, indent=2, default=str)
                            try:
                                os.chmod(vig_path, 0o664)
                            except Exception:
                                pass
                            logger.info(f"✅ Vigilancia actualizada: {pair_lead} (heat {leader.get('heat_score')})")
                        except Exception as ve:
                            logger.debug(f"No se pudo persistir vigilancia_state.json: {ve}")
            
            except Exception as vig_err:
                logger.debug(f"No se pudo actualizar vigilancia: {vig_err}")
            
            # 5. Inventario Dinámico
            dynamic_inventory = []
            try:
                dynamic_inventory = await self._get_dynamic_inventory()
                logger.debug(f"Inventario dinámico: {len(dynamic_inventory)} activos")
            except Exception as e:
                logger.debug(f"Error al obtener inventario dinámico: {e}")
            
            # 6. Valor total del portfolio
            total_portfolio_value = 0.0
            try:
                if hasattr(self, 'total_portfolio_value') and self.total_portfolio_value > 0:
                    total_portfolio_value = self.total_portfolio_value
                else:
                    total_portfolio_value = self.vault.calculate_total_portfolio_value()
                    if total_portfolio_value is None or total_portfolio_value < 0:
                        total_portfolio_value = 0.0
            except Exception as e:
                logger.debug(f"Error calculando portfolio value: {e}")
            
            # 7. Treasury
            treasury_total = {'total_eur': 0.0, 'total_btc': 0.0}
            try:
                treasury_total = self.db.get_total_treasury()
            except Exception as e:
                logger.debug(f"Error al obtener treasury: {e}")
            
            # 8. Free cash
            free_cash_eur = 0.0
            try:
                free_cash_eur = balances_data.get('total', {}).get('EUR', 0.0)
            except:
                pass
            
            # 9. Gas BNB
            gas_bnb = {'value_eur': 0.0, 'amount': 0.0, 'percentage': 0.0}
            try:
                bnb_balance = balances_data.get('total', {}).get('BNB', 0.0)
                if bnb_balance > 0:
                    gas_bnb['amount'] = bnb_balance
            except:
                pass
            
            # Construir shared_state completo
            shared_state = {
                'timestamp': datetime.now().isoformat(),
                'market_status': market_status,
                'prices': prices,
                'balances': balances_data,
                'radar_data': radar_data,  # ← AQUÍ ESTÁ EL RADAR CON LOS 19 PARES
                'open_trades': [],
                'dynamic_inventory': dynamic_inventory,
                'total_portfolio_value': total_portfolio_value,
                'treasury': treasury_total,
                'gas_bnb': gas_bnb,
                'free_cash_eur': free_cash_eur,
                'strategy': {
                    'monto_por_operacion': self.strategy.get("trading", {}).get("monto_por_operacion", 0),
                    'max_slots': self.strategy.get("trading", {}).get("max_slots", 0),
                    'rsi_compra': self.strategy.get("indicators", {}).get("rsi_compra", 0)
                }
            }
            
            # Guardar en shared/state.json
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(shared_state, f, indent=2, default=str)
            
            try:
                self.state_path.chmod(0o664)
            except Exception as e:
                logger.debug(f"No se pudieron establecer permisos: {e}")
            
            logger.info(f"✅ Estado compartido guardado: {len(radar_data)} pares en radar")
            
        except Exception as e:
            logger.error(f"❌ Error al guardar estado compartido: {e}", exc_info=True)
            # Medir intervalo entre guardados
