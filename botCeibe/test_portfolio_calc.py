#!/usr/bin/env python3
"""
Script de prueba para verificar el cálculo del valor total del portfolio.
"""
import sys
from pathlib import Path

# Añadir el directorio raíz del proyecto al path
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from vault import Vault
from router import get_pair_info
import json

# Datos de ejemplo del state.json
balances_data = {
    'EUR': 51.31196,
    'XRP': 26.4,
    'BTC': 0.000026,
    'BNB': 0.0115298
}

print("=" * 60)
print("PRUEBA DE CÁLCULO DE PORTFOLIO")
print("=" * 60)

print("\nBalances en wallet:")
for asset, amount in balances_data.items():
    if amount > 0:
        print(f"  {asset:8} = {amount:15}")

# Crear instancia de Vault (sin exchange real)
vault = Vault(None)

print("\nConversión de cada asset a EUR:")
total = 0.0
for asset, amount in balances_data.items():
    if amount > 0:
        try:
            value = vault.get_asset_value(asset, amount, 'EUR')
            total += value
            print(f"  {asset:8} {amount:15.8f} → {value:10.2f}€")
        except Exception as e:
            print(f"  {asset:8} ERROR: {e}")

print(f"\n{'TOTAL PORTFOLIO VALUE':8} = {total:.2f}€")

# Cargar state.json para comparar
try:
    state_path = ROOT_DIR / 'shared' / 'state.json'
    with open(state_path) as f:
        state = json.load(f)
    reported_value = state.get('total_portfolio_value', 0)
    print(f"{'STATE.JSON REPORTED':8} = {reported_value:.2f}€")
    print(f"\n📊 Diferencia: {abs(total - reported_value):.2f}€")
except Exception as e:
    print(f"Error cargando state.json: {e}")
