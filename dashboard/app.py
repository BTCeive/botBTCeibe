"""
Dashboard de alta precisión para botCeibe.
Diseño de riesgo y lógica de control - Versión Definitiva.
"""
import streamlit as st
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import os
import sys
import time
import logging
import re
import sqlite3

# Agregar el directorio raíz al path (ruta absoluta resuelta)
ROOT_DIR = Path(__file__).resolve().parent.parent
root_dir_str = str(ROOT_DIR)
if root_dir_str not in sys.path:
    sys.path.insert(0, root_dir_str)

# Importar storage tras asegurar ROOT_DIR en sys.path
from engine.storage import DB_PATH as STORAGE_DB_PATH
from bot_config import DB_PATH as CONFIG_DB_PATH

# Rutas de datos (alineadas con el motor)
TRADES_DB_PATH = Path(CONFIG_DB_PATH)
if not TRADES_DB_PATH.is_absolute():
    TRADES_DB_PATH = ROOT_DIR / TRADES_DB_PATH

# Base de datos de métricas/radar consolidada
BOT_DB_PATH = STORAGE_DB_PATH

# Función de limpieza para comparación robusta
def clean_symbol(s):
    """Extrae solo letras y barra diagonal para comparación robusta de pares."""
    return re.sub(r'[^A-Z/]', '', str(s).upper())


def normalize_pair_for_compare(s: str) -> str:
    """Normaliza eliminando caracteres raros, mantiene el orden original (sin reordenar lados)."""
    return clean_symbol(s)

# Configurar ruta al state.json
STATE_PATH = ROOT_DIR / "shared" / "state.json"
BITACORA_PATH = ROOT_DIR / "bitacora.txt"

def get_latest_market_data() -> List[Dict[str, Any]]:
    try:
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        cur = conn.cursor()
        cur.execute("SELECT id, ts, origin, destination, pair, swap_label, heat_score, change_24h, vol_pct, vol, extra_json FROM market_data ORDER BY id DESC")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return []
        result = []
        for r in rows:
            try:
                extra = json.loads(r[10]) if r[10] else {}
            except Exception:
                extra = {}
            # Normalizar campos mínimos
            extra.setdefault('origin', r[2])
            extra.setdefault('destination', r[3])
            extra.setdefault('pair', r[4])
            extra.setdefault('swap_label', r[5])
            extra.setdefault('heat_score', r[6])
            extra.setdefault('24h', r[7])
            extra.setdefault('vol_pct', r[8])
            extra.setdefault('vol', r[9])
            result.append(extra)
        return result
    except Exception:
        return []

def get_portfolio_history_days(days: int = 30) -> pd.DataFrame:
    try:
        cutoff = int(time.time()) - days * 86400
        conn = sqlite3.connect(str(BOT_DB_PATH), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        cur = conn.cursor()
        cur.execute("SELECT ts, total_portfolio_value, free_cash_eur FROM portfolio_history WHERE ts>=? ORDER BY ts ASC", (cutoff,))
        rows = cur.fetchall()
        conn.close()
        if rows:
            df = pd.DataFrame(rows, columns=['ts', 'total_value', 'free_cash_eur'])
            df['timestamp'] = pd.to_datetime(df['ts'], unit='s')
            return df[['timestamp', 'total_value', 'free_cash_eur']]
        return pd.DataFrame(columns=['timestamp', 'total_value', 'free_cash_eur'])
    except Exception:
        return pd.DataFrame(columns=['timestamp', 'total_value', 'free_cash_eur'])

# Configuración de página
st.set_page_config(
    page_title="botCeibe Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Inicializar caché silenciosamente sin debug
try:
    _ = get_latest_market_data()
except Exception:
    pass

# Ajuste de logging: Dashboard solo WARNING para evitar ruido
try:
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("streamlit").setLevel(logging.WARNING)
except Exception:
    pass

# CSS personalizado - Diseño de alta precisión (inyectado una sola vez)
CSS_STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');

:root{
  --bg: #f8f9fa;
  --card: #000000;
  --text-card: #ffffff;
  --text-title: #000000;
  --accent-green: #00FF88;
  --accent-orange: #FF8844;
  --accent-red: #FF4444;
  --accent-gold: #FFD700;
  --muted: #888888;
}

/* FORZAR TEXTO BLANCO EN TODAS LAS TABLAS DE RADAR */
.stTable table td, .stDataFrame table td {
    color: #FFFFFF !important;
}
.stTable table th, .stDataFrame table th {
    color: #FFFFFF !important;
}
table {
    color: #FFFFFF !important;
}
table tr td {
    color: #FFFFFF !important;
}
table tr th {
    color: #FFFFFF !important;
}

* {
    font-family: 'Inter', sans-serif;
}

body {
    background: var(--bg) !important;
}

div.block-container {
    padding-top: 1rem !important;
    background: var(--bg) !important;
}

#MainMenu {visibility: hidden;}
header {visibility: hidden;}
footer {visibility: hidden;}
.stDeployButton {display:none;}
section[data-testid="stSidebar"] {
    display: none !important;
}

.main .block-container {
    padding-left: 1rem;
    padding-right: 1rem;
    max-width: 100%;
    background: var(--bg) !important;
}

/* Eliminar parpadeo de recarga - Transiciones desactivadas */
.stApp {
    background: var(--bg) !important;
    transition: none !important;
    animation: none !important;
}

[data-testid="stAppViewContainer"] {
    background: var(--bg) !important;
    transition: none !important;
    animation: none !important;
}

/* Prevenir re-render completo de elementos */
.element-container {
    transition: none !important;
    animation: none !important;
}

[data-testid="stVerticalBlock"] {
    transition: none !important;
    animation: none !important;
}

/* Ocultar spinners de carga que causan parpadeo */
.stSpinner {
    display: none !important;
}

/* Mantener estructura estática durante updates */
[data-testid="stMarkdownContainer"] {
    transition: none !important;
}

/* Títulos de sección - Texto negro puro, sin iconos */
h1, h2, h3 {
    color: #000000 !important;
    font-weight: 700 !important;
}

/* Asegurar que los títulos de sección no tengan iconos */
h2, h3 {
    font-size: 1.5em !important;
    margin-top: 1rem !important;
    margin-bottom: 0.5rem !important;
}

/* Header boxes - Dimensiones Blindadas */
.header-box {
    background: var(--card) !important;
    color: var(--text-card) !important;
    border-radius: 8px !important;
    padding: 10px !important;
    height: 110px !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: space-between !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
    overflow: hidden !important;
    position: relative !important;
}

/* Caja GAS - Alineación especial para texto */
.header-box.gas-box {
    justify-content: flex-start !important;
}

.header-box.gas-box .value {
    margin: 0 !important;
    padding: 0 !important;
    position: absolute !important;
    bottom: 10px !important;
    left: 10px !important;
    font-size: 0.85em !important;
}

/* Caja RIESGO BTC - Estructura idéntica a GAS */
.header-box.risk-box {
    justify-content: flex-start !important;
    position: relative !important;
}

.header-box.risk-box .risk-content {
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 4px !important;
    flex: 1 !important;
    margin-top: 0 !important;
}

.header-box.risk-box .value {
    font-size: 0.8em !important;
    margin: 0 !important;
    padding: 0 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}

.header-box h4 {
    color: var(--muted) !important;
    font-size: 0.85em !important;
    font-weight: 600 !important;
    margin: 0 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
}

.header-box .value {
    color: var(--text-card) !important;
    font-size: 1.8em !important;
    font-weight: 700 !important;
    margin: 0 !important;
}

.header-box .value-gold {
    color: var(--accent-gold) !important;
    font-size: 1.8em !important;
    font-weight: 700 !important;
    margin: 0 !important;
}

/* Barra de progreso de Gas */
.gas-progress {
    width: 100% !important;
    height: 4px !important;
    max-height: 4px !important;
    background: #333333 !important;
    border-radius: 2px !important;
    overflow: hidden !important;
    margin-top: 2px !important;
    margin-bottom: 0 !important;
    padding: 0 !important;
    display: block !important;
    position: relative !important;
}

.gas-progress-fill {
    height: 100% !important;
    min-height: 4px !important;
    transition: width 0.3s ease, background-color 0.3s ease !important;
    display: block !important;
    border-radius: 2px !important;
}

.gas-progress-fill.green { background: var(--accent-green) !important; }
.gas-progress-fill.orange { background: var(--accent-orange) !important; }
.gas-progress-fill.red { background: var(--accent-red) !important; }

/* Luz de estado (riesgo) */
.status-light {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 8px;
    box-shadow: 0 0 8px currentColor;
}

.status-light.green-bright { background: var(--accent-green); color: var(--accent-green); box-shadow: 0 0 12px var(--accent-green); }
.status-light.green-light { background: #88FF88; color: #88FF88; box-shadow: 0 0 8px #88FF88; }
.status-light.white { background: #FFFFFF; color: #FFFFFF; box-shadow: 0 0 6px #FFFFFF; }
.status-light.orange { background: var(--accent-orange); color: var(--accent-orange); box-shadow: 0 0 8px var(--accent-orange); }
.status-light.red { background: var(--accent-red); color: var(--accent-red); box-shadow: 0 0 10px var(--accent-red); }

/* Tabla de Slots */
.slots-table {
    width: 100%;
    border-collapse: collapse;
    background: var(--card);
    color: var(--text-card);
    border-radius: 8px;
    overflow: hidden;
}

.slots-table thead {
    background: rgba(255,255,255,0.05);
}

.slots-table th {
    padding: 12px 10px;
    text-align: left;
    font-weight: 600;
    font-size: 0.85em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--muted);
    border-bottom: 1px solid rgba(255,255,255,0.1);
}

.slots-table td {
    padding: 12px 10px;
    border-bottom: 1px solid rgba(255,255,255,0.05);
}

/* Separación entre VALOR y % WALLET */
.slots-table td:nth-child(3) {
    padding-right: 15px !important;
}

.slots-table td:nth-child(4) {
    padding-left: 15px !important;
}

.slots-table tbody tr:hover {
    background: rgba(255,255,255,0.03);
}

/* Slot vigilante - Opacidad selectiva */
.slot-vigilante td:first-child {
    opacity: 1 !important;
}

.slot-vigilante td:nth-child(2) {
    opacity: 0.7 !important;
}

/* Luz de Heat con máximo brillo y efectos de sombra */
.heat-dot {
    opacity: 1 !important;
    width: 12px !important;
    height: 12px !important;
    border-radius: 50% !important;
    display: inline-block !important;
    margin-right: 6px !important;
}

.heat-dot.heat-green,
.heat-dot.heat-brilliant {
    box-shadow: 0 0 8px currentColor, 0 0 12px currentColor !important;
}

.heat-dot.heat-brilliant {
    box-shadow: 0 0 10px currentColor, 0 0 16px currentColor !important;
}

/* Dot blanco para datos faltantes */
.heat-dot.status-white {
    background: #FFFFFF !important;
    color: #FFFFFF !important;
    box-shadow: 0 0 6px #FFFFFF !important;
}

/* Resaltado rojo suave para trades en zona de liquidación - ELIMINADO para uniformidad */
.slot-liquidation-zone {
    /* background: rgba(255, 77, 77, 0.1) !important; */
}

/* Colores PNL brillantes */
.pnl-positive {
    color: var(--accent-green) !important;
    font-weight: 700 !important;
}

.pnl-negative {
    color: var(--accent-red) !important;
    font-weight: 700 !important;
}

.pnl-neutral {
    color: var(--text-card) !important;
}

/* Heat indicator */
.heat-indicator {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

/* Clases de Heat actualizadas según rangos específicos */
.heat-dot.heat-red { 
    background: var(--accent-red) !important; 
    color: var(--accent-red) !important;
    box-shadow: 0 0 6px var(--accent-red) !important;
}

.heat-dot.heat-orange { 
    background: var(--accent-orange) !important; 
    color: var(--accent-orange) !important;
    box-shadow: 0 0 6px var(--accent-orange) !important;
}

.heat-dot.heat-green { 
    background: var(--accent-green) !important; 
    color: var(--accent-green) !important;
}

.heat-dot.heat-brilliant { 
    background: #00ffcc !important; 
    color: #00ffcc !important;
    box-shadow: 0 0 8px #00ffcc, 0 0 12px #00ffcc, 0 0 16px rgba(0, 255, 204, 0.5) !important;
}

/* Reloj */
.clock {
    font-family: 'Courier New', monospace;
    font-size: 0.9em;
    color: var(--muted);
}

/* Slot vigilante - Sin fondo resaltado */
.slot-vigilante {
    background: transparent !important;
    border-left: none !important;
}

/* Historial */
.historial-box {
    background: var(--card) !important;
    color: var(--text-card) !important;
    border-radius: 8px !important;
    padding: 20px !important;
    max-height: 400px;
    overflow-y: auto;
}

.historial-event {
    padding: 8px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    font-size: 0.9em;
}

/* Radar */
.radar-line {
    padding: 10px;
    margin: 6px 0;
    border-radius: 8px;
    background: rgba(255,255,255,0.02);
    transition: background-color 0.18s;
}

.radar-line.heat-high {
    background: var(--accent-green);
    color: #07150a;
    font-weight: 800;
}

.radar-line.heat-warm {
    background: rgba(0,255,136,0.06);
    color: var(--accent-green);
    font-weight: 700;
}

.radar-line.heat-low {
    color: var(--text-card);
}

</style>

<script>
// Script para prevenir parpadeo durante actualizaciones
(function() {
    // Prevenir flash de contenido durante recarga
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAntiFlicker);
    } else {
        initAntiFlicker();
    }
    
    function initAntiFlicker() {
        // Mantener visibilidad durante transiciones
        const containers = document.querySelectorAll('[data-testid="stVerticalBlock"]');
        containers.forEach(container => {
            container.style.transition = 'none';
            container.style.opacity = '1';
        });
        
        // Prevenir re-render completo
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.type === 'childList') {
                    mutation.addedNodes.forEach(function(node) {
                        if (node.nodeType === 1) {
                            node.style.transition = 'none';
                        }
                    });
                }
            });
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }
})();
</script>
"""
st.markdown(CSS_STYLE, unsafe_allow_html=True)

# Inicializar session state para evitar parpadeo
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.last_state = None
    st.session_state.last_update = datetime.now()
    st.session_state.auto_refresh = True
    st.session_state.refresh_interval = 20  # segundos
    st.session_state.last_refresh_time = time.time()

# NO usar st_autorefresh - causa parpadeo
# El auto-refresh se controla desde main() usando st.rerun() de forma controlada


@st.cache_data(ttl=5, show_spinner=False)
def load_state_cached() -> Optional[Dict[str, Any]]:
    """Carga el estado desde state.json con cache para evitar parpadeo.
    Si el JSON está corrupto o parcial, devolver un estado mínimo con valores por defecto
    para evitar que el dashboard rompa el renderizado.
    """
    # Espera corta con reintentos si el archivo aún no existe (evitar carreras de escritura)
    if not STATE_PATH.exists():
        for _ in range(5):
            time.sleep(0.2)
            if STATE_PATH.exists():
                break
        if not STATE_PATH.exists():
            # NO mostrar warnings, devolver estado por defecto silenciosamente
            # La UI cargará radar.json como fallback
            return {
                'balances': {'total': {}},
                'radar_data': [],
                'free_cash_eur': 0.0,
                'total_portfolio_value': 0.0,
                'market_status': {'message': '', 'status': 'safe'},
                'gas_status': {},
                'treasury': {'total_eur': 0.0, 'total_btc': 0.0},
                'open_trades': []
            }

    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            try:
                state = json.load(f)
            except json.JSONDecodeError:
                # Intentar leer el texto por si el archivo está parcialmente escrito
                try:
                    f.seek(0)
                    text = f.read()
                    if not text.strip():
                        raise ValueError("state.json vacío")
                    state = json.loads(text)
                except Exception:
                    # NO mostrar error, usar estado por defecto
                    state = {}

            if not isinstance(state, dict):
                state = {}

            # Asegurar claves por defecto para evitar KeyError o crashes en render
            state.setdefault('balances', {'total': {}})
            state.setdefault('radar_data', [])
            state.setdefault('free_cash_eur', 0.0)
            state.setdefault('total_portfolio_value', 0.0)
            state.setdefault('market_status', {'status': 'safe'})
            state.setdefault('gas_status', {})
            state.setdefault('treasury', {'total_eur': 0.0, 'total_btc': 0.0})
            state.setdefault('open_trades', [])

            return state
    except Exception as e:
        # NO llamar st.error() aquí - causa que Streamlit bloquee el render
        # Solo devolver un estado válido por defecto
        return {
            'balances': {'total': {}},
            'radar_data': [],
            'free_cash_eur': 0.0,
            'total_portfolio_value': 0.0,
            'market_status': {'status': 'safe'},
            'gas_status': {},
            'treasury': {'total_eur': 0.0, 'total_btc': 0.0},
            'open_trades': []
        }


def load_state() -> Optional[Dict[str, Any]]:
    """Carga el estado desde state.json con fallback a session state."""
    # Intentar cargar desde cache primero
    state = load_state_cached()
    
    # Si no hay estado nuevo, usar el último conocido o devolver un estado por defecto
    if state is None:
        if 'last_shared_state' in st.session_state:
            state = st.session_state.last_shared_state
        else:
            state = {
                'balances': {'total': {}},
                'radar_data': [],
                'free_cash_eur': 0.0,
                'total_portfolio_value': 0.0,
                'market_status': {'message': 'Inicializando...'},
                'gas_status': {},
                'treasury': {'total_eur': 0.0, 'total_btc': 0.0},
                'open_trades': []
            }

    # Guardar en session state como backup
    st.session_state.last_shared_state = state
    return state


def get_active_trades() -> List[Dict[str, Any]]:
    """Obtiene trades activos desde la base de datos."""
    try:
        from database import Database
        db = Database(str(TRADES_DB_PATH))
        return db.get_all_active_trades()
    except Exception as e:
        # Fallback a state.json
        state = load_state()
        if state:
            return state.get('open_trades', [])
        return []


def format_time_elapsed(created_at) -> str:
    """Formatea el tiempo transcurrido desde la creación.
    Acepta strings ISO o datetime.
    """
    try:
        if isinstance(created_at, str):
            # Manejar diferentes formatos de fecha
            if 'T' in created_at:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
        elif isinstance(created_at, datetime):
            dt = created_at
        else:
            return "N/A"

        now = datetime.now(dt.tzinfo) if getattr(dt, 'tzinfo', None) else datetime.now()
        delta = now - dt

        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            return f"{days}d {hours}h"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    except Exception:
        return "N/A"


def get_heat_color_class(heat_score: int) -> str:
    """Retorna la clase CSS según el heat score."""
    if heat_score >= 86:
        return "heat-brilliant"  # Verde Brillante / Cian
    elif heat_score >= 71:
        return "heat-green"  # Verde
    elif heat_score >= 41:
        return "heat-orange"  # Naranja
    else:
        return "heat-red"  # Rojo (0-40)


def get_portfolio_snapshots(limit: int = 100) -> pd.DataFrame:
    """Obtiene snapshots del portfolio (últimos 30 días) desde SQLite bot_data.db."""
    return get_portfolio_history_days(days=30)


def load_bitacora() -> List[str]:
    """Carga los últimos eventos de bitacora.txt."""
    if not BITACORA_PATH.exists():
        return []
    try:
        with open(BITACORA_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return [line.strip() for line in lines[-50:] if line.strip()]
    except:
        return []


def main():
    """Función principal del dashboard."""
    # Inicializar estado de auto-refresh (cada 30 segundos)
    if 'auto_refresh' not in st.session_state:
        st.session_state.auto_refresh = True
        st.session_state.refresh_interval = 30  # segundos
    
    # Título estático
    st.title("botCeibe Dashboard")
    
    # Control de auto-refresh (ejecuta silenciosamente en background)
    current_time = time.time()
    if 'last_refresh_time' not in st.session_state:
        st.session_state.last_refresh_time = current_time
    
    time_since_refresh = current_time - st.session_state.last_refresh_time
    
    # Auto-refresco cada 30 segundos
    if st.session_state.auto_refresh and time_since_refresh >= st.session_state.refresh_interval:
        st.session_state.last_refresh_time = current_time
        st.rerun()
    
    # Definir todos los contenedores al inicio para evitar parpadeo
    # Estos contenedores se mantienen en la misma posición siempre
    # Usar placeholders vacíos que se llenan sin causar re-render completo
    header_cont = st.empty()
    slots_cont = st.empty()
    radar_cont = st.empty()
    hucha_cont = st.empty()
    bottom_cont = st.empty()
    
    # Cargar estado con cache (evita lecturas repetidas del archivo)
    state = load_state()
    
    # Manejo de errores sin romper la estructura: nunca debería ser None tras refuerzo
    if state is None:
        state = {
            'balances': {'total': {}},
            'radar_data': [],
            'free_cash_eur': 0.0,
            'total_portfolio_value': 0.0,
            'market_status': {'message': 'Inicializando...'},
            'gas_status': {},
            'treasury': {'total_eur': 0.0, 'total_btc': 0.0},
            'open_trades': []
        }
    
    balances = state.get('balances', {}).get('total', {}) or {}
    radar_data = state.get('radar_data', [])
    
    # Si NO hay balances pero SÍ hay radar_data, mostrar el radar de inmediato
    if (not balances or len(balances) == 0) and (not radar_data or len(radar_data) == 0):
        market_msg = state.get('market_status', {}).get('message', '')
        with header_cont.container():
            if 'Inicializando' in market_msg:
                with st.spinner('⏳ Descargando datos de Binance para 21 activos...'):
                    st.info("El bot está inicializando. Esto puede tomar 30-60 segundos en el primer ciclo.")
            else:
                st.warning("El bot no tiene datos aún.")
        # Mantener estructura aunque no haya datos
        with slots_cont.container():
            pass
        with radar_cont.container():
            pass
        with hucha_cont.container():
            pass
        with bottom_cont.container():
            pass
        return
    
    # ========== HEADER DE CONTROL (Proporción [3, 2, 2, 2, 1]) ==========
    treasury = state.get('treasury', {})
    total_portfolio_value = state.get('total_portfolio_value', 0.0)
    free_cash_eur = state.get('free_cash_eur', 0.0)
    market_status = state.get('market_status', {})
    gas_status = state.get('gas_status', {})
    
    # Calcular fondos totales
    if total_portfolio_value <= 0:
        try:
            from router import get_pair_info
            total_portfolio_value = 0.0
            for asset, amount in balances.items():
                if amount and amount > 0:
                    if asset in ['EUR', 'USDC']:
                        total_portfolio_value += amount
                    else:
                        try:
                            pair_info = get_pair_info(f"{asset}/EUR")
                            if pair_info and pair_info.get('last_price'):
                                total_portfolio_value += amount * pair_info['last_price']
                        except:
                            pass
        except:
            pass
    
    # Calcular inversión (suma de activos en slots)
    active_trades = get_active_trades()
    inversion_total = 0.0
    for trade in active_trades:
        inversion_total += trade.get('initial_fiat_value', 0)
    
    # Calcular Hucha
    hucha_path = ROOT_DIR / 'shared' / 'hucha_diversificada.json'
    hucha_total_eur = 0.0
    try:
        if hucha_path.exists():
            with open(hucha_path, 'r', encoding='utf-8') as f:
                hucha_list = json.load(f)
            for e in hucha_list:
                hucha_total_eur += float(e.get('value_eur_at_save', 0) or 0)
    except:
        hucha_total_eur = 0.0
    
    # Calcular Gas (BNB) con precio de router como fallback
    bnb_balance = balances.get('BNB', 0.0)
    bnb_price = 0
    bnb_value_eur = 0
    try:
        from router import get_pair_info
        bnb_info = get_pair_info("BNB/EUR")
        bnb_price = bnb_info.get('last_price', 0) if bnb_info else 0
        bnb_value_eur = bnb_balance * bnb_price if bnb_price > 0 else 0
    except:
        # Fallback: obtener desde prices en state
        prices = state.get('prices', {})
        bnb_price = prices.get('bnb_price', 0) or 0
        if bnb_price > 0:
            bnb_value_eur = bnb_balance * bnb_price
    
    gas_percent = gas_status.get('percentage', 0.0) if gas_status else 0.0
    if gas_percent <= 0 and bnb_balance > 0 and bnb_price > 0:
        # Calcular % basado en valor de BNB respecto al portfolio total
        gas_percent = (bnb_value_eur / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
    
    # SINCRONIZACIÓN TOTAL DE CAPITAL: Sumar TODAS las criptos en balances
    # EUR, USDC, USDT, BTC, ETH, BNB, etc.
    # FONDOS TOTALES: total_portfolio_value + gas_bnb (el gas no está incluido en portfolio)
    # Este valor incluye TODOS los balances (EUR, USDC, USDT, BTC, ETH, XRP, DOGE) 
    # más el BNB de gas que es reserva separada
    # Recalcular FONDOS desde balances 'total' (Free + Locked)
    try:
        from router import get_pair_info
        wallet_total_eur = 0.0
        funds_audit = []
        for asset, amount in balances.items():
            try:
                amount = float(amount or 0.0)
            except Exception:
                amount = 0.0
            if amount <= 0:
                continue
            price_used = 1.0
            eur_value = 0.0
            if asset == 'EUR':
                # EUR es la moneda base: tasa 1.0 (sin conversión)
                price_used = 1.0
                eur_value = amount
                wallet_total_eur += eur_value
            elif asset in ['USDC', 'USDT']:
                # Stablecoins: forzar EUR/USDT para precisión
                price_used = 1.0
                try:
                    # Intentar EUR/USDT primero para stablecoins
                    pair_info = get_pair_info(f"EUR/{asset}")
                    if pair_info and pair_info.get('last_price'):
                        price_used = float(pair_info.get('last_price', 1.0))
                    else:
                        # Fallback: asumir peg 1:1
                        price_used = 1.0
                except Exception:
                    price_used = 1.0
                eur_value = amount * float(price_used)
                wallet_total_eur += eur_value
            else:
                try:
                    pair_info = get_pair_info(f"{asset}/EUR")
                    price_used = (pair_info.get('last_price', 0.0) if pair_info else 0.0) or 0.0
                    if price_used > 0:
                        eur_value = amount * price_used
                        wallet_total_eur += eur_value
                except Exception:
                    price_used = 0.0
                    eur_value = 0.0
            # Auditar cada activo y su conversión
            funds_audit.append({
                'asset': asset,
                'amount': amount,
                'eur_price': float(price_used or 0.0),
                'eur_value': float(eur_value or 0.0)
            })
        # Imprimir auditoría en logs de Streamlit/console
        try:
            print("\n================ AUDITORÍA DE FONDOS ================")
            print(f"Total activos encontrados: {len(funds_audit)}")
            for row in funds_audit:
                print(f" - {row['asset']:6s}: {row['amount']:>12.8f} unidades | EUR_price={row['eur_price']:.8f} | EUR_value={row['eur_value']:>12.2f}€")
            print(f"TOTAL WALLET: {wallet_total_eur:.2f}€")
            print("====================================================\n")
        except Exception as audit_err:
            print(f"Error en auditoría: {audit_err}")
        fondos_liquidos = wallet_total_eur
    except Exception:
        # Fallback: usar cálculo original
        gas_bnb_value = state.get('gas_bnb', {}).get('value_eur', 0.0)
        fondos_liquidos = (total_portfolio_value or 0.0) + (gas_bnb_value or 0.0)
    
    # Determinar color de gas
    if gas_percent >= 5.0:
        gas_color_class = "green"
    elif gas_percent >= 2.0:
        gas_color_class = "orange"
    else:
        gas_color_class = "red"
    
    # Estado de riesgo (BTC) - Calcular % de riesgo basado en volatilidad
    btc_change = market_status.get('btc_change', 0)
    if btc_change is None:
        btc_change = 0
    
    # Calcular riesgo absoluto (volatilidad)
    btc_risk_percent = abs(btc_change) if btc_change else 0
    
    # Determinar color de luz según umbrales
    if btc_risk_percent < 0.5:
        risk_light_color = "green-bright"
        risk_text = f"{btc_risk_percent:.2f}%"
    elif btc_risk_percent < 0.8:
        risk_light_color = "green-light"
        risk_text = f"{btc_risk_percent:.2f}%"
    elif btc_risk_percent < 1.2:
        risk_light_color = "white"
        risk_text = f"{btc_risk_percent:.2f}%"
    elif btc_risk_percent < 1.8:
        risk_light_color = "orange"
        risk_text = f"{btc_risk_percent:.2f}%"
    else:
        risk_light_color = "red"
        risk_text = f"{btc_risk_percent:.2f}%"
    
    # Bot paralizado si riesgo > 2.0%
    bot_paralizado = btc_risk_percent > 2.0
    
    # Calcular PNL diario
    pnl_diario = 0.0
    for trade in active_trades:
        current_value = trade.get('current_value_eur', trade.get('initial_fiat_value', 0))
        initial_value = trade.get('initial_fiat_value', 0)
        if initial_value > 0:
            pnl_diario += ((current_value - initial_value) / initial_value * 100)
    
    # Calcular fondos totales
    disponible = free_cash_eur
    invertido = inversion_total
    gas_valor = bnb_value_eur
    fondos_total = disponible + invertido + gas_valor
    
    # Renderizar Header
    with header_cont.container():
        col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 2, 1])
    
    # Forzar casts para evitar errores de tipo
    try:
        # Mostrar el total de wallet (suma EUR + cripto) sin quedarnos solo con EUR
        safe_fondos = float(wallet_total_eur if 'wallet_total_eur' in locals() else fondos_liquidos or 0.0)
    except Exception:
        safe_fondos = 0.0

    with col1:
        st.markdown(f"""
            <div class="header-box">
                <h4>FONDOS</h4>
                <div class="value">{safe_fondos:,.2f}€</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
            <div class="header-box">
                <h4>INVERSIÓN</h4>
                <div class="value">{inversion_total:,.2f}€</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
            <div class="header-box">
                <h4>HUCHA</h4>
                <div class="value-gold">{hucha_total_eur:,.2f}€</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        # Barra al 100% si Gas > 5%, pero texto muestra el valor real
        gas_bar_width = 100 if gas_percent > 5.0 else min(100, (gas_percent / 5.0) * 100) if gas_percent > 0 else 0
        st.markdown(f"""
        <div class="header-box gas-box">
            <h4>GAS (BNB)</h4>
            <div class="gas-progress">
                <div class="gas-progress-fill {gas_color_class}" style="width: {gas_bar_width}%;"></div>
            </div>
            <div class="value">{gas_percent:.2f}% / 5.00%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col5:
        st.markdown(f"""
            <div class="header-box risk-box">
                <h4>RIESGO BTC</h4>
                <div class="risk-content">
                    <span class="status-light {risk_light_color}"></span>
                    <div class="value">{risk_text}</div>
                </div>
                {"<div style=\"font-size: 0.7em; color: var(--accent-red); text-align: center; margin-top: auto; position: absolute; bottom: 10px; left: 50%; transform: translateX(-50%);\">BOT PARALIZADO</div>" if bot_paralizado else ""}
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ========== TABLA DE SLOTS ACTIVOS ==========
    with slots_cont.container():
        st.header("SLOTS ACTIVOS")
        
        radar_data = state.get('radar_data', [])
        best_candidate = None
        if radar_data:
            # Ordenar por Heat score descendente y tomar el más alto
            radar_sorted = sorted(radar_data, key=lambda x: x.get('heat_score', 0), reverse=True)
            if radar_sorted:
                best_candidate = radar_sorted[0]
                
                # Gestionar cronómetro de vigilancia con BUFFER DE CAMBIO (3 ciclos consecutivos)
                current_pair_key = f"{best_candidate.get('origin', '')}/{best_candidate.get('destination', '')}"
                
                # Inicializar tracking del par vigilado
                if 'vigilante_pair' not in st.session_state:
                    # Primera vez: inicializar todo
                    st.session_state.vigilante_pair = current_pair_key
                    st.session_state.vigilante_start_time = datetime.now()
                    st.session_state.vigilante_pair_buffer = [current_pair_key]  # Buffer de 3 ciclos
                else:
                    # Buffer de cambio: solo reiniciar si el par cambia durante 3 ciclos consecutivos
                    if 'vigilante_pair_buffer' not in st.session_state:
                        st.session_state.vigilante_pair_buffer = []
                    
                    # Añadir el par actual al buffer (mantener solo los últimos 3)
                    st.session_state.vigilante_pair_buffer.append(current_pair_key)
                    if len(st.session_state.vigilante_pair_buffer) > 3:
                        st.session_state.vigilante_pair_buffer.pop(0)
                    
                    # Verificar si el par cambió durante 3 ciclos consecutivos
                    if len(st.session_state.vigilante_pair_buffer) >= 3:
                        # Si los últimos 3 son iguales y diferentes al par guardado
                        last_three_equal = all(p == current_pair_key for p in st.session_state.vigilante_pair_buffer[-3:])
                        pair_changed = current_pair_key != st.session_state.vigilante_pair
                        
                        if last_three_equal and pair_changed:
                            # El par cambió de forma estable durante 3 ciclos: reiniciar cronómetro
                            st.session_state.vigilante_pair = current_pair_key
                            st.session_state.vigilante_start_time = datetime.now()
                            st.session_state.vigilante_pair_buffer = [current_pair_key]  # Reset buffer
                    # Si el par es el mismo o no hay 3 ciclos consecutivos, NO tocar vigilante_start_time
        
        # Obtener trades activos
        active_trades = get_active_trades()
        
        # Calcular total del portfolio para % WALLET
        if total_portfolio_value <= 0:
            dynamic_inventory = state.get('dynamic_inventory', [])
            total_portfolio_value = sum(item.get('value_eur', 0) for item in dynamic_inventory)
            total_portfolio_value += bnb_value_eur + treasury.get('total_eur', 0)
                
        # Construir tabla HTML - PRIMERO los slots activos, LUEGO el vigilante
        slots_html = '<div style="background: var(--card); border-radius: 8px; overflow: hidden;">'
        slots_html += '<table class="slots-table">'
        slots_html += '<thead><tr>'
        slots_html += '<th>#</th>'
        slots_html += '<th>ACTIVO</th>'
        slots_html += '<th>VALOR (€)</th>'
        slots_html += '<th>% WALLET</th>'
        slots_html += '<th>ENTRADA</th>'
        slots_html += '<th>ACTUAL</th>'
        slots_html += '<th>PNL%</th>'
        slots_html += '<th>ESTADO</th>'
        slots_html += '<th>⏱</th>'
        slots_html += '</tr></thead><tbody>'
        
        # Slots en operación (PRIMERO) - Asegurar que empiezan en # 1
        slot_counter = 1
        for trade in active_trades:
            slot_id = slot_counter  # Forzar numeración desde 1
            slot_counter += 1
            target_asset = trade.get('target_asset', 'N/A')
            initial_value = trade.get('initial_fiat_value', 0)
            entry_price = trade.get('entry_price', 0)
            amount = trade.get('amount', 0)
            created_at = trade.get('created_at', '')
            
            # Obtener precio actual
            current_price = entry_price
            current_value = initial_value
            try:
                from router import get_pair_info
                symbol = trade.get('symbol', f"{target_asset}/EUR")
                pair_info = get_pair_info(symbol)
                if pair_info and pair_info.get('last_price'):
                    current_price = pair_info['last_price']
                    current_value = amount * current_price
            except:
                pass
            
            # Calcular PNL
            pnl_percent = ((current_value - initial_value) / initial_value * 100) if initial_value > 0 else 0
            pnl_class = "pnl-positive" if pnl_percent > 0 else "pnl-negative" if pnl_percent < 0 else "pnl-neutral"
            
            # Obtener highest_price para trailing stop persistente
            highest_price = trade.get('highest_price', entry_price)
            max_pnl_reached = ((highest_price * amount - initial_value) / initial_value * 100) if initial_value > 0 and amount > 0 else 0
            
            # % Wallet
            wallet_percent = (current_value / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
            
            # Estado (estrategia activa) - Trailing Stop Con Memoria BLOQUEADA
            # Una vez que PNL toque +0.60%, el estado 'Trailing' se queda FIJO PERMANENTEMENTE
            # Muestra SIEMPRE el beneficio asegurado (PNL máximo alcanzado - 0.5%)
            # NO desaparece aunque el precio baje después
            estado = "Sin protección"
            trailing_stop_value = None
            is_liquidation_zone = False
            
            if pnl_percent <= -1.5:
                estado = "Stop Loss -1.5%"
            elif max_pnl_reached >= 0.6:
                # Trailing Stop BLOQUEADO: una vez activado al +0.6%, permanece para siempre
                # Calcular beneficio asegurado basado en el PNL máximo alcanzado
                # Beneficio asegurado = max_pnl_reached - 0.5%
                trailing_stop_value = max_pnl_reached - 0.5
                
                # Asegurar que el trailing_stop_value nunca sea negativo
                if trailing_stop_value < 0:
                    trailing_stop_value = 0.0
                
                estado = f"Trailing {trailing_stop_value:.2f}%"
                
                # Si PNL actual < stop asegurado, está en zona de liquidación
                if pnl_percent < trailing_stop_value:
                    is_liquidation_zone = True
            else:
                estado = "Sin protección"
            
            # Tiempo transcurrido
            time_elapsed = format_time_elapsed(created_at)
            
            # Obtener símbolo completo para mostrar par
            symbol = trade.get('symbol', f"{target_asset}/EUR")
            
            # Formatear precios con todos los decimales
            entry_price_str = f"{entry_price:.8f}".rstrip('0').rstrip('.')
            current_price_str = f"{current_price:.8f}".rstrip('0').rstrip('.')
            
            # Color del precio actual: Blanco fijo
            current_price_color = "#FFFFFF"
            
            # Clase CSS para zona de liquidación - Sin resaltado visual
            row_class = ""
            
            slots_html += f'<tr class="{row_class}">'
            slots_html += f'<td>{slot_id}</td>'
            slots_html += f'<td><strong>{symbol}</strong></td>'
            slots_html += f'<td style="padding-right: 15px;">{current_value:,.2f}</td>'
            slots_html += f'<td style="padding-left: 15px;">{wallet_percent:.1f}%</td>'
            slots_html += f'<td style="font-family: monospace;">{entry_price_str}</td>'
            slots_html += f'<td style="font-family: monospace; color: {current_price_color};">{current_price_str}</td>'
            slots_html += f'<td class="{pnl_class}">{pnl_percent:+.2f}%</td>'
            slots_html += f'<td>{estado}</td>'
            slots_html += f'<td class="clock">⏳ {time_elapsed}</td>'
            slots_html += '</tr>'
        
        # Slot Vigilante (*) - SIEMPRE AL FINAL
        if best_candidate:
            heat_score = best_candidate.get('heat_score', 0)
            heat_class = get_heat_color_class(heat_score)
            origin = best_candidate.get('origin') or best_candidate.get('from_currency', 'N/A')
            destination = best_candidate.get('destination') or best_candidate.get('to_currency', 'N/A')
            pair_candidate = f"{origin}/{destination}"
            
            # Color dinámico según Heat con rangos específicos
            if heat_score >= 86:
                heat_color = "#00ffcc"  # Verde Brillante / Cian (86-100)
            elif heat_score >= 71:
                heat_color = "var(--accent-green)"  # Verde (71-85)
            elif heat_score >= 41:
                heat_color = "var(--accent-orange)"  # Naranja (41-70)
            else:
                heat_color = "var(--accent-red)"  # Rojo (0-40)
            
            # FORZAR cálculo datetime.now() - start_ts con formato extendido (ej: 14m 20s)
            # IMPORTANTE: start_ts debe tratarse como float (timestamp UNIX) en todo el flujo
            vigilancia_time = "Iniciando..."
            vigilancia_time_color = "#888888"  # Gris para distinguir del resto
            try:
                vigilancia_state_path = ROOT_DIR / "shared" / "vigilancia_state.json"
                if vigilancia_state_path.exists():
                    with open(vigilancia_state_path, 'r', encoding='utf-8') as vf:
                        vigilancia_state = json.load(vf)
                        start_ts = vigilancia_state.get('start_ts')
                        current_pair_vigilancia = vigilancia_state.get('current_pair')
                        
                        # Comparación normalizada con clean_symbol (solo A-Z y /)
                        current_normalized = normalize_pair_for_compare(current_pair_vigilancia)
                        candidate_normalized = normalize_pair_for_compare(pair_candidate)

                        # DEBUG: log siempre activo en consola para diagnosticar matching
                        print(
                            f"🔍 Comparando slot: [{candidate_normalized}] con JSON: [{current_normalized}] | "
                            f"raw_slot='{pair_candidate}' raw_json='{current_pair_vigilancia}'"
                        )

                        matched = current_normalized == candidate_normalized
                        if not matched:
                            # Último recurso: comparar solo la moneda base (lado izquierdo tras orden alfabético)
                            slot_base = candidate_normalized.split('/')[0] if '/' in candidate_normalized else candidate_normalized
                            json_base = current_normalized.split('/')[0] if '/' in current_normalized else current_normalized
                            matched = slot_base == json_base
                            if matched:
                                print(
                                    f"🔍 Fallback base match: slot_base={slot_base} json_base={json_base} "
                                    f"(slot={candidate_normalized}, json={current_normalized})"
                                )

                        if (start_ts is not None) and matched:
                            # Cálculo forzado en tiempo real con manejo robusto de float
                            now_ts = time.time()
                            
                            # Convertir start_ts a float si es necesario
                            try:
                                # Si es string, intentar convertir
                                if isinstance(start_ts, str):
                                    # Intentar como ISO string primero
                                    try:
                                        start_dt = datetime.fromisoformat(start_ts)
                                        start_ts_float = start_dt.timestamp()
                                    except:
                                        # Si falla, intentar como string numérico
                                        start_ts_float = float(start_ts)
                                else:
                                    # Ya es número
                                    start_ts_float = float(start_ts)
                                
                                # Calcular elapsed time
                                elapsed_seconds = int(max(0.0, now_ts - start_ts_float))
                                
                                # Si elapsed es 0 o negativo, forzar 0s
                                if elapsed_seconds <= 0:
                                    vigilancia_time = "0s"
                                # Formato: siempre mostrar minutos y segundos
                                elif elapsed_seconds < 60:
                                    vigilancia_time = f"{elapsed_seconds}s"
                                elif elapsed_seconds < 3600:
                                    minutes = elapsed_seconds // 60
                                    seconds = elapsed_seconds % 60
                                    vigilancia_time = f"{minutes}m {seconds}s"
                                else:
                                    hours = elapsed_seconds // 3600
                                    minutes = (elapsed_seconds % 3600) // 60
                                    seconds = elapsed_seconds % 60
                                    vigilancia_time = f"{hours}h {minutes}m {seconds}s"
                            except Exception as conv_error:
                                logger.debug(f"Error convirtiendo start_ts: {conv_error}")
                                vigilancia_time = "Iniciando..."
                        else:
                            # Si no coincide el par, mostrar estado inicial
                            vigilancia_time = "Iniciando..."
            except Exception as e:
                vigilancia_time = "Iniciando..."
            
            slots_html += '<tr class="slot-vigilante">'
            slots_html += '<td>*</td>'
            slots_html += f'<td><strong style="color: #aaaaaa; font-weight: 400;">{pair_candidate} (esperando...)</strong></td>'
            slots_html += '<td>-</td>'
            slots_html += '<td>-</td>'
            slots_html += '<td>-</td>'
            slots_html += '<td>-</td>'
            slots_html += '<td>-</td>'
            slots_html += f'<td><div class="heat-indicator"><span class="heat-dot {heat_class}" style="background: {heat_color}; color: {heat_color};"></span>HEAT {heat_score}</div></td>'
            slots_html += f'<td class="clock" style="color: {vigilancia_time_color}; font-weight: 500;">⏳ {vigilancia_time}</td>'
            slots_html += '</tr>'
        
        slots_html += '</tbody></table></div>'
        
        st.markdown(slots_html, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
    # ========== RADAR TÉCNICO (TABLA CON PANDAS) ==========
    with radar_cont.container():
        st.header("Radar Técnico")

        # Cargar radar desde SQLite preferentemente
        # Preferir el estado en memoria (tiene las entradas forzadas completas)
        radar_data_state = state.get('radar_data', []) if isinstance(state.get('radar_data', []), list) else []
        radar_data_db = get_latest_market_data()
        radar_data = radar_data_state if radar_data_state else radar_data_db

        if radar_data:
            # Top 20 por HEAT (reducción de ruido y render más ligero)
            radar_sorted = sorted(radar_data, key=lambda x: x.get('heat_score', 0), reverse=True)[:20]
            
            # Función para obtener LED con box-shadow según valor
            def get_led_style_rsi(rsi):
                if rsi is None or not isinstance(rsi, (int, float)): 
                    return 'background: #666; box-shadow: 0 0 4px #666;'
                if rsi < 30: return 'background: #ff4444; box-shadow: 0 0 8px #ff4444;'
                elif rsi < 40: return 'background: #ff8844; box-shadow: 0 0 8px #ff8844;'
                elif rsi < 45: return 'background: #ffffff; box-shadow: 0 0 6px #ffffff;'
                elif rsi < 60: return 'background: #00ff88; box-shadow: 0 0 10px #00ff88;'
                else: return 'background: #00ffcc; box-shadow: 0 0 12px #00ffcc;'
            
            def get_led_style_ema(ema_dist):
                if ema_dist is None or not isinstance(ema_dist, (int, float)): 
                    return 'background: #666; box-shadow: 0 0 4px #666;'
                ema_abs = abs(ema_dist)
                if ema_abs > 3: return 'background: #ff4444; box-shadow: 0 0 8px #ff4444;'
                elif ema_abs > 2: return 'background: #ff8844; box-shadow: 0 0 8px #ff8844;'
                elif ema_abs > 1: return 'background: #ffffff; box-shadow: 0 0 6px #ffffff;'
                elif ema_abs > 0.5: return 'background: #00ff88; box-shadow: 0 0 10px #00ff88;'
                else: return 'background: #00ffcc; box-shadow: 0 0 12px #00ffcc;'
            
            def get_color_unified(value):
                """Escala AGRESIVA de 5 niveles para 24h y VOL (texto y LED).
                SENSIBILIDAD MÁXIMA: Aplicar color aunque valores sean pequeños.
                Verde Brillante: > 1.0%
                Verde Claro: 0.05% a 1.0%
                Blanco: -0.05% a 0.05%
                Naranja: -1.0% a -0.05%
                Rojo: < -1.0%
                """
                if value is None or not isinstance(value, (int, float)):
                    return '#888888'  # Gris SOLO si no hay dato (None)
                # Escala AGRESIVA: Umbrales MÁS BAJOS para máxima sensibilidad
                if value > 1.0:
                    return '#00ff88'  # 🟢 Verde brillante (>1.0%)
                elif value > 0.05:
                    return '#a2ffb3'  # 🟢 Verde claro (>0.05%)
                elif value >= -0.05:
                    return '#ffffff'  # ⚪ Blanco (-0.05% a +0.05%)
                elif value >= -1.0:
                    return '#ffcc00'  # 🟠 Naranja (-1.0% a -0.05%)
                else:
                    return '#ff4444'  # 🔴 Rojo (<-1.0%)
            
            def get_led_style_unified(value):
                """Escala AGRESIVA de 5 niveles para LEDs de VOL con box-shadow."""
                if value is None or not isinstance(value, (int, float)):
                    return 'background: #666; box-shadow: 0 0 4px #666;'  # Gris SOLO si None
                # Escala AGRESIVA: Mismos umbrales bajos que get_color_unified
                if value > 1.0:
                    return 'background: #00ff88; box-shadow: 0 0 12px #00ff88;'  # 🟢 >1.0%
                elif value > 0.05:
                    return 'background: #a2ffb3; box-shadow: 0 0 8px #a2ffb3;'  # 🟢 >0.05%
                elif value >= -0.05:
                    return 'background: #ffffff; box-shadow: 0 0 6px #ffffff;'  # ⚪ ±0.05%
                elif value >= -1.0:
                    return 'background: #ffcc00; box-shadow: 0 0 8px #ffcc00;'  # 🟠 -1.0% a -0.05%
                else:
                    return 'background: #ff4444; box-shadow: 0 0 10px #ff4444;'  # 🔴 <-1.0%
            
            def get_led_style_heat(heat):
                if heat >= 86: return 'background: #00ffcc; box-shadow: 0 0 12px #00ffcc;'
                elif heat >= 71: return 'background: #00ff88; box-shadow: 0 0 10px #00ff88;'
                elif heat >= 41: return 'background: #ff8844; box-shadow: 0 0 8px #ff8844;'
                else: return 'background: #ff4444; box-shadow: 0 0 8px #ff4444;'
            
            def is_optimal_row(rsi, ema, vol_change, heat):
                # Fila óptima: todos los indicadores en verde claro o brillante
                rsi_ok = rsi and isinstance(rsi, (int, float)) and 45 <= rsi <= 70
                ema_ok = ema and isinstance(ema, (int, float)) and abs(ema) <= 1.0
                vol_ok = vol_change and isinstance(vol_change, (int, float)) and vol_change >= 20
                heat_ok = heat >= 71
                return rsi_ok and ema_ok and vol_ok and heat_ok
            
            # Mostrar siempre 10 filas por tabla (20 filas totales: 10 en izquierda + 10 en derecha)
            # RADAR DINÁMICO: Top 20 por heat_score, EXACTAMENTE 20 filas
            rows_per_table = 10
            total_rows = 20  # FIJO: 20 filas para Top 20
            
            # Rellenar con filas vacías si hay menos datos
            radar_display = radar_sorted[:total_rows]
            while len(radar_display) < total_rows:
                radar_display.append(None)  # Añadir filas vacías
            
            # Dividir en impares (izquierda) y pares (derecha)
            radar_impares = [radar_display[i] for i in range(0, len(radar_display), 2)]
            radar_pares = [radar_display[i] for i in range(1, len(radar_display), 2)]
            
            # Contenedor con fondo negro (sin botones, ocupa todo el ancho disponible)
            st.markdown(
                '<div style="background: #0a0a0a; padding: 15px; border-radius: 8px; width: 100%;">',
                unsafe_allow_html=True
            )
            
            # COLUMNAS PARALELAS (2 columnas de igual ancho)
            col1, col2 = st.columns(2, gap="small")
            
            # COLUMNA IZQUIERDA (Impares: 1, 3, 5...)
            with col1:
                radar_html_left = '<table style="width: 100%; border-collapse: collapse; color: #FFFFFF; font-size: 12px; background: #0a0a0a;">'
                radar_html_left += '<thead><tr style="background: transparent; text-align: left; border: none;">'
                radar_html_left += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">#</th>'
                radar_html_left += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">ACTIVO</th>'
                radar_html_left += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">24h</th>'
                radar_html_left += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">RSI</th>'
                radar_html_left += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">EMA</th>'
                radar_html_left += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">VOL</th>'
                radar_html_left += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">HEAT</th>'
                radar_html_left += '</tr></thead><tbody>'
                
                for idx_display, item in enumerate(radar_impares, start=1):
                    real_idx = (idx_display - 1) * 2 + 1  # 1, 3, 5, 7...
                    
                    if item is None:
                        # Fila vacía con guiones
                        radar_html_left += '<tr style="background: transparent; border-bottom: 1px solid rgba(255,255,255,0.03);">'
                        radar_html_left += f'<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">{real_idx}</td>'
                        radar_html_left += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 11px;">-</td>'
                        radar_html_left += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">-</td>'
                        radar_html_left += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">-</td>'
                        radar_html_left += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">-</td>'
                        radar_html_left += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">-</td>'
                        radar_html_left += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">-</td>'
                        radar_html_left += '</tr>'
                        continue
                    
                    origin = item.get('origin', item.get('from_currency', ''))
                    destination = item.get('destination', item.get('to_currency', ''))
                    par_completo = f"{origin}/{destination}" if origin and destination else destination or '-'
                    
                    rsi = item.get('rsi')
                    ema_dist = item.get('ema200_distance')
                    # MAPEO FORZADO IZQUIERDA: Leer '24h' y 'vol_pct' (claves cortas del motor)
                    cambio_24h = item.get('24h')
                    if cambio_24h is None:
                        cambio_24h = (item.get('change_24h') or item.get('price_change_24h') or 
                                      item.get('priceChangePercent') or item.get('percentage') or 0.0)
                    vol_change = item.get('vol_pct')
                    if vol_change is None:
                        vol_change = (item.get('volume_change') or 
                                      item.get('volume_change_24h') or item.get('vol_change_pct') or 0.0)
                    heat = int(item.get('heat_score', 0) or 0)
                    
                    # LEDs con box-shadow
                    led_style_rsi = get_led_style_rsi(rsi)
                    led_style_ema = get_led_style_ema(ema_dist)
                    led_style_vol = get_led_style_unified(vol_change)
                    led_style_heat = get_led_style_heat(heat)
                    
                    # Valores formateados - limpiar 0 y None
                    heat_str = f"{heat}" if heat > 0 else "-"
                    rsi_str = f"{rsi:.0f}" if rsi and isinstance(rsi, (int, float)) and rsi > 0 else "-"
                    ema_str = f"{ema_dist:+.1f}" if ema_dist and isinstance(ema_dist, (int, float)) else "-"
                    vol_str = f"{vol_change:+.1f}%" if isinstance(vol_change, (int, float)) and abs(vol_change) >= 0.01 else "-"
                    cambio_str = f"{cambio_24h:+.1f}%" if cambio_24h and isinstance(cambio_24h, (int, float)) and abs(cambio_24h) >= 0.01 else "-"
                    color_24h = get_color_unified(cambio_24h) if cambio_24h and abs(cambio_24h) >= 0.01 else "#888888"
                    color_vol = get_color_unified(vol_change) if vol_change and abs(vol_change) >= 0.01 else "#888888"
                    # Determinar color de fondo para filas óptimas (verde suave)
                    row_bg = 'rgba(0, 255, 136, 0.1)' if is_optimal_row(rsi, ema_dist, vol_change, heat) else 'transparent'
                    row_style = f'background: {row_bg}; border-bottom: 1px solid rgba(255,255,255,0.03);'
                    
                    # LEDs como spans circulares con resplandor (tamaño 8px) - solo mostrar si hay valor significativo
                    led_html_rsi = f'<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; {led_style_rsi} margin-right: 3px;"></span>' if (rsi and isinstance(rsi, (int, float)) and rsi > 0) else ''
                    led_html_ema = f'<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; {led_style_ema} margin-right: 3px;"></span>' if (ema_dist and isinstance(ema_dist, (int, float))) else ''
                    led_html_vol = f'<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; {led_style_vol} margin-right: 3px;"></span>' if (isinstance(vol_change, (int, float)) and abs(vol_change) >= 0.01) else ''
                    led_html_heat = f'<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; {led_style_heat} margin-right: 3px;"></span>' if heat > 0 else ''
                    
                    radar_html_left += f'<tr style="{row_style}">'
                    radar_html_left += f'<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">{real_idx}</td>'
                    radar_html_left += f'<td style="padding: 5px 3px; font-weight: 600; font-size: 11px; color: #FFFFFF;">{par_completo}</td>'
                    radar_html_left += f'<td style="padding: 5px 3px; font-size: 10px; color: {color_24h}; font-weight: 600;">{cambio_str}</td>'
                    radar_html_left += f'<td style="padding: 5px 3px; font-size: 10px; color: #FFFFFF;">{led_html_rsi}{rsi_str}</td>'
                    radar_html_left += f'<td style="padding: 5px 3px; font-size: 10px; color: #FFFFFF;">{led_html_ema}{ema_str}</td>'
                    radar_html_left += f'<td style="padding: 5px 3px; font-size: 10px; color: {color_vol}; font-weight: 600;">{led_html_vol}{vol_str}</td>'
                    radar_html_left += f'<td style="padding: 5px 3px; font-weight: 600; font-size: 10px; color: #FFFFFF;">{led_html_heat}{heat_str}</td>'
                    radar_html_left += '</tr>'
                
                radar_html_left += '</tbody></table>'
                st.markdown(radar_html_left, unsafe_allow_html=True)
            
            # COLUMNA DERECHA (Pares: 2, 4, 6...)
            with col2:
                radar_html_right = '<table style="width: 100%; border-collapse: collapse; color: #FFFFFF; font-size: 12px; background: #0a0a0a; position: relative;">'
                radar_html_right += '<thead><tr style="background: transparent; text-align: left; border: none;">'
                radar_html_right += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">#</th>'
                radar_html_right += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">ACTIVO</th>'
                radar_html_right += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">24h</th>'
                radar_html_right += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">RSI</th>'
                radar_html_right += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">EMA</th>'
                radar_html_right += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">VOL</th>'
                radar_html_right += '<th style="padding: 6px 4px; border: none; border-bottom: none; font-size: 11px; color: #FFFFFF;">HEAT</th>'
                radar_html_right += '</tr></thead><tbody>'
                
                for idx_display, item in enumerate(radar_pares, start=1):
                    real_idx = idx_display * 2  # 2, 4, 6, 8...
                    
                    if item is None:
                        # Fila vacía con guiones
                        radar_html_right += '<tr style="background: transparent; border-bottom: 1px solid rgba(255,255,255,0.03);">'
                        radar_html_right += f'<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">{real_idx}</td>'
                        radar_html_right += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 11px;">-</td>'
                        radar_html_right += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">-</td>'
                        radar_html_right += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">-</td>'
                        radar_html_right += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">-</td>'
                        radar_html_right += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">-</td>'
                        radar_html_right += '<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">-</td>'
                        radar_html_right += '</tr>'
                        continue
                    
                    origin = item.get('origin', item.get('from_currency', ''))
                    destination = item.get('destination', item.get('to_currency', ''))
                    par_completo = f"{origin}/{destination}" if origin and destination else destination or '-'
                    
                    rsi = item.get('rsi')
                    ema_dist = item.get('ema200_distance')
                    # MAPEO FORZADO DERECHA: Leer '24h' y 'vol_pct' (claves cortas del motor)
                    cambio_24h = item.get('24h')
                    if cambio_24h is None:
                        cambio_24h = (item.get('change_24h') or item.get('price_change_24h') or 
                                      item.get('priceChangePercent') or item.get('percentage') or 0.0)
                    vol_change = item.get('vol_pct')
                    if vol_change is None:
                        vol_change = (item.get('volume_change') or 
                                      item.get('volume_change_24h') or item.get('vol_change_pct') or 0.0)
                    heat = int(item.get('heat_score', 0) or 0)
                    
                    # LEDs con box-shadow
                    led_style_rsi = get_led_style_rsi(rsi)
                    led_style_ema = get_led_style_ema(ema_dist)
                    led_style_vol = get_led_style_unified(vol_change)
                    led_style_heat = get_led_style_heat(heat)
                    
                    # Valores formateados
                    heat_str = f"{heat}" if heat > 0 else "-"
                    rsi_str = f"{rsi:.0f}" if rsi and isinstance(rsi, (int, float)) and rsi > 0 else "-"
                    ema_str = f"{ema_dist:+.1f}" if ema_dist and isinstance(ema_dist, (int, float)) else "-"
                    vol_str = f"{vol_change:+.1f}%" if isinstance(vol_change, (int, float)) and abs(vol_change) >= 0.01 else "-"
                    cambio_str = f"{cambio_24h:+.1f}%" if cambio_24h and isinstance(cambio_24h, (int, float)) and abs(cambio_24h) >= 0.01 else "-"
                    color_24h = get_color_unified(cambio_24h) if cambio_24h and abs(cambio_24h) >= 0.01 else "#888888"
                    color_vol = get_color_unified(vol_change) if vol_change and abs(vol_change) >= 0.01 else "#888888"
                    
                    # Determinar color de fondo para filas óptimas (verde suave)
                    row_bg = 'rgba(0, 255, 136, 0.1)' if is_optimal_row(rsi, ema_dist, vol_change, heat) else 'transparent'
                    row_style = f'background: {row_bg}; border-bottom: 1px solid rgba(255,255,255,0.03);'
                    
                    # LEDs como spans circulares con resplandor (tamaño 8px) - solo mostrar si hay valor significativo
                    led_html_rsi = f'<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; {led_style_rsi} margin-right: 3px;"></span>' if (rsi and isinstance(rsi, (int, float)) and rsi > 0) else ''
                    led_html_ema = f'<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; {led_style_ema} margin-right: 3px;"></span>' if (ema_dist and isinstance(ema_dist, (int, float))) else ''
                    led_html_vol = f'<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; {led_style_vol} margin-right: 3px;"></span>' if (isinstance(vol_change, (int, float)) and abs(vol_change) >= 0.01) else ''
                    led_html_heat = f'<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; {led_style_heat} margin-right: 3px;"></span>' if heat > 0 else ''
                    
                    radar_html_right += f'<tr style="{row_style}">'
                    radar_html_right += f'<td style="padding: 5px 3px; color: #FFFFFF; font-size: 10px;">{real_idx}</td>'
                    radar_html_right += f'<td style="padding: 5px 3px; font-weight: 600; font-size: 11px; color: #FFFFFF;">{par_completo}</td>'
                    radar_html_right += f'<td style="padding: 5px 3px; font-size: 10px; color: {color_24h}; font-weight: 600;">{cambio_str}</td>'
                    radar_html_right += f'<td style="padding: 5px 3px; font-size: 10px; color: #FFFFFF;">{led_html_rsi}{rsi_str}</td>'
                    radar_html_right += f'<td style="padding: 5px 3px; font-size: 10px; color: #FFFFFF;">{led_html_ema}{ema_str}</td>'
                    radar_html_right += f'<td style="padding: 5px 3px; font-size: 10px; color: {color_vol}; font-weight: 600;">{led_html_vol}{vol_str}</td>'
                    radar_html_right += f'<td style="padding: 5px 3px; font-weight: 600; font-size: 10px; color: #FFFFFF;">{led_html_heat}{heat_str}</td>'
                    radar_html_right += '</tr>'
                
                radar_html_right += '</tbody></table>'
                st.markdown(radar_html_right, unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("No hay oportunidades de intercambio disponibles.")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ========== HUCHA DE ACTIVOS (Gráfica de Queso) ==========
    with hucha_cont.container():
        st.header("Hucha de Activos")
        
        try:
            hucha_path = ROOT_DIR / 'shared' / 'hucha_diversificada.json'
            if hucha_path.exists():
                with open(hucha_path, 'r', encoding='utf-8') as f:
                    hucha_list = json.load(f)

                if hucha_list and len(hucha_list) > 0:
                    # Preparar datos para gráfica de queso (coercionar valores)
                    hucha_df = pd.DataFrame(hucha_list)
                    hucha_df['currency'] = hucha_df.get('currency', 'N/A')
                    hucha_df['value_eur'] = pd.to_numeric(hucha_df.get('value_eur_at_save', 0), errors='coerce').fillna(0.0).astype(float)

                    # Filtrar valores > 0
                    hucha_df = hucha_df[hucha_df['value_eur'] > 0]

                    if len(hucha_df) > 0:
                        fig = go.Figure(data=[go.Pie(
                            labels=hucha_df['currency'],
                            values=hucha_df['value_eur'],
                            hole=0.4,
                            marker_colors=px.colors.qualitative.Set3
                        )])

                        fig.update_layout(
                            height=400,
                            plot_bgcolor='#f8f9fa',
                            paper_bgcolor='#f8f9fa',
                            font_color='#000000',
                            showlegend=True,
                            margin=dict(l=0, r=0, t=0, b=0)
                        )

                        st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No hay activos en la hucha.")
            else:
                st.info("No se encontró el archivo de hucha.")
        except Exception as e:
            st.info(f"No se pudo cargar la hucha: {e}")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
    # ========== HISTORIAL Y GRÁFICA ==========
    with bottom_cont.container():
        col_historial, col_grafica = st.columns([0.65, 0.35])
        
        with col_historial:
            st.header("Historial de Eventos")
            
            bitacora_events = load_bitacora()
            
            historial_html = '<div class="historial-box">'
            if bitacora_events:
                for event in bitacora_events[-30:]:
                    event_formatted = event
                    css_class = ''
                    
                    if event.startswith('[⛽ MANAGE_GAS]') or event.startswith('⛽ MANAGE_GAS'):
                        css_class = 'gas-critical'
                        event_text = event.split(']', 1)[-1] if ']' in event else event
                        event_formatted = f'⛽ <strong>Manage Gas:</strong> {event_text.strip()}'
                    elif event.startswith('[DIVERSIFICACIÓN]') or 'DIVERSIFICACIÓN' in event.upper():
                        css_class = 'diversificacion-tag'
                        event_text = event.split(']', 1)[-1] if ']' in event else event
                        event_formatted = f'⚡ <strong>DIVERSIFICACIÓN:</strong> {event_text.strip()}'
                    elif event.startswith('[💎 HUCHA_SAVE]') or 'HUCHA' in event.upper():
                        css_class = 'hucha-tag'
                        event_text = event.split(']', 1)[-1] if ']' in event else event
                        event_formatted = f'💎 <strong>HUCHA:</strong> {event_text.strip()}'
                    elif "Compra:" in event:
                        event_formatted = f"🟢 <strong>Compra realizada:</strong> {event.replace('Compra:', '').strip()}"
                    elif "Venta:" in event:
                        event_formatted = f"🔴 <strong>Venta realizada:</strong> {event.replace('Venta:', '').strip()}"
                    
                    historial_html += f'<div class="historial-event {css_class}">{event_formatted}</div>'
            else:
                historial_html += '<div style="color: var(--muted);">No hay eventos recientes</div>'
            
            historial_html += '</div>'
            st.markdown(historial_html, unsafe_allow_html=True)
        
        with col_grafica:
            st.header("Evolución del Fondo Total")
            
            snapshots_df = get_portfolio_snapshots(limit=100)
            
            if not snapshots_df.empty and len(snapshots_df) > 1:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=snapshots_df['timestamp'],
                    y=snapshots_df['total_value'],
                    mode='lines',
                    name='Fondo Total',
                    line=dict(color='#00FF88', width=2),
                    fill='tozeroy',
                    fillcolor='rgba(0,255,136,0.1)'
                ))
                
                fig.update_layout(
                    height=400,
                    plot_bgcolor='#000000',
                    paper_bgcolor='#000000',
                    font_color='#ffffff',
                    xaxis=dict(
                        gridcolor='rgba(255,255,255,0.1)',
                        title='Tiempo'
                    ),
                    yaxis=dict(
                        gridcolor='rgba(255,255,255,0.1)',
                        title='Valor (€)'
                    ),
                    margin=dict(l=0, r=0, t=0, b=0),
                    showlegend=False
                )
                
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No hay datos suficientes para mostrar la evolución.")


if __name__ == "__main__":
    main()

