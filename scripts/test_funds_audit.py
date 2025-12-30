#!/usr/bin/env python3
"""
Script rápido para verificar la auditoría de fondos y cálculo de wallet.
"""
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Cargar shared/state.json
state_path = ROOT_DIR / "shared" / "state.json"

if not state_path.exists():
    print("❌ state.json no existe. Ejecuta el motor primero.")
    sys.exit(1)

try:
    with open(state_path, 'r', encoding='utf-8') as f:
        state = json.load(f)
except Exception as e:
    print(f"❌ Error leyendo state.json: {e}")
    sys.exit(1)

balances = state.get('balances', {}).get('total', {}) or {}

print("\n================ AUDITORÍA DE FONDOS (desde state.json) ================")
print(f"Total activos encontrados: {len(balances)}")

# Simulación de cálculo wallet
from router import get_pair_info

wallet_total_eur = 0.0
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
        price_used = 1.0
        eur_value = amount
        wallet_total_eur += eur_value
    elif asset in ['USDC', 'USDT']:
        price_used = 1.0
        try:
            pair_info = get_pair_info(f"EUR/{asset}")
            if pair_info and pair_info.get('last_price'):
                price_used = float(pair_info.get('last_price', 1.0))
            else:
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
    
    print(f" - {asset:6s}: {amount:>12.8f} unidades | EUR_price={price_used:.8f} | EUR_value={eur_value:>12.2f}€")

print(f"\n✅ TOTAL WALLET: {wallet_total_eur:.2f}€")
print("========================================================================\n")
