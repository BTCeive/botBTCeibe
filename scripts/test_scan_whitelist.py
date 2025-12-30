import asyncio
import sys
from pathlib import Path
# Añadir ruta del proyecto al path para importar engine
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import types
# Inyectar un módulo ccxt falso para evitar dependencia durante la prueba
fake_ccxt = types.SimpleNamespace()
class FakeBinance:
    def __init__(self, *a, **k):
        pass
fake_ccxt.binance = FakeBinance
sys.modules['ccxt'] = fake_ccxt
sys.modules['dotenv'] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)
import engine.trading_logic as tl
from engine.trading_logic import TradingEngine

# Price map: 1 unit -> EUR
PRICE_MAP = {
    'XRP': 0.5,   # 1 XRP = 0.5 EUR -> 172 XRP -> 86 EUR
    'BTC': 30000,
    'ETH': 1600,
    'SOL': 20,
    'ADA': 0.35,
    'LTC': 90,
    'BNB': 220,
    'DOGE': 0.07,
    'DOT': 5,
    'LINK': 6,
    'UNI': 4,
    'MATIC': 0.9,
    'ATOM': 10,
    'SUSHI': 1.2,
    'AAVE': 60,
    'XMR': 120
}

# Monkeypatch get_pair_info in the trading_logic module
def fake_get_pair_info(pair):
    # Expect pair like 'XRP/EUR' or 'SOL/EUR'
    try:
        base, quote = pair.split('/')
    except Exception:
        return None
    if quote in ('EUR', 'USDC') and base in PRICE_MAP:
        return {'last_price': PRICE_MAP[base], 'price_change_percent': 1.0}
    return None

async def main():
    tl.get_pair_info = fake_get_pair_info

    engine = TradingEngine()

    # Set whitelist explicitly
    engine.strategy['whitelist'] = ['BTC','ETH','SOL','ADA','LTC','BNB','DOGE','DOT','LINK','UNI','MATIC','ATOM','SUSHI','AAVE','XMR']

    # Patch vault methods
    class FakeVault:
        def calculate_total_portfolio_value(self):
            # total portfolio EUR (we simulate XRP=86 being large part)
            return 100.0
        def get_asset_value(self, currency, amount, to_currency):
            if to_currency == 'EUR':
                price = PRICE_MAP.get(currency, 0)
                return amount * price
            return None
    engine.vault = FakeVault()

    # Patch exchange.fetch_balance to indicate 172 XRP (=> 86 EUR)
    class FakeExchange:
        def fetch_balance(self):
            return {'total': {'XRP': 172}}
    engine.exchange = FakeExchange()

    # Ensure radar cache empty
    engine.radar_data_cache.clear()
    engine.radar_last_update.clear()

    # Run scan
    await engine._scan_whitelist_against_base('XRP')

    # Print first 10 entries
    print("\nRADAR DATA CACHE (first 10):")
    i = 0
    for k, v in engine.radar_data_cache.items():
        if i >= 10:
            break
        heat = v.get('heat_score')
        over = v.get('overexposed', False)
        note = v.get('note')
        origin = v.get('origin')
        dest = v.get('destination')
        print(f"{k}: heat={heat}, overexposed={over}, note={note}, origin={origin}, dest={dest}")
        i += 1

    # Calculate swap amount proposal for XRP first slot
    total_balance_units = 172
    swap_amount = engine._calculate_swap_order_size('XRP', total_balance_units)
    swap_value_eur = engine.vault.get_asset_value('XRP', swap_amount, 'EUR')
    print(f"\nSwap proposal for XRP: amount_units={swap_amount}, value_eur={swap_value_eur:.2f} EUR")

if __name__ == '__main__':
    asyncio.run(main())
