#!/usr/bin/env python3
"""
Dashboard simple sin JavaScript - Solo HTML y CSS
Usa meta refresh para auto-actualizar cada 10 segundos
"""
from flask import Flask, render_template_string, send_from_directory
import json
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
# Usar el directorio del proyecto como raíz para rutas compartidas
ROOT_DIR = Path(__file__).resolve().parent

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="10">
    <title>botCeibe Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: Arial, sans-serif; 
            background: #0a0a0a; 
            color: #fff; 
            padding: 20px; 
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #00FF88; margin-bottom: 20px; }
        h2 { color: #00FF88; margin: 20px 0 10px; border-bottom: 2px solid #333; padding-bottom: 5px; }
        .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
        .metric { background: #1E1E1E; padding: 15px; border-radius: 8px; border: 1px solid #333; }
        .metric-label { color: #888; font-size: 0.9em; margin-bottom: 5px; }
        .metric-value { color: #00FF88; font-size: 1.5em; font-weight: bold; }
        .slots { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; margin: 20px 0; }
        .slot { background: #1E1E1E; padding: 15px; border-radius: 8px; border: 2px solid #333; }
        .slot.active { border-color: #00FF88; }
        .slot.inactive { background: #121212; color: #666; }
        .slot-header { font-weight: bold; margin-bottom: 10px; color: #00FF88; }
        .info { background: #1E1E1E; padding: 15px; border-radius: 8px; margin: 10px 0; }
        .error { background: #4a1a1a; color: #ff4444; padding: 15px; border-radius: 8px; margin: 10px 0; }
        .success { background: #1a4a1a; color: #44ff44; padding: 15px; border-radius: 8px; margin: 10px 0; }
        table { width: 100%; border-collapse: collapse; margin: 10px 0; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #333; }
        th { background: #1E1E1E; color: #00FF88; }
        .timestamp { color: #888; font-size: 0.8em; margin-top: 20px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 botCeibe Dashboard (Sin JavaScript)</h1>
        
        {{ content|safe }}
        
        <div class="timestamp">
            Última actualización: {{ timestamp }}<br>
            Auto-actualización cada 10 segundos
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
        except:
            return None
    return None

def format_currency(value):
    """Formatea un valor como moneda"""
    if value is None:
        return 'N/A'
    return f'{value:,.2f} €'

def generate_content(state):
    """Genera el contenido HTML del dashboard"""
    if not state:
        return '<div class="error">⚠️ No se pudo cargar el estado. El bot puede no estar ejecutándose.</div>'
    
    content = []
    
    # Resumen General
    content.append('<h2>📊 Resumen General</h2>')
    content.append('<div class="metrics">')
    
    total_value = state.get('total_portfolio_value', 0)
    content.append(f'<div class="metric"><div class="metric-label">Portfolio Total</div><div class="metric-value">{format_currency(total_value)}</div></div>')
    
    gas_status = state.get('gas_status', {})
    gas_percent = gas_status.get('current_percent', 0)
    gas_color = '#00FF88' if gas_percent >= 2.5 else '#FF8844' if gas_percent >= 0.5 else '#FF4444'
    content.append(f'<div class="metric"><div class="metric-label">Gas (BNB)</div><div class="metric-value" style="color: {gas_color}">{gas_percent:.2f}%</div></div>')
    
    market_status = state.get('market_status', {})
    status_msg = market_status.get('message', 'Desconocido')
    content.append(f'<div class="metric"><div class="metric-label">Estado Mercado</div><div class="metric-value">{status_msg}</div></div>')
    
    open_trades = state.get('open_trades', [])
    content.append(f'<div class="metric"><div class="metric-label">Trades Activos</div><div class="metric-value">{len(open_trades)}</div></div>')
    
    content.append('</div>')
    
    # Slots de Inversión
    content.append('<h2>📈 Slots de Inversión</h2>')
    content.append('<div class="slots">')
    
    if open_trades:
        for i, trade in enumerate(open_trades[:10]):  # Máximo 10 slots
            slot_class = 'slot active'
            asset = trade.get('target_asset', 'N/A')
            amount = trade.get('amount', 0)
            pnl = trade.get('pnl_percent', 0)
            pnl_color = '#00FF88' if pnl > 0 else '#FF4444' if pnl < 0 else '#FFFFFF'
            
            content.append(f'<div class="{slot_class}">')
            content.append(f'<div class="slot-header">Slot {i+1}: {asset}</div>')
            content.append(f'<div>Cantidad: {amount:.8f}</div>')
            content.append(f'<div style="color: {pnl_color}">PNL: {pnl:+.2f}%</div>')
            content.append('</div>')
    else:
        content.append('<div class="info">No hay trades activos</div>')
    
    content.append('</div>')
    
    # Radar de Oportunidades
    radar_data = state.get('radar_data', [])
    if radar_data:
        content.append('<h2>📡 Radar de Oportunidades</h2>')
        content.append('<table>')
        content.append('<tr><th>Activo</th><th>Heat Score</th><th>Precio</th></tr>')
        for item in radar_data[:10]:  # Top 10
            currency = item.get('currency', 'N/A')
            heat = item.get('heat_score', 0)
            price = item.get('current_price', 0)
            content.append(f'<tr><td>{currency}</td><td>{heat}</td><td>{price:.8f}</td></tr>')
        content.append('</table>')
    
    return '\n'.join(content)

@app.route('/')
def index():
    """Página principal del dashboard"""
    state = load_state()
    content = generate_content(state)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return render_template_string(HTML_TEMPLATE, content=content, timestamp=timestamp)

@app.route('/shared/<path:filename>')
def shared_files(filename):
    """Sirve archivos de la carpeta shared"""
    return send_from_directory(ROOT_DIR / 'shared', filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False)
