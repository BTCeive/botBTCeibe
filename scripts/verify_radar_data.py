#!/usr/bin/env python3
"""
Script de verificación para auditar datos del radar y vigilante.
Comprueba:
1. Presencia de change_24h y volume_change en radar_data
2. Formato de start_ts en vigilancia_state (debe ser float)
3. Logs de auditoría en bitacora.txt
"""
import json
from pathlib import Path
from datetime import datetime
import time

ROOT = Path(__file__).parent.parent
STATE_PATH = ROOT / 'shared' / 'state.json'
VIGILANCIA_PATH = ROOT / 'shared' / 'vigilancia_state.json'
BITACORA_PATH = ROOT / 'bitacora.txt'

def check_radar_data():
    """Verificar estructura de radar_data."""
    print("\n🔍 VERIFICANDO RADAR DATA...")
    
    if not STATE_PATH.exists():
        print(f"❌ No existe {STATE_PATH}")
        return False
    
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            state = json.load(f)
        
        radar_data = state.get('radar_data', [])
        
        if not radar_data:
            print("⚠️  Radar vacío (no hay pares)")
            return False
        
        print(f"✅ Radar tiene {len(radar_data)} pares")
        
        # Verificar primer par
        first_pair = radar_data[0]
        print(f"\n📊 Analizando primer par: {first_pair.get('pair', 'N/A')}")
        
        # Verificar claves forzadas
        has_change_24h = 'change_24h' in first_pair
        has_volume_change = 'volume_change' in first_pair
        
        change_24h_value = first_pair.get('change_24h', 'N/A')
        volume_change_value = first_pair.get('volume_change', 'N/A')
        
        print(f"  change_24h: {'✅' if has_change_24h else '❌'} = {change_24h_value}")
        print(f"  volume_change: {'✅' if has_volume_change else '❌'} = {volume_change_value}")
        
        # Verificar que no sean 0.0
        if has_change_24h and change_24h_value == 0.0:
            print("  ⚠️  change_24h es 0.0 (posible problema de API)")
        
        if has_volume_change and volume_change_value == 0.0:
            print("  ⚠️  volume_change es 0.0 (volumen no calculado)")
        
        # Mostrar otros campos
        print(f"  RSI: {first_pair.get('rsi', 'N/A')}")
        print(f"  EMA200: {first_pair.get('ema200_distance', 'N/A')}")
        print(f"  Heat: {first_pair.get('heat_score', 'N/A')}")
        
        return has_change_24h and has_volume_change
        
    except Exception as e:
        print(f"❌ Error leyendo state.json: {e}")
        return False

def check_vigilancia_state():
    """Verificar formato de vigilancia_state."""
    print("\n🔍 VERIFICANDO VIGILANCIA STATE...")
    
    if not VIGILANCIA_PATH.exists():
        print(f"⚠️  No existe {VIGILANCIA_PATH}")
        return False
    
    try:
        with open(VIGILANCIA_PATH, 'r', encoding='utf-8') as f:
            vigilancia = json.load(f)
        
        start_ts = vigilancia.get('start_ts')
        current_pair = vigilancia.get('current_pair')
        
        print(f"  current_pair: {current_pair}")
        print(f"  start_ts: {start_ts}")
        print(f"  tipo: {type(start_ts).__name__}")
        
        # Verificar que sea float/int
        is_numeric = isinstance(start_ts, (int, float))
        
        if is_numeric:
            print(f"  ✅ start_ts es numérico (timestamp UNIX)")
            
            # Calcular tiempo transcurrido
            now = time.time()
            elapsed = int(now - start_ts)
            
            if elapsed < 60:
                time_str = f"{elapsed}s"
            elif elapsed < 3600:
                minutes = elapsed // 60
                seconds = elapsed % 60
                time_str = f"{minutes}m {seconds}s"
            else:
                hours = elapsed // 3600
                minutes = (elapsed % 3600) // 60
                time_str = f"{hours}h {minutes}m"
            
            print(f"  ⏱️  Tiempo transcurrido: {time_str}")
        else:
            print(f"  ⚠️  start_ts NO es numérico (es string: {start_ts})")
        
        return is_numeric
        
    except Exception as e:
        print(f"❌ Error leyendo vigilancia_state.json: {e}")
        return False

def check_bitacora_logs():
    """Buscar logs de auditoría en bitacora."""
    print("\n🔍 VERIFICANDO LOGS DE AUDITORÍA...")
    
    if not BITACORA_PATH.exists():
        print(f"⚠️  No existe {BITACORA_PATH}")
        return False
    
    try:
        with open(BITACORA_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Buscar últimos logs de BUY_CHECK
        buy_check_logs = [l for l in lines if '[BUY_CHECK]' in l]
        swap_reject_logs = [l for l in lines if '[SWAP_REJECT]' in l]
        
        print(f"  Logs [BUY_CHECK]: {len(buy_check_logs)}")
        print(f"  Logs [SWAP_REJECT]: {len(swap_reject_logs)}")
        
        # Mostrar últimos 3 logs de auditoría
        if buy_check_logs:
            print("\n  📝 Últimos logs de auditoría:")
            for log in buy_check_logs[-3:]:
                print(f"    {log.strip()}")
        
        if swap_reject_logs:
            print("\n  ⛔ Últimos rechazos:")
            for log in swap_reject_logs[-3:]:
                print(f"    {log.strip()}")
        
        return len(buy_check_logs) > 0
        
    except Exception as e:
        print(f"❌ Error leyendo bitacora.txt: {e}")
        return False

def main():
    print("=" * 60)
    print("🔧 VERIFICACIÓN DE DATOS FORZADOS - RADAR Y VIGILANTE")
    print("=" * 60)
    
    radar_ok = check_radar_data()
    vigilancia_ok = check_vigilancia_state()
    logs_ok = check_bitacora_logs()
    
    print("\n" + "=" * 60)
    print("📊 RESUMEN:")
    print(f"  Radar (change_24h/volume_change): {'✅' if radar_ok else '❌'}")
    print(f"  Vigilante (start_ts float): {'✅' if vigilancia_ok else '❌'}")
    print(f"  Logs de auditoría: {'✅' if logs_ok else '⚠️  Sin logs recientes'}")
    print("=" * 60)
    
    if not radar_ok:
        print("\n💡 RECOMENDACIÓN:")
        print("   Si radar está vacío o tiene change_24h=0.0:")
        print("   1. Verificar: tail -n 50 bot_run.log")
        print("   2. Buscar errores de Rate Limit de Binance")
        print("   3. Reiniciar el bot: ./start_bot.sh")

if __name__ == '__main__':
    main()
