import asyncio
from engine.trading_logic import TradingEngine

async def main():
    engine = TradingEngine()
    await engine._save_shared_state()
    await asyncio.sleep(2)
    await engine._save_shared_state()

if __name__ == "__main__":
    asyncio.run(main())
