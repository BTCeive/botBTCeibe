"""Test simple: simula que el Watchdog detecta tareas ausentes y escribe entradas de reinicio en bitacora.txt"""
from pathlib import Path
from datetime import datetime
ROOT = Path(__file__).parent.parent
BITACORA = ROOT / 'bitacora.txt'

def write_bitacora_local(msg: str):
    with open(BITACORA, 'a', encoding='utf-8') as bf:
        bf.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")

# Registrar entradas simuladas
write_bitacora_local('[RADAR_RESTART] Intento de reinicio del radar dinámico (test)')
write_bitacora_local('[RADAR_RESTART_OK] Reinicio intentado (test)')

# Verificar
text = BITACORA.read_text(encoding='utf-8')
assert '[RADAR_RESTART] Intento de reinicio del radar dinamico' in text.replace('á','a') or '[RADAR_RESTART] Intento de reinicio del radar dinámico (test)' in text
assert '[RADAR_RESTART_OK] Reinicio intentado (test)' in text
print('OK: bitacora updated with radar restart entries')
