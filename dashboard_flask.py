#!/usr/bin/env python3
"""
Centro de Mando Profesional botCeibe - Dashboard de Solo Lectura
Refleja el sistema de portafolio dinámico, hucha selectiva y radar de calor
"""
from flask import Flask, render_template_string, send_from_directory, Response, stream_with_context
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# Agregar el directorio raíz al path
ROOT_DIR = Path(__file__).parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Importar módulos necesarios
try:
    from database import Database
    from bot_config import DB_PATH
    HAS_DATABASE = True
except ImportError:
    HAS_DATABASE = False
    print("⚠️ No se pudo importar Database. Los slots se mostrarán desde state.json")

try:
    from router import get_pair_info, get_available_pairs
    HAS_ROUTER = True
except ImportError:
    HAS_ROUTER = False
    print("⚠️ No se pudo importar router. El filtrado de pares puede estar limitado")

app = Flask(__name__)

# HTML Template con diseño profesional Dark Mode
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>botCeibe - Centro de Mando</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif; 
            background: #0a0a0a; 
            color: #e0e0e0; 
            padding: 20px; 
            line-height: 1.6;
            font-size: 14px;
        }
        .container { max-width: 1600px; margin: 0 auto; }
        .header { 
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 25px;
            border: 1px solid #2a2a3e;
        }
        h1 { 
            color: #00FF88; 
            font-size: 2.2em; 
            margin-bottom: 10px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }
        .subtitle {
            color: #888;
            font-size: 0.9em;
        }
        h2 { 
            color: #00FF88; 
            margin: 25px 0 15px; 
            font-size: 1.4em;
            font-weight: 600;
            border-bottom: 2px solid #2a2a3e;
            padding-bottom: 8px;
        }
        
        /* RESUMEN GENERAL - 5 Métricas - Grid Reorganizado */
        .summary-grid {
            display: grid;
            grid-template-columns: 2fr 0.8fr 1fr 1fr 1fr;
            gap: 15px;
            margin: 25px 0;
        }
        @media (max-width: 1400px) {
            .summary-grid {
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            }
        }
        .summary-card {
            background: #1a1a2e;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #2a2a3e;
            transition: transform 0.2s, border-color 0.2s;
        }
        .summary-card:hover {
            transform: translateY(-2px);
            border-color: #00FF88;
        }
        .summary-label {
            color: #888;
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
            font-weight: 600;
        }
        .summary-value {
            color: #00FF88;
            font-size: 1.8em;
            font-weight: 700;
            margin-bottom: 5px;
        }
        .summary-subvalue {
            color: #666;
            font-size: 0.85em;
            margin-top: 5px;
        }
        /* Luz LED de Estado de Mercado */
        .market-led {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 8px;
            box-shadow: 0 0 8px currentColor;
        }
        .market-led-green { 
            background: #00FF88; 
            color: #00FF88;
            box-shadow: 0 0 8px #00FF88, 0 0 12px #00FF88;
        }
        .market-led-orange { 
            background: #FF8844; 
            color: #FF8844;
            box-shadow: 0 0 8px #FF8844;
        }
        .market-led-red { 
            background: #FF4444; 
            color: #FF4444;
            box-shadow: 0 0 8px #FF4444, 0 0 12px #FF4444;
        }
        
        /* TABLA SLOTS ACTIVOS - Minimalista */
        .table-container {
            background: #1a1a2e;
            border-radius: 10px;
            padding: 20px;
            border: 1px solid #2a2a3e;
            margin: 20px 0;
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: transparent;
        }
        th {
            background: #2a2a3e;
            color: #00FF88;
            padding: 10px 12px;
            text-align: left;
            font-weight: 600;
            font-size: 0.8em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 2px solid #00FF88;
        }
        td {
            padding: 10px 12px;
            border-bottom: 1px solid #2a2a3e;
            color: #FFFFFF;
            font-size: 0.9em;
        }
        tr:hover {
            background: #2a2a3e;
        }
        .pnl-positive { color: #00FF88; font-weight: 600; }
        .pnl-negative { color: #FF4444; font-weight: 600; }
        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: 600;
        }
        .status-vigilando { background: #333; color: #888; }
        .status-protegido { background: #664400; color: #FFAA00; }
        .status-trailing { background: #004422; color: #00FF88; }
        
        /* RADAR DE OPORTUNIDAD */
        .radar-container {
            background: #1a1a2e;
            border-radius: 10px;
            padding: 20px;
            border: 1px solid #2a2a3e;
            margin: 20px 0;
        }
        /* Heat Map del Radar */
        .radar-hot {
            background: linear-gradient(90deg, rgba(0, 255, 136, 0.15) 0%, rgba(0, 255, 136, 0.05) 100%);
            border-left: 4px solid #00FF88;
        }
        .radar-warm {
            background: linear-gradient(90deg, rgba(136, 255, 136, 0.1) 0%, rgba(136, 255, 136, 0.02) 100%);
            border-left: 2px solid #88FF88;
        }
        .radar-normal {
            background: #1a1a2e;
        }
        .radar-row-top5 {
            border-left: 4px solid #00FF88;
        }
        .radar-row-semi {
            border-left: 2px solid #88FF88;
        }
        .sync-indicator {
            color: #666;
            font-size: 0.75em;
            margin-top: 10px;
            text-align: right;
        }
        .sync-indicator.active {
            color: #00FF88;
        }
        
        /* DISTRIBUCIÓN - Gráficos Pie Charts */
        .distribution-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin: 20px 0;
        }
        .chart-container {
            background: #1a1a2e;
            border-radius: 10px;
            padding: 20px;
            border: 1px solid #2a2a3e;
        }
        .chart-legend {
            margin-top: 15px;
        }
        .legend-item {
            display: grid;
            grid-template-columns: 60px 100px 80px 120px 100px;
            gap: 10px;
            padding: 8px;
            border-bottom: 1px solid #2a2a3e;
            font-size: 0.85em;
            align-items: center;
        }
        .legend-header {
            display: grid;
            grid-template-columns: 60px 100px 80px 120px 100px;
            gap: 10px;
            padding: 8px;
            background: #2a2a3e;
            font-weight: 600;
            font-size: 0.8em;
            text-transform: uppercase;
            color: #00FF88;
        }
        .legend-color {
            width: 16px;
            height: 16px;
            border-radius: 3px;
            margin-right: 10px;
            display: inline-block;
        }
        .pie-chart {
            width: 200px;
            height: 200px;
            border-radius: 50%;
            margin: 20px auto;
            background: conic-gradient(
                #00FF88 0deg 90deg,
                #FF8844 90deg 180deg,
                #FF4444 180deg 270deg,
                #888888 270deg 360deg
            );
        }
        
        /* HISTORIAL DE EVENTOS */
        .event-item {
            padding: 12px;
            margin: 8px 0;
            border-left: 3px solid #333;
            background: #111;
            border-radius: 4px;
            font-size: 0.9em;
            line-height: 1.6;
        }
        .event-time {
            color: #888;
            font-size: 0.85em;
            margin-right: 10px;
        }
        .event-type {
            font-weight: 600;
            margin-right: 10px;
        }
        .event-gas-emergency { border-left-color: #FF4444; }
        .event-gas-retained { border-left-color: #888888; color: #888888 !important; }
        .event-swap-diversificacion { border-left-color: #FFFFFF; }
        .event-swap-centinela { border-left-color: #FF4444; }
        .event-hucha { border-left-color: #FFD700; }
        .event-compra { border-left-color: #FFFFFF; }
        .event-venta { border-left-color: #00FF88; }
        .events-container {
            background: #1a1a2e;
            border-radius: 10px;
            padding: 20px;
            border: 1px solid #2a2a3e;
            margin: 20px 0;
            max-height: 400px;
            overflow-y: auto;
        }
        .events-filters {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }
        .filter-select {
            background: #2a2a3e;
            border: 1px solid #3a3a4e;
            color: #FFFFFF;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.85em;
            cursor: pointer;
        }
        .filter-select:hover {
            border-color: #00FF88;
        }
        .expand-events {
            background: #2a2a3e;
            border: 1px solid #3a3a4e;
            color: #00FF88;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85em;
            margin-top: 10px;
        }
        .expand-events:hover {
            background: #3a3a4e;
            border-color: #00FF88;
        }
        .event-timestamp {
            color: #888;
            font-size: 0.8em;
            width: 160px;
            display: inline-block;
            font-family: monospace;
        }
        .event-item {
            padding: 10px;
            border-left: 3px solid #2a2a3e;
            margin-bottom: 8px;
            font-size: 0.9em;
        }
        .event-swap { border-left-color: #00FF88; }
        .event-gas { border-left-color: #FFAA00; }
        .event-hucha { border-left-color: #FFD700; }
        .event-protection { border-left-color: #FF8844; }
        .event-gas-emergency { border-left-color: #FF4444; }
        .event-gas-retained { border-left-color: #888888; color: #888888 !important; }
        .event-swap-diversificacion { border-left-color: #FFFFFF; }
        .event-swap-centinela { border-left-color: #FF4444; }
        .event-compra { border-left-color: #FFFFFF; }
        .event-venta { border-left-color: #00FF88; }
        .event-time {
            color: #888;
            font-size: 0.85em;
            margin-right: 10px;
        }
        .event-type {
            font-weight: 600;
            margin-right: 8px;
        }
        .event-swap .event-type { color: #00FF88; }
        .event-gas .event-type { color: #FFAA00; }
        .event-hucha .event-type { color: #FFD700; }
        .event-gas-emergency .event-type { color: #FF4444; }
        .event-gas-retained .event-type { color: #888888; }
        .event-swap-diversificacion .event-type { color: #FFFFFF; }
        .event-swap-centinela .event-type { color: #FF4444; }
        .event-compra .event-type { color: #FFFFFF; }
        .event-venta .event-type { color: #00FF88; }
        .event-protection .event-type { color: #FF8844; }
        
        .timestamp {
            color: #666;
            font-size: 0.8em;
            margin-top: 25px;
            text-align: center;
            padding: 15px;
            border-top: 1px solid #2a2a3e;
        }
        /* Footer de Información Técnica */
        .footer-info {
            background: #1a1a2e;
            border-radius: 10px;
            padding: 15px 20px;
            border: 1px solid #2a2a3e;
            margin-top: 25px;
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 20px;
            font-size: 0.8em;
        }
        .footer-section {
            border-right: 1px solid #2a2a3e;
            padding-right: 20px;
        }
        .footer-section:last-child {
            border-right: none;
        }
        .footer-title {
            color: #00FF88;
            font-weight: 600;
            margin-bottom: 8px;
            text-transform: uppercase;
            font-size: 0.85em;
        }
        .footer-item {
            color: #888;
            margin: 4px 0;
            font-size: 0.85em;
        }
        .footer-item strong {
            color: #FFFFFF;
        }
        
        /* Indicadores técnicos visuales */
        .indicator-icon {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 5px;
            vertical-align: middle;
        }
        .indicator-green-intense { background: #00FF88; box-shadow: 0 0 4px #00FF88; }
        .indicator-green-soft { background: #88FF88; }
        .indicator-white { background: #CCCCCC; }
        .indicator-red { background: #FF4444; }
        
        /* Botón expandir radar (sin JavaScript) */
        details {
            margin-top: 15px;
        }
        details summary {
            background: #2a2a3e;
            border: 1px solid #3a3a4e;
            color: #00FF88;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.3s;
            list-style: none;
        }
        details summary::-webkit-details-marker {
            display: none;
        }
        details summary::before {
            content: "▶ ";
            margin-right: 8px;
            transition: transform 0.3s;
        }
        details[open] summary::before {
            transform: rotate(90deg);
        }
        details summary:hover {
            background: #3a3a4e;
            border-color: #00FF88;
        }
        .radar-all {
            display: table-row-group;
        }
        
        @media (max-width: 1200px) {
            .distribution-grid { grid-template-columns: 1fr; }
        }
        @media (max-width: 768px) {
            .summary-grid { grid-template-columns: 1fr; }
            body { padding: 10px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 botCeibe - Centro de Mando</h1>
            <div class="subtitle">Dashboard Profesional de Solo Lectura | Auto-actualización cada 10s</div>
        </div>
        
        {{ content|safe }}
        
        <div class="timestamp">
            Última actualización: {{ timestamp }} | Sincronizado hace {{ sync_ago }}
        </div>
        
        <!-- Footer de Información Técnica -->
        <div class="footer-info">
            <div class="footer-section">
                <div class="footer-title">Info Mercado</div>
                <div class="footer-item"><strong>Verde:</strong> BTC > +0.2%</div>
                <div class="footer-item"><strong>Naranja:</strong> BTC entre +0.2% y -0.5%</div>
                <div class="footer-item"><strong>Rojo:</strong> BTC < -0.5% (Bloqueo)</div>
            </div>
            <div class="footer-section">
                <div class="footer-title">Info Gas</div>
                <div class="footer-item"><strong>&lt;5%:</strong> Pasivo</div>
                <div class="footer-item"><strong>&lt;2%:</strong> Activo</div>
                <div class="footer-item"><strong>&lt;1%:</strong> Emergencia</div>
            </div>
            <div class="footer-section">
                <div class="footer-title">Info Radar</div>
                <div class="footer-item"><strong>RSI Verde:</strong> &gt;45 (Fuerza alcista)</div>
                <div class="footer-item"><strong>RSI Blanco:</strong> &gt;30 (Neutral)</div>
                <div class="footer-item"><strong>RSI Rojo:</strong> &lt;30 (Sobreventa)</div>
                <div class="footer-item"><strong>EMA Verde:</strong> Tendencia confirmada</div>
                <div class="footer-item"><strong>Volumen Verde:</strong> Alto (Confirmación)</div>
                <div class="footer-item"><strong>Info Heat:</strong> RSI (40%) | EMA (30%) | VOL (20%) | Bonus (10%)</div>
            </div>
        </div>
    </div>
</body>
</html>
'''

def load_state():
    """Carga el estado desde shared/state.json"""
    state_path = ROOT_DIR / 'shared' / 'state.json'
    if state_path.exists():
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f'Error cargando estado: {e}')
            return None
    return None


@app.route('/stream')
def stream():
    """SSE stream que emite actualizaciones parciales según frecuencias:
    - summary: cada 60s
    - slots: cada 5s
    - radar por zona: 'muy_caliente' 10s, 'caliente' 30s, 'fria' 60s, 'muy_fria' 120s
    Emite eventos con nombre 'summary', 'slots' y 'radar' (campo 'zone').
    """
    def events():
        last_summary = 0
        last_slots = 0
        last_zone = {'muy_caliente': 0, 'caliente': 0, 'fria': 0, 'muy_fria': 0}
        zone_freqs = {'muy_caliente': 10, 'caliente': 30, 'fria': 60, 'muy_fria': 120}
        try:
            while True:
                state = load_state() or {}
                now = time.time()

                # Summary every 60s
                if now - last_summary >= 60:
                    summary = {
                        'timestamp': state.get('timestamp'),
                        'market_status': state.get('market_status'),
                        'gas_status': state.get('gas_status'),
                        'free_cash_eur': state.get('free_cash_eur')
                    }
                    yield f"event: summary\ndata: {json.dumps(summary)}\n\n"
                    last_summary = now

                # Slots every 5s
                if now - last_slots >= 5:
                    slots = {'open_trades': state.get('open_trades', [])}
                    yield f"event: slots\ndata: {json.dumps(slots)}\n\n"
                    last_slots = now

                # Radar por zonas
                radar_data = state.get('radar_data', [])
                for zone, freq in zone_freqs.items():
                    if now - last_zone[zone] >= freq:
                        entries = [r for r in radar_data if r.get('zone') == zone]
                        payload = {'zone': zone, 'entries': entries}
                        yield f"event: radar\ndata: {json.dumps(payload)}\n\n"
                        last_zone[zone] = now

                time.sleep(1)
        except GeneratorExit:
            # Cliente cerrado
            return
        except Exception:
            return

    return Response(stream_with_context(events()), mimetype='text/event-stream')

def load_hucha():
    """Carga la hucha diversificada"""
    hucha_path = ROOT_DIR / 'shared' / 'hucha_diversificada.json'
    if hucha_path.exists():
        try:
            with open(hucha_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def load_bitacora():
    """Carga los últimos eventos de bitacora.txt"""
    bitacora_path = ROOT_DIR / 'bitacora.txt'
    if bitacora_path.exists():
        try:
            with open(bitacora_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                return [line.strip() for line in lines[-30:] if line.strip()]
        except:
            return []
    return []

def format_currency(value):
    """Formatea un valor como moneda"""
    if value is None or value == 0:
        return '0.00 €'
    return f'{value:,.2f} €'

def format_number(value, decimals=8):
    """Formatea un número"""
    if value is None:
        return 'N/A'
    return f'{value:,.{decimals}f}'

def calculate_sync_ago(timestamp_str):
    """Calcula hace cuánto tiempo fue la última sincronización"""
    try:
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        now = datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.now()
        delta = now - timestamp
        if delta.total_seconds() < 60:
            return f"{int(delta.total_seconds())}s"
        elif delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() / 60)}min"
        else:
            return f"{int(delta.total_seconds() / 3600)}h"
    except:
        return "N/A"

def generate_summary(state):
    """Genera la sección de Resumen General con 5 métricas"""
    content = []
    content.append('<div class="summary-grid">')
    
    # 1. FONDOS
    dynamic_inventory = state.get('dynamic_inventory', [])
    gas_bnb = state.get('gas_bnb', {})
    treasury = state.get('treasury', {})
    
    # Capital disponible (excluyendo Gas y Hucha)
    available_capital = sum(item.get('value_eur', 0) for item in dynamic_inventory)
    total_funds = available_capital + gas_bnb.get('value_eur', 0) + treasury.get('total_eur', 0)
    
    content.append('<div class="summary-card">')
    content.append('<div class="summary-label">FONDOS</div>')
    content.append(f'<div class="summary-value">{format_currency(available_capital)}</div>')
    content.append(f'<div class="summary-subvalue">Fondo Total: {format_currency(total_funds)}</div>')
    content.append('</div>')
    
    # 2. SLOTS (Dinámico) - Solo número de slots activos
    active_slots = len([item for item in dynamic_inventory if item.get('value_eur', 0) > 10])
    
    content.append('<div class="summary-card">')
    content.append('<div class="summary-label">SLOTS</div>')
    content.append(f'<div class="summary-value">{active_slots}</div>')
    content.append('</div>')
    
    # 3. ESTADO DEL MERCADO - Luz LED
    market_status = state.get('market_status', {})
    btc_change = market_status.get('btc_change', 0)
    
    # Determinar color LED según umbrales
    if btc_change > 0.2:
        led_class = 'market-led-green'
    elif btc_change > -0.5:
        led_class = 'market-led-orange'
    else:
        led_class = 'market-led-red'
    
    content.append('<div class="summary-card">')
    content.append('<div class="summary-label">ESTADO DE MERCADO</div>')
    content.append(f'<div class="summary-value"><span class="market-led {led_class}"></span>BTC: {btc_change:+.2f}%</div>')
    content.append('</div>')
    
    # 4. GAS (BNB)
    gas_status = state.get('gas_status', {})
    gas_percent = gas_status.get('percentage', 0)
    gas_value_eur = gas_bnb.get('value_eur', 0)
    gas_color = gas_status.get('color', '#00FF88')
    
    content.append('<div class="summary-card">')
    content.append('<div class="summary-label">GAS (BNB)</div>')
    content.append(f'<div class="summary-value" style="color: {gas_color}">{gas_percent:.2f}%</div>')
    content.append(f'<div class="summary-subvalue">{format_currency(gas_value_eur)}</div>')
    content.append('</div>')
    
    # 5. RESERVA (Hucha)
    hucha_total = treasury.get('total_eur', 0)
    
    content.append('<div class="summary-card">')
    content.append('<div class="summary-label">RESERVA</div>')
    content.append(f'<div class="summary-value">{format_currency(hucha_total)}</div>')
    content.append(f'<div class="summary-subvalue">Hucha diversificada</div>')
    content.append('</div>')
    
    content.append('</div>')
    return '\n'.join(content)

def generate_slots_table(state):
    """
    🎯 Genera la tabla de SLOTS ACTIVOS mostrando operaciones individuales desde la DB.
    Cada fila = una operación abierta (no el balance total del activo).
    """
    content = []
    content.append('<h2>📈 SLOTS ACTIVOS (Gestión de Posición)</h2>')
    content.append('<div class="table-container">')
    
    # 🎯 Cargar trades activos desde la base de datos
    active_trades = []
    if HAS_DATABASE:
        try:
            db = Database(DB_PATH)
            active_trades = db.get_all_active_trades()
        except Exception as e:
            print(f"⚠️ Error cargando trades desde DB: {e}")
            # Fallback a state.json
            active_trades = state.get('open_trades', [])
    else:
        # Fallback a state.json
        active_trades = state.get('open_trades', [])
    
    if not active_trades:
        content.append('<div style="padding: 20px; text-align: center; color: #666;">No hay operaciones activas</div>')
        content.append('</div>')
        return '\n'.join(content)
    
    # 🎯 Calcular total del portfolio para % FONDO
    total_portfolio_eur = state.get('total_portfolio_value', 0)
    if total_portfolio_eur <= 0:
        # Calcular desde dynamic_inventory si no está disponible
        dynamic_inventory = state.get('dynamic_inventory', [])
        total_portfolio_eur = sum(item.get('value_eur', 0) for item in dynamic_inventory)
        gas_bnb = state.get('gas_bnb', {})
        treasury = state.get('treasury', {})
        total_portfolio_eur += gas_bnb.get('value_eur', 0) + treasury.get('total_eur', 0)
    
    MAX_POSITION_PCT = 0.25  # 25% máximo por posición
    
    content.append('<table>')
    content.append('<tr>')
    content.append('<th>FECHA/HORA</th>')
    content.append('<th>ACTIVO</th>')
    content.append('<th>CANTIDAD</th>')
    content.append('<th>VALOR €</th>')
    content.append('<th>PNL %</th>')
    content.append('</tr>')
    
    # Obtener precios actuales desde state
    prices = state.get('prices', {})
    
    # Intentar importar Vault para obtener precios actuales
    try:
        from vault import Vault
        from database import Database
        vault = Vault(Database(DB_PATH))
        has_vault = True
    except:
        has_vault = False
        vault = None
    
    for trade in active_trades:
        slot_id = trade.get('slot_id', 0)
        base_asset = trade.get('base_asset', 'N/A')
        target_asset = trade.get('target_asset', 'N/A')
        symbol = trade.get('symbol', f'{target_asset}/{base_asset}')
        
        # Cantidad de la operación (no el balance total)
        amount = trade.get('amount', 0)
        entry_price = trade.get('entry_price', 0)
        initial_fiat_value = trade.get('initial_fiat_value', 0)
        
        # 🎯 Obtener precio actual: Prioridad 1) Vault (precio real), 2) prices dict, 3) calcular desde valor
        current_price = 0
        if has_vault and vault:
            try:
                # Obtener precio actual desde Vault (más preciso)
                current_price = vault.get_asset_value(target_asset, 1.0, base_asset)
                if current_price <= 0:
                    # Si no hay par directo, obtener en EUR y convertir
                    current_price_eur = vault.get_asset_value(target_asset, 1.0, 'EUR')
                    if current_price_eur > 0 and base_asset != 'EUR':
                        base_price_eur = vault.get_asset_value(base_asset, 1.0, 'EUR')
                        if base_price_eur > 0:
                            current_price = current_price_eur / base_price_eur
            except Exception as e:
                print(f"⚠️ Error obteniendo precio desde Vault para {target_asset}: {e}")
        
        # Fallback: Intentar desde prices dict
        if current_price <= 0:
            price_key = f'{target_asset.lower()}_price'
            current_price = prices.get(price_key, 0)
        
        # Fallback: Calcular desde current_value_eur si está en el trade
        if current_price <= 0 and amount > 0:
            current_value_eur = trade.get('current_value_eur', 0)
            if current_value_eur > 0:
                current_price = current_value_eur / amount
            else:
                # Último fallback: usar entry_price si no hay datos actuales
                current_price = entry_price
        
        # 🎯 Calcular valor actual de la posición usando precio actualizado
        if current_price > 0 and amount > 0:
            # Si base_asset es EUR, el valor ya está en EUR
            if base_asset == 'EUR':
                current_value_eur = current_price * amount
            else:
                # Convertir a EUR
                if has_vault and vault:
                    try:
                        current_value_eur = vault.get_asset_value(target_asset, amount, 'EUR')
                    except:
                        # Fallback: usar precio en base_asset y convertir
                        base_price_eur = vault.get_asset_value(base_asset, 1.0, 'EUR') if has_vault else 0
                        if base_price_eur > 0:
                            current_value_eur = (current_price * amount) * base_price_eur
                        else:
                            current_value_eur = initial_fiat_value
                else:
                    current_value_eur = initial_fiat_value
        else:
            current_value_eur = initial_fiat_value  # Fallback
        
        # Calcular PNL %
        if initial_fiat_value > 0:
            pnl_percent = ((current_value_eur - initial_fiat_value) / initial_fiat_value) * 100
        else:
            pnl_percent = 0
        
        # 🎯 Calcular % FONDO (porcentaje sobre el total del portfolio)
        fund_percent = (current_value_eur / total_portfolio_eur * 100) if total_portfolio_eur > 0 else 0
        is_overexposed = fund_percent > (MAX_POSITION_PCT * 100)
        percent_color = '#FF4444' if is_overexposed else '#00FF88' if fund_percent > 20 else '#FFFFFF'
        
        # Colores para PNL
        pnl_color = '#00FF88' if pnl_percent > 0 else '#FF4444' if pnl_percent < 0 else '#FFFFFF'
        pnl_symbol = '+' if pnl_percent > 0 else ''
        
        # Resaltar fila si está sobreexpuesta
        row_style = 'background: #4a1a1a;' if is_overexposed else ''
        
        # Fecha/Hora de apertura
        created_at = trade.get('created_at', '')
        if created_at:
            try:
                if isinstance(created_at, str):
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    fecha_hora = dt.strftime('%Y-%m-%d %H:%M')
                else:
                    fecha_hora = str(created_at)
            except:
                fecha_hora = 'N/A'
        else:
            fecha_hora = 'N/A'
        
        # Formatear valores (minimalista)
        amount_str = format_number(amount, 8)
        value_str = format_currency(initial_fiat_value)  # Valor en apertura
        pnl_str = f'{pnl_percent:+.2f}%'
        pnl_class = 'pnl-positive' if pnl_percent >= 0 else 'pnl-negative'
        
        content.append('<tr>')
        content.append(f'<td>{fecha_hora}</td>')
        content.append(f'<td><strong>{symbol}</strong></td>')
        content.append(f'<td>{amount_str}</td>')
        content.append(f'<td>{value_str}</td>')
        content.append(f'<td class="{pnl_class}">{pnl_str}</td>')
        content.append('</tr>')
    
    content.append('</table>')
    content.append('</div>')
    return '\n'.join(content)

def _get_indicator_icon(value, indicator_type):
    """
    Retorna el icono de color según el valor del indicador.
    
    Args:
        value: Valor del indicador (RSI, EMA distance, etc.)
        indicator_type: 'rsi', 'ema', 'volume'
    
    Returns:
        HTML del icono con clase CSS
    """
    if indicator_type == 'rsi':
        # RSI: Verde si < 30 (sobreventa), Rojo si > 70 (sobrecompra)
        if value is None:
            return '<span class="indicator-icon indicator-white"></span>'
        if value < 30:
            return '<span class="indicator-icon indicator-green-intense"></span>'
        elif value < 40:
            return '<span class="indicator-icon indicator-green-soft"></span>'
        elif value > 70:
            return '<span class="indicator-icon indicator-red"></span>'
        else:
            return '<span class="indicator-icon indicator-white"></span>'
    
    elif indicator_type == 'ema':
        # EMA Distance: Verde si negativo (precio por debajo de EMA, oportunidad de compra)
        if value is None:
            return '<span class="indicator-icon indicator-white"></span>'
        if value < -5:
            return '<span class="indicator-icon indicator-green-intense"></span>'
        elif value < -2:
            return '<span class="indicator-icon indicator-green-soft"></span>'
        elif value > 10:
            return '<span class="indicator-icon indicator-red"></span>'
        else:
            return '<span class="indicator-icon indicator-white"></span>'
    
    elif indicator_type == 'volume':
        # Volume: Verde si alto, Rojo si bajo
        if value is None or value == 'medium':
            return '<span class="indicator-icon indicator-white"></span>'
        if value == 'high':
            return '<span class="indicator-icon indicator-green-intense"></span>'
        elif value == 'normal':
            return '<span class="indicator-icon indicator-green-soft"></span>'
        else:
            return '<span class="indicator-icon indicator-red"></span>'
    
    return '<span class="indicator-icon indicator-white"></span>'

def generate_radar(state):
    """
    🎯 Genera la sección de RADAR DE OPORTUNIDADES con análisis técnico profundo.
    Filtrado inteligente: solo pares directos con monedas en inventario.
    Top 15 por defecto, botón para ver todos.
    Indicadores visuales: EMA, RSI, Volumen con iconos de colores.
    """
    content = []
    content.append('<h2>📡 RADAR DE OPORTUNIDADES (Análisis Técnico)</h2>')
    content.append('<div class="radar-container">')
    
    radar_data = state.get('radar_data', [])
    if not radar_data:
        content.append('<div style="padding: 20px; text-align: center; color: #666;">No hay oportunidades detectadas</div>')
        content.append('</div>')
        return '\n'.join(content)
    
    # 🎯 FILTRADO INTELIGENTE: Solo pares directos con monedas en inventario
    dynamic_inventory = state.get('dynamic_inventory', [])
    wallet_assets = {item.get('currency') for item in dynamic_inventory if item.get('value_eur', 0) > 10}
    
    # También incluir FIAT disponible
    free_cash_eur = state.get('free_cash_eur', 0)
    if free_cash_eur > 10:
        wallet_assets.add('EUR')
        wallet_assets.add('USDC')
    
    filtered_radar = []
    for item in radar_data:
        origin = item.get('from_currency') or item.get('origin', '')
        destination = item.get('to_currency') or item.get('currency', '')
        
        # Verificar que el origen esté en la wallet
        if origin in wallet_assets:
            # Verificar existencia directa del par (si hay router)
            pair = f"{origin}/{destination}" if origin != destination else None
            include_item = False

            if pair:
                if HAS_ROUTER:
                    # Aceptar si existe par directo en cualquiera de las direcciones
                    if get_pair_info(pair) or get_pair_info(f"{destination}/{origin}"):
                        include_item = True
                else:
                    # Sin router, permitir mostrar (fallback)
                    include_item = True

            # Si no hay par directo, permitir entradas virtuales (triangulación / fiat)
            if not include_item:
                note = (item.get('note') or '').lower()
                if 'triangulation' in note or 'via_fiat' in note or 'fiat_comparison' in note:
                    include_item = True
                # También aceptar si el campo 'pair' (swap_pair) contiene el origen — indica ruta virtual
                elif item.get('pair') and origin in item.get('pair'):
                    include_item = True

            if include_item:
    # Ordenar por heat_score descendente (mayor a menor calor)
    filtered_radar.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
    
    if not filtered_radar:
        content.append('<div style="padding: 20px; text-align: center; color: #666;">No hay oportunidades con origen disponible en wallet</div>')
        content.append('</div>')
        return '\n'.join(content)
    
    # Separar top 15 y resto
    top_15 = filtered_radar[:15]
    rest = filtered_radar[15:] if len(filtered_radar) > 15 else []
    
        content.append('<table>')
    content.append('<tr>')
    content.append('<th>ACTIVO</th>')
    content.append('<th>Heat</th>')
    content.append('<th>DIST. EMA</th>')
    content.append('<th>RSI</th>')
    content.append('<th>VOLUMEN</th>')
    content.append('<th>ESTADO</th>')
    content.append('</tr>' )
    
    # Renderizar top 15 con Heat Map
    for i, item in enumerate(top_15):
        swap_label = item.get('swap_label', f"{item.get('from_currency', 'N/A')} → {item.get('to_currency', 'N/A')}")
        heat = item.get('heat_score', 0)
        price = item.get('current_price', 0)
        
        # Obtener indicadores técnicos
        rsi = item.get('rsi')
        ema_distance = item.get('ema200_distance')
        volume_status = item.get('volume_status', 'medium')
        triple_green = item.get('triple_green', False)
        
        # Heat Map: Top 5 muy calientes, siguientes 10 semicalientes
        if i < 5:
            row_class = 'radar-row-top5'
        elif i < 15:
            row_class = 'radar-row-semi'
        else:
            row_class = ''
        
        heat_color = '#00FF88' if heat >= 85 else '#88FF88' if heat >= 70 else '#FFFFFF'
        
        # Estado: Triple Verde, Compra, Venta, Normal
        estado = 'Normal'
        estado_color = '#FFFFFF'
        if triple_green:
            estado = 'Triple Verde ✅'
            estado_color = '#00FF88'
        elif rsi is not None:
            if rsi < 30:
                estado = 'Sobreventa'
                estado_color = '#00FF88'
            elif rsi > 70:
                estado = 'Sobrecompra'
                estado_color = '#FF4444'
        
        content.append(f'<tr class="{row_class}">')
        content.append(f'<td><strong style="color: #FFFFFF;">{swap_label}</strong></td>')
        content.append(f'<td style="color: {heat_color}; font-weight: 600;">{heat}</td>')
        content.append(f'<td>{_get_indicator_icon(ema_distance, "ema")}{format_number(ema_distance, 2) if ema_distance is not None else "N/A"}%</td>')
        content.append(f'<td>{_get_indicator_icon(rsi, "rsi")}{format_number(rsi, 1) if rsi is not None else "N/A"}</td>')
        content.append(f'<td>{_get_indicator_icon(volume_status, "volume")}{volume_status if volume_status else "N/A"}</td>')
        content.append(f'<td style="color: {estado_color};">{estado}</td>')
        content.append('</tr>')
    
    content.append('</table>')
    
    # Botón para ver todos los pares (sin JavaScript, usando HTML5 details)
    if rest:
        content.append(f'<details>')
        content.append(f'<summary>Ver todos los pares ({len(filtered_radar)} total)</summary>')
        content.append('<table style="margin-top: 15px;">')
        content.append('<tr>')
        content.append('<th>ACTIVO</th>')
        content.append('<th>Heat</th>')
        content.append('<th>DIST. EMA</th>')
        content.append('<th>RSI</th>')
        content.append('<th>VOLUMEN</th>')
        content.append('<th>ESTADO</th>')
        content.append('</tr>')
        
        for i, item in enumerate(rest):
            swap_label = item.get('swap_label', f"{item.get('from_currency', 'N/A')} → {item.get('to_currency', 'N/A')}")
            heat = item.get('heat_score', 0)
            
            rsi = item.get('rsi')
            ema_distance = item.get('ema200_distance')
            volume_status = item.get('volume_status', 'medium')
            triple_green = item.get('triple_green', False)
            
            heat_color = '#00FF88' if heat >= 85 else '#88FF88' if heat >= 70 else '#FFFFFF'
            
            estado = 'Normal'
            estado_color = '#FFFFFF'
            if triple_green:
                estado = 'Triple Verde ✅'
                estado_color = '#00FF88'
            elif rsi is not None:
                if rsi < 30:
                    estado = 'Sobreventa'
                    estado_color = '#00FF88'
                elif rsi > 70:
                    estado = 'Sobrecompra'
                    estado_color = '#FF4444'
            
            content.append('<tr>')
            content.append(f'<td><strong style="color: #FFFFFF;">{swap_label}</strong></td>')
            content.append(f'<td style="color: {heat_color}; font-weight: 600;">{heat}</td>')
            content.append(f'<td>{_get_indicator_icon(ema_distance, "ema")}{format_number(ema_distance, 2) if ema_distance is not None else "N/A"}%</td>')
            content.append(f'<td>{_get_indicator_icon(rsi, "rsi")}{format_number(rsi, 1) if rsi is not None else "N/A"}</td>')
            content.append(f'<td>{_get_indicator_icon(volume_status, "volume")}{volume_status if volume_status else "N/A"}</td>')
            content.append(f'<td style="color: {estado_color};">{estado}</td>')
            content.append('</tr>')
        
        content.append('</table>')
        content.append('</details>')
    
    # Indicador de sincronización
    timestamp = state.get('timestamp', '')
    sync_ago = calculate_sync_ago(timestamp) if timestamp else 'N/A'
    content.append(f'<div class="sync-indicator active">🔄 Última sincronización: hace {sync_ago}</div>')
    
    content.append('</div>')
    return '\n'.join(content)

def generate_distribution(state, hucha_data):
    """Genera los gráficos de distribución (Pie Charts)"""
    content = []
    content.append('<h2>📊 DISTRIBUCIÓN</h2>')
    content.append('<div class="distribution-grid">')
    
    # Gráfico A: Wallet Operativa
    dynamic_inventory = state.get('dynamic_inventory', [])
    gas_bnb = state.get('gas_bnb', {})
    free_cash = state.get('free_cash_eur', 0)
    
    content.append('<div class="chart-container">')
    content.append('<h3 style="color: #00FF88; margin-bottom: 15px;">Wallet Operativa</h3>')
    
    # Calcular distribución
    total_operativa = sum(item.get('value_eur', 0) for item in dynamic_inventory) + gas_bnb.get('value_eur', 0) + free_cash
    
    if total_operativa > 0:
        content.append('<div class="chart-legend">')
        # Inventario
        for item in sorted(dynamic_inventory, key=lambda x: x.get('value_eur', 0), reverse=True)[:8]:
            asset = item.get('currency', 'N/A')
            value_eur = item.get('value_eur', 0)
            amount = item.get('operable_amount', 0)
            current_price = item.get('current_price', 0)
            percent = (value_eur / total_operativa * 100) if total_operativa > 0 else 0
            
            if value_eur > 1:
                content.append('<div class="legend-item">')
                content.append(f'<div><span class="legend-color" style="background: #00FF88;"></span><strong>{asset}</strong></div>')
                content.append(f'<div>{percent:.1f}% | {format_currency(value_eur)} | {format_number(amount)} | {format_number(current_price, 4)}</div>')
                content.append('</div>')
        
        # Gas
        if gas_bnb.get('value_eur', 0) > 1:
            gas_percent = (gas_bnb.get('value_eur', 0) / total_operativa * 100) if total_operativa > 0 else 0
            content.append('<div class="legend-item">')
            content.append(f'<div><span class="legend-color" style="background: #FFAA00;"></span><strong>BNB (Gas)</strong></div>')
            content.append(f'<div>{gas_percent:.1f}% | {format_currency(gas_bnb.get("value_eur", 0))}</div>')
            content.append('</div>')
        
        # Cash libre
        if free_cash > 1:
            cash_percent = (free_cash / total_operativa * 100) if total_operativa > 0 else 0
            content.append('<div class="legend-item">')
            content.append(f'<div><span class="legend-color" style="background: #8844FF;"></span><strong>Cash Libre</strong></div>')
            content.append(f'<div>{cash_percent:.1f}% | {format_currency(free_cash)}</div>')
            content.append('</div>')
        
        content.append('</div>')
    else:
        content.append('<div style="padding: 20px; text-align: center; color: #666;">Sin datos</div>')
    
    content.append('</div>')
    
    # Gráfico B: Reserva (Hucha)
    content.append('<div class="chart-container">')
    content.append('<h3 style="color: #8844FF; margin-bottom: 15px;">Reserva (Hucha)</h3>')
    
    if hucha_data:
        # Agrupar por currency
        hucha_by_currency = defaultdict(float)
        for entry in hucha_data:
            currency = entry.get('currency', 'N/A')
            amount = entry.get('amount', 0)
            value_eur = entry.get('value_eur_at_save', 0)
            hucha_by_currency[currency] += value_eur
        
        total_hucha = sum(hucha_by_currency.values())
        
        if total_hucha > 0:
            content.append('<div class="chart-legend">')
            for currency, value_eur in sorted(hucha_by_currency.items(), key=lambda x: x[1], reverse=True):
                percent = (value_eur / total_hucha * 100) if total_hucha > 0 else 0
                content.append('<div class="legend-item">')
                content.append(f'<div><span class="legend-color" style="background: #8844FF;"></span><strong>{currency}</strong></div>')
                content.append(f'<div>{percent:.1f}% | {format_currency(value_eur)}</div>')
                content.append('</div>')
            content.append('</div>')
        else:
            content.append('<div style="padding: 20px; text-align: center; color: #666;">Hucha vacía</div>')
    else:
        content.append('<div style="padding: 20px; text-align: center; color: #666;">Hucha vacía</div>')
    
    content.append('</div>')
    content.append('</div>')
    return '\n'.join(content)

def generate_events(bitacora_lines):
    """Genera la sección de Historial de Eventos con fecha/hora absoluta y filtros"""
    content = []
    content.append('<h2>📋 HISTORIAL DE EVENTOS (Bitácora Pro)</h2>')
    content.append('<div class="events-container">')
    
    # Filtros (sin JavaScript, usando URL params o form)
    content.append('<div class="events-filters">')
    content.append('<label style="color: #888; margin-right: 10px;">Filtrar por tipo:</label>')
    content.append('<select class="filter-select" name="event_type" onchange="window.location.href=window.location.pathname+\'?filter=\'+this.value">')
    content.append('<option value="all">Todos</option>')
    content.append('<option value="gas">Gas</option>')
    content.append('<option value="hucha">Hucha</option>')
    content.append('<option value="swap">Swaps</option>')
    content.append('<option value="compra">Compras</option>')
    content.append('<option value="venta">Ventas</option>')
    content.append('</select>')
    content.append('</div>')
    
    if not bitacora_lines:
        content.append('<div style="padding: 20px; text-align: center; color: #666;">No hay eventos registrados</div>')
        content.append('</div>')
        return '\n'.join(content)
    
    # Procesar eventos (últimos 15 por defecto)
    events = bitacora_lines[-15:] if len(bitacora_lines) > 15 else bitacora_lines
    events.reverse()
    
    for line in events:
        # Parsear formato: YYYY-MM-DD HH:MM:SS | [PREFIJO] Mensaje
        timestamp_display = "N/A"
        message = line
        
        if ' | ' in line:
            parts = line.split(' | ', 1)
            if len(parts) == 2:
                timestamp_str = parts[0]
                message = parts[1]
                
                # Mostrar fecha/hora absoluta
                try:
                    event_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    timestamp_display = event_time.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    timestamp_display = timestamp_str
        elif '|' in line:
            parts = line.split('|', 1)
            if len(parts) == 2:
                timestamp_str = parts[0].strip()
                message = parts[1].strip()
                try:
                    event_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    timestamp_display = event_time.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    timestamp_display = timestamp_str
        
        # Determinar tipo de evento y color según prefijos
        message_upper = message.upper()
        event_color = '#FFFFFF'  # Blanco por defecto
        event_class = ''
        
        if '[⛽ GAS_EMERGENCIA]' in message or '[⛽ GAS_ESTRATÉGICO]' in message:
            event_color = '#FF4444'  # ROJO
            event_class = 'event-gas-emergency'
            event_type = message.split(']')[0] + ']' if ']' in message else '[GAS]'
        elif '[⛽ GAS_RETENIDO]' in message:
            event_color = '#888888'  # GRIS TENUE
            event_class = 'event-gas-retained'
            event_type = '[⛽ GAS_RETENIDO]'
        elif '[🔄 SWAP_DIVERSIFICACIÓN]' in message:
            event_color = '#FFFFFF'  # BLANCO
            event_class = 'event-swap-diversificacion'
            event_type = '[🔄 SWAP_DIVERSIFICACIÓN]'
        elif '[🔄 SWAP_CENTINELA]' in message:
            event_color = '#FF4444'  # ROJO
            event_class = 'event-swap-centinela'
            event_type = '[🔄 SWAP_CENTINELA]'
        elif '[💎 HUCHA_SAVE]' in message:
            event_color = '#FFD700'  # DORADO/AMARILLO
            event_class = 'event-hucha'
            event_type = '[💎 HUCHA_SAVE]'
        elif '[🛒 COMPRA_SLOT]' in message:
            event_color = '#FFFFFF'  # BLANCO
            event_class = 'event-compra'
            event_type = '[🛒 COMPRA_SLOT]'
        elif '[💰 VENTA_SLOT]' in message:
            # Determinar si es positivo o negativo
            if '+' in message or 'Resultado: +' in message:
                event_color = '#00FF88'  # VERDE (profit positivo)
            else:
                event_color = '#FF4444'  # ROJO (pérdida)
            event_class = 'event-venta'
            event_type = '[💰 VENTA_SLOT]'
        else:
            # Fallback para eventos antiguos
            line_lower = message.lower()
            if 'swap' in line_lower or '→' in message or '->' in message:
                event_color = '#FFFFFF'
                event_class = 'event-swap'
                event_type = '[SWAP]'
            elif 'gas' in line_lower or 'bnb' in line_lower:
                event_color = '#FFAA00'
                event_class = 'event-gas'
                event_type = '[GAS]'
            elif 'hucha' in line_lower:
                event_color = '#FFD700'
                event_class = 'event-hucha'
                event_type = '[HUCHA]'
            else:
                event_color = '#FFFFFF'
                event_class = ''
                event_type = '[EVENT]'
        
        content.append(f'<div class="event-item {event_class}" style="color: {event_color};">')
        content.append(f'<span class="event-timestamp">{timestamp_display}</span>')
        content.append(f'<span class="event-type" style="color: {event_color};">{event_type}</span>')
        content.append(f'<span style="color: {event_color};">{message}</span>')
        content.append('</div>')
    
    # Botón para expandir a 50 eventos (usando details HTML5)
    if len(bitacora_lines) > 15:
        content.append('<details>')
        content.append('<summary class="expand-events">Ver más eventos (hasta 50)</summary>')
        
        # Mostrar eventos adicionales
        extra_events = bitacora_lines[-50:-15] if len(bitacora_lines) > 50 else bitacora_lines[:-15]
        extra_events.reverse()
        
        for line in extra_events:
            timestamp_display = "N/A"
            message = line
            if '|' in line:
                parts = line.split('|', 1)
                if len(parts) == 2:
                    timestamp_str = parts[0].strip()
                    message = parts[1].strip()
                    try:
                        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        timestamp_display = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        timestamp_display = timestamp_str
            
            # Determinar tipo y color
            message_upper = message.upper()
            event_color = '#FFFFFF'
            event_class = ''
            if '[⛽ GAS_EMERGENCIA]' in message or '[⛽ GAS_ESTRATÉGICO]' in message:
                event_color = '#FF4444'
                event_class = 'event-gas-emergency'
            elif '[⛽ GAS_RETENIDO]' in message:
                event_color = '#888888'
                event_class = 'event-gas-retained'
            elif '[🔄 SWAP_DIVERSIFICACIÓN]' in message:
                event_color = '#FFFFFF'
                event_class = 'event-swap-diversificacion'
            elif '[🔄 SWAP_CENTINELA]' in message:
                event_color = '#FF4444'
                event_class = 'event-swap-centinela'
            elif '[💎 HUCHA_SAVE]' in message:
                event_color = '#FFD700'
                event_class = 'event-hucha'
            elif '[🛒 COMPRA_SLOT]' in message:
                event_color = '#FFFFFF'
                event_class = 'event-compra'
            elif '[💰 VENTA_SLOT]' in message:
                if '+' in message or 'Resultado: +' in message:
                    event_color = '#00FF88'
                else:
                    event_color = '#FF4444'
                event_class = 'event-venta'
            
            event_type = message.split(']')[0] + ']' if ']' in message else '[EVENT]'
            
            content.append(f'<div class="event-item {event_class}" style="color: {event_color};">')
            content.append(f'<span class="event-timestamp">{timestamp_display}</span>')
            content.append(f'<span class="event-type" style="color: {event_color};">{event_type}</span>')
            content.append(f'<span style="color: {event_color};">{message}</span>')
            content.append('</div>')
        
        content.append('</details>')
    
    content.append('</div>')
    return '\n'.join(content)

def generate_content(state, hucha_data, bitacora_lines):
    """Genera todo el contenido del dashboard"""
    if not state:
        return '<div style="padding: 40px; text-align: center; color: #FF4444; background: #1a1a2e; border-radius: 10px; margin: 20px 0;">⚠️ No se pudo cargar el estado. El bot puede no estar ejecutándose.</div>'
    
    content = []
    
    # 1. RESUMEN GENERAL
    content.append(generate_summary(state))
    
    # 2. SLOTS ACTIVOS
    content.append(generate_slots_table(state))
    
    # 3. RADAR DE OPORTUNIDAD
    content.append(generate_radar(state))
    
    # 4. DISTRIBUCIÓN
    content.append(generate_distribution(state, hucha_data))
    
    # 5. HISTORIAL DE EVENTOS
    content.append(generate_events(bitacora_lines))
    
    return '\n'.join(content)

@app.route('/')
def index():
    """Página principal del dashboard"""
    state = load_state()
    hucha_data = load_hucha()
    bitacora_lines = load_bitacora()
    
    content = generate_content(state, hucha_data, bitacora_lines)
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sync_ago = calculate_sync_ago(state.get('timestamp', '')) if state else 'N/A'
    
    return render_template_string(HTML_TEMPLATE, content=content, timestamp=timestamp, sync_ago=sync_ago)

@app.route('/shared/<path:filename>')
def shared_files(filename):
    """Sirve archivos de la carpeta shared"""
    return send_from_directory(ROOT_DIR / 'shared', filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
