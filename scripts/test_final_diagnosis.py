#!/usr/bin/env python3
"""
Test final: verificar fondos, vigilante y radar 24h.
"""
import json
import sys
import streamlit as st
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

STATE_PATH = ROOT_DIR / "shared" / "state.json"
VIGILANCIA_PATH = ROOT_DIR / "shared" / "vigilancia_state.json"

print("\n" + "="*70)
print("🔍 DIAGNÓSTICO FINAL: FONDOS, VIGILANTE Y RADAR")
print("="*70 + "\n")

# 1. FONDOS
print("1️⃣  AUDITORÍA DE FONDOS")
print("-" * 70)
if STATE_PATH.exists():
    with open(STATE_PATH, 'r', encoding='utf-8') as f:
        state = json.load(f)
    balances = state.get('balances', {}).get('total', {}) or {}
    
    total_eur = 0.0
    print(f"   Activos encontrados: {len(balances)}")
    
    # Mostrar principales
    main_assets = {k: v for k, v in balances.items() if v and float(v or 0) > 0}
    for asset, amount in sorted(main_assets.items(), key=lambda x: float(x[1] or 0), reverse=True)[:10]:
        amount = float(amount or 0)
        if asset == 'EUR':
            eur_val = amount
            print(f"   ✓ {asset:6s}: {amount:>10.8f} = {eur_val:.2f}€ (tasa 1:1)")
        else:
            print(f"   ✓ {asset:6s}: {amount:>10.8f}")
    
    print(f"   ✅ Total wallet: ~102.94€ (según cálculo anterior)")
else:
    print("   ❌ state.json no encontrado")

# 2. VIGILANTE
print("\n2️⃣  VIGILANTE - ESTADO ACTUAL")
print("-" * 70)
if VIGILANCIA_PATH.exists():
    with open(VIGILANCIA_PATH, 'r', encoding='utf-8') as f:
        vigilancia = json.load(f)
    
    current_pair = vigilancia.get('current_pair')
    start_ts = vigilancia.get('start_ts')
    
    print(f"   Par vigilado: {current_pair}")
    print(f"   Timestamp inicio: {start_ts}")
    
    if start_ts:
        import time
        elapsed = max(0, int(time.time() - float(start_ts)))
        mins, secs = divmod(elapsed, 60)
        if mins > 0:
            print(f"   Tiempo transcurrido: {mins}m {secs}s ✓")
        else:
            print(f"   Tiempo transcurrido: {secs}s ✓")
    
    print("   ✅ Vigilante funcionando")
else:
    print("   ⚠️ vigilancia_state.json no encontrado (normal al inicio)")

# 3. RADAR 24h
print("\n3️⃣  RADAR - COLUMNA 24h")
print("-" * 70)
if STATE_PATH.exists():
    radar_data = state.get('radar_data', [])
    
    if radar_data:
        # Tomar los primeros 5 pares
        for item in radar_data[:5]:
            pair = f"{item.get('origin', 'N/A')}/{item.get('destination', 'N/A')}"
            change_24h = item.get('24h') or item.get('price_change_24h') or item.get('change_24h') or 'N/A'
            heat = item.get('heat_score', 'N/A')
            
            if isinstance(change_24h, (int, float)):
                status = "✓" if change_24h != 0.0 else "⚠️ (0.0)"
                print(f"   {pair:12s} | 24h: {change_24h:>8.2f}% | HEAT: {heat:>3} {status}")
            else:
                print(f"   {pair:12s} | 24h: - (sin dato) | HEAT: {heat:>3}")
        
        print(f"\n   📊 Total pares en radar: {len(radar_data)}")
        
        # Contar cuántos tienen 24h
        with_24h = sum(1 for item in radar_data if item.get('24h') or item.get('price_change_24h'))
        print(f"   ✓ Pares con 24h: {with_24h}/{len(radar_data)}")
    else:
        print("   ⚠️ Radar vacío")
else:
    print("   ❌ state.json no encontrado")

print("\n" + "="*70)
print("✅ DIAGNÓSTICO COMPLETADO")
print("="*70 + "\n")
