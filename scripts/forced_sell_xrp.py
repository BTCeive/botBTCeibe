#!/usr/bin/env python3
import os
from pathlib import Path
ROOT = Path(__file__).parent.parent
os.chdir(ROOT)

import sys
# Asegurar que el directorio del proyecto está en sys.path
root = str(Path(__file__).parent.parent)
if root not in sys.path:
    sys.path.insert(0, root)
from database import Database
from engine.trading_logic import TradingEngine

# Cargar DB y encontrar trade XRP/EUR
db = Database('multibot.db')
trades = db.get_all_active_trades()
trade = None
for t in trades:
    if isinstance(t.get('symbol',''), str) and t.get('symbol','').upper().startswith('XRP/EUR'):
        trade = t
        break

if not trade:
    print('No active XRP/EUR trade found')
    raise SystemExit(1)

amount = trade.get('amount')
symbol = trade.get('symbol')
slot_id = trade.get('slot_id')
trade_id = trade.get('id')

print(f'Attempting forced market sell: {symbol} amount={amount} (slot {slot_id})')

engine = TradingEngine()
exchange = engine.exchange

try:
    order = exchange.create_market_sell_order(symbol, amount)
    ok_msg = f"[FORCED_EXIT_OK] Slot {slot_id + 1}: {symbol} — Order: {order}"
    print(ok_msg)
    from engine.trading_logic import write_bitacora
    write_bitacora(ok_msg)
    try:
        db.deactivate_trade(trade_id)
    except Exception:
        pass
except Exception as e:
    raw_err = repr(e)
    err_msg = f"[FORCED_EXIT_FAIL_RAW] Slot {slot_id + 1}: {symbol} | RAW_ERROR: {raw_err}"
    print(err_msg)
    from engine.trading_logic import write_bitacora
    write_bitacora(err_msg)
    raise