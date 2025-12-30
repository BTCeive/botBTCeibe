#!/usr/bin/env python3
import json
from pathlib import Path

STATE_PATH = Path(__file__).parent / "shared" / "state.json"
OUTPUT_PATH = Path(__file__).parent / "dashboard_static.html"

def format_value(value, decimals=2):
    if isinstance(value, float):
        return f"{value:,.{decimals}f}"
    return str(value)

def get_gas_class(percentage):
    if percentage < 0.5:
        return "critical"
    elif percentage < 2.5:
        return "warning"
    return "ok"

def generate_html(state_data):
    timestamp = state_data.get("timestamp", "N/A")
    market_status = state_data.get("market_status", {})
    gas_status = state_data.get("gas_status", {})
    balances = state_data.get("balances", {}).get("total", {})
    open_trades = state_data.get("open_trades", [])
    radar_data = state_data.get("radar_data", [])
    total_value = state_data.get("total_portfolio_value", 0)
    
    gas_percent = gas_status.get("percentage", 0)
    gas_class = get_gas_class(gas_percent)
    
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="30">
    <title>botCeibe Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: Arial, sans-serif; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ color: #00ff88; margin-bottom: 10px; }}
        .timestamp {{ color: #888; margin-bottom: 20px; }}
        .section {{ background: #1a1a1a; padding: 20px; margin: 20px 0; border-radius: 8px; border: 1px solid #333; }}
        .section h2 {{ color: #00ff88; margin-bottom: 15px; }}
        .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
        .metric {{ background: #252525; padding: 15px; border-radius: 6px; border-left: 4px solid #00ff88; }}
        .metric-label {{ color: #aaa; font-size: 0.85em; margin-bottom: 5px; }}
        .metric-value {{ color: #00ff88; font-size: 1.8em; font-weight: bold; }}
        .status-critical {{ color: #ff4444; }}
        .status-warning {{ color: #ffaa00; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ background: #2a2a2a; color: #00ff88; }}
        tr:hover {{ background: #252525; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>botCeibe Dashboard</h1>
        <p class="timestamp">Actualizado: {timestamp}</p>
        
        <div class="section">
            <h2>Estado del Mercado</h2>
            <div class="metrics">
                <div class="metric">
                    <div class="metric-label">Estado</div>
                    <div class="metric-value">{market_status.get("message", "N/A")}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">BTC 24h</div>
                    <div class="metric-value">{(market_status.get("btc_change") or 0):.2f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Gas (BNB)</div>
                    <div class="metric-value status-{gas_class}">{gas_percent:.2f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Portfolio Total</div>
                    <div class="metric-value">{format_value(total_value)}€</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>Balances Principales</h2>
            <table>
                <tr><th>Activo</th><th>Cantidad</th></tr>
"""
    
    active_balances = {k: v for k, v in balances.items() if isinstance(v, (int, float)) and v > 0.0001}
    for asset, amount in sorted(active_balances.items(), key=lambda x: x[1], reverse=True)[:20]:
        html += f"                <tr><td>{asset}</td><td>{format_value(amount, 8)}</td></tr>\n"
    
    html += """            </table>
        </div>
        
        <div class="section">
            <h2>Trades Activos</h2>
"""
    
    if open_trades:
        html += """            <table>
                <tr><th>Slot</th><th>Activo</th><th>Cantidad</th><th>Entrada</th><th>Actual</th><th>PNL</th></tr>
"""
        for trade in open_trades:
            slot = trade.get("slot_id", "N/A")
            asset = trade.get("target_asset", "N/A")
            amount = trade.get("amount", 0)
            entry = trade.get("entry_price", 0)
            current = trade.get("current_price", entry)
            pnl = ((current - entry) / entry * 100) if entry > 0 else 0
            pnl_class = "status-ok" if pnl > 0 else "status-error"
            html += f"""                <tr>
                    <td>{slot}</td>
                    <td>{asset}</td>
                    <td>{format_value(amount, 8)}</td>
                    <td>{format_value(entry, 4)}</td>
                    <td>{format_value(current, 4)}</td>
                    <td class="{pnl_class}">{pnl:+.2f}%</td>
                </tr>
"""
        html += "            </table>\n"
    else:
        html += "            <p>No hay trades activos</p>\n"
    
    html += """        </div>
        
        <div class="section">
            <h2>Radar (Top 15)</h2>
            <table>
                <tr><th>Par / Swap</th><th>Heat Score</th><th>Triang.</th></tr>
"""
    
    for item in sorted(radar_data, key=lambda x: x.get("heat_score", 0), reverse=True)[:15]:
        pair = item.get("swap_label") or item.get("pair") or f"{item.get('origin','N/A')}/{item.get('destination','N/A')}"
        heat = item.get("heat_score", 0)
        tri = "🔁" if item.get("requires_triangulation") else ""
        html += f"                <tr><td>{pair}</td><td>{heat}</td><td>{tri}</td></tr>\n"
    
    # Heat components legend
    gas_target = gas_status.get("target_percent", "N/A")
    html += """            </table>
            <p style=\"margin-top:10px;color:#aaa;font-size:0.9em;\">Leyenda Heat: <strong>RSI 40%</strong> • <strong>EMA 30%</strong> • <strong>VOL 20%</strong> • <strong>BONUS 10%</strong></p>
"""
    html += f"            <p style=\"margin-top:6px;color:#aaa;font-size:0.9em;\">Gas target: {gas_target}% — Niveles: Pasivo <5% • Estratégico <2% • Emergencia <1%</p>\n"
    html += """        </div>
    </div>
</body>
</html>"""
    
    return html

if __name__ == "__main__":
    try:
        if STATE_PATH.exists():
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            html = generate_html(state_data)
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"Dashboard generado: {OUTPUT_PATH}")
        else:
            print(f"No se encontró: {STATE_PATH}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
