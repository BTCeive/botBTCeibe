"""Simula 3 ciclos del radar con el mismo líder y verifica que vigilancia_state.json
actualiza 'current_pair' y 'vigilante_timers' tras 3 ciclos idénticos.
"""
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
RADAR_PATH = ROOT / 'shared' / 'radar.json'
VIG_PATH = ROOT / 'shared' / 'vigilancia_state.json'

def update_buffer_from_radar():
    try:
        if not RADAR_PATH.exists():
            return
        with open(RADAR_PATH,'r',encoding='utf-8') as f:
            radar = json.load(f)
        radar_list = radar.get('radar_data', [])
        leader_pair = None
        if radar_list and len(radar_list) > 0:
            top = radar_list[0]
            origin = top.get('origin') or top.get('from_currency') or top.get('currency')
            dest = top.get('destination') or top.get('to_currency')
            if origin and dest:
                leader_pair = f"{origin}/{dest}"

        vstate = {}
        if VIG_PATH.exists():
            with open(VIG_PATH,'r',encoding='utf-8') as vf:
                vstate = json.load(vf) or {}
        buffer = vstate.get('buffer', [])
        current_pair = vstate.get('current_pair')

        if leader_pair:
            buffer.append(leader_pair)
            if len(buffer) > 3:
                buffer = buffer[-3:]

            if len(buffer) >= 3 and all(p == leader_pair for p in buffer) and leader_pair != current_pair:
                vstate['current_pair'] = leader_pair
                vstate['start_ts'] = datetime.now().isoformat()
                vstate['buffer'] = buffer
                vstate.setdefault('vigilante_timers', {})
                vstate['vigilante_timers'][leader_pair] = vstate['start_ts']
                with open(VIG_PATH,'w',encoding='utf-8') as wf:
                    json.dump(vstate,wf,indent=2)
                return 'restarted'
            else:
                vstate['buffer'] = buffer
                with open(VIG_PATH,'w',encoding='utf-8') as wf:
                    json.dump(vstate,wf,indent=2)
                return 'buffered'
    except Exception as e:
        print('Error:', e)
    return 'noop'

# Test: perform 3 cycles with the same top leader
leader = {'origin':'ETH','destination':'EUR','currency':'ETH','to_currency':'EUR'}
RADAR_PATH.parent.mkdir(parents=True,exist_ok=True)

# Reset vigilancia
with open(VIG_PATH,'w',encoding='utf-8') as vf:
    json.dump({'vigilante_timers':{}, 'current_pair': None, 'buffer': [], 'start_ts': None}, vf, indent=2)

outcomes = []
for i in range(3):
    # write radar with ETH/EUR on top
    with open(RADAR_PATH,'w',encoding='utf-8') as rf:
        json.dump({'radar_data':[leader]}, rf, indent=2)
    res = update_buffer_from_radar()
    outcomes.append(res)

# Verify final state
with open(VIG_PATH,'r',encoding='utf-8') as vf:
    final = json.load(vf)

assert final.get('current_pair') == 'ETH/EUR', f"current_pair not set, got {final.get('current_pair')}"
assert 'ETH/EUR' in final.get('vigilante_timers', {}), 'timers not present'
print('OK: buffer logic triggered, vigilante restarted after 3 cycles')
print('outcomes:', outcomes)
