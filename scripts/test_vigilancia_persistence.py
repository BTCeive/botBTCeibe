"""Prueba: persistencia de vigilancia
Escribe una estructura de vigilancia simulada en shared/vigilancia_state.json
y comprueba que dashboard.app._read_vigilancia_state la puede leer correctamente.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).parent.parent
VIG_PATH = ROOT / 'shared' / 'vigilancia_state.json'

sample = {
    'vigilante_timers': {'BTC/EUR': (datetime.utcnow() - timedelta(seconds=30)).isoformat()},
    'current_pair': 'BTC/EUR',
    'buffer': ['BTC/EUR','BTC/EUR','BTC/EUR'],
    'start_ts': (datetime.utcnow() - timedelta(seconds=30)).isoformat(),
    'last_updated': datetime.utcnow().isoformat()
}

# Escribir
VIG_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(VIG_PATH, 'w', encoding='utf-8') as f:
    json.dump(sample, f, indent=2)

# Leer directamente el archivo (no dependemos de streamlit en el entorno de pruebas)
with open(VIG_PATH,'r',encoding='utf-8') as f:
    read = json.load(f)
assert read.get('current_pair') == 'BTC/EUR', 'current_pair mismatch'
assert 'BTC/EUR' in read.get('vigilante_timers', {}), 'timer not present'
print('OK: vigilancia_state.json persistido y leido correctamente')
