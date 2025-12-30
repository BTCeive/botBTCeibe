#!/usr/bin/env python3
import asyncio
import os
from pathlib import Path
ROOT = Path(__file__).parent.parent
os.chdir(ROOT)

async def main():
    import sys
    print('cwd=', Path.cwd())
    # Asegurar que el directorio raíz está en sys.path para poder importar paquetes del proyecto
    root = str(Path.cwd())
    if root not in sys.path:
        sys.path.insert(0, root)
    print('sys.path[0]=', sys.path[0])
    print('sys.path sample=', sys.path[:5])
    # Intentar importar TradingEngine
    from engine.trading_logic import TradingEngine
    engine = TradingEngine()
    # Llamar a _save_radar_data (async)
    await engine._save_radar_data()
    print('Radar saved')

if __name__ == '__main__':
    asyncio.run(main())
