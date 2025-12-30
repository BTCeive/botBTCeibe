#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ccxt
from database import Database
import bot_config
from engine.trading_logic import write_bitacora

DB = Database('multibot.db')
trades = DB.get_all_active_trades()
trade = None
for t in trades:
    if isinstance(t.get('symbol',''), str) and t.get('symbol','').upper().startswith('XRP/EUR'):
        trade = t
        break

if not trade:
    print('No active XRP/EUR trade found')
    raise SystemExit(1)

symbol = trade['symbol']
amount = trade['amount']
slot_id = trade['slot_id']
trade_id = trade['id']

# Config exchange with timeout
exchange_config = {
    'apiKey': bot_config.BINANCE_API_KEY,
    'secret': bot_config.BINANCE_SECRET_KEY,
    'enableRateLimit': True,
    'timeout': 10000,
    'options': {'defaultType': 'spot'}
}
if bot_config.BINANCE_TESTNET:
    exchange_config['urls'] = {
        'api': {'public': 'https://testnet.binance.vision/api', 'private': 'https://testnet.binance.vision/api'}
    }

exchange = ccxt.binance(exchange_config)

print(f'Attempting safe forced market sell: {symbol} amount={amount} (slot {slot_id})')

try:
    order = exchange.create_order(symbol, 'market', 'sell', amount, None)
    ok_msg = f"[FORCED_EXIT_OK] Slot {slot_id + 1}: {symbol} — Order: {order}"
    print(ok_msg)
    write_bitacora(ok_msg)
    try:
        DB.deactivate_trade(trade_id)
    except Exception:
        pass
except Exception as e:
    raw_err = repr(e)
    err_msg = f"[FORCED_EXIT_FAIL_RAW] Slot {slot_id + 1}: {symbol} | RAW_ERROR: {raw_err}"
    print(err_msg)
    write_bitacora(err_msg)
    raise