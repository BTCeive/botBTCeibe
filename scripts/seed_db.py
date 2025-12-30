#!/usr/bin/env python3
"""
Seed de emergencia para bot_data.db
Inserta una fila dummy en market_data y portfolio_history
"""
import json
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.storage import connect


def seed_once() -> None:
    ts = int(time.time())
    market_row = (
        ts,
        "seed",
        "seed",
        "BTC/USDT",
        "seed",
        0.0,
        0.0,
        0.0,
        0.0,
        json.dumps({"seed": True, "note": "dummy market row"}),
    )
    portfolio_row = (
        ts,
        10000.0,
        5000.0,
        json.dumps({"BTC": 0.1, "USDT": 5000}),
    )

    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO market_data (ts, origin, destination, pair, swap_label, heat_score, change_24h, vol_pct, vol, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            market_row,
        )
        cur.execute(
            """
            INSERT INTO portfolio_history (ts, total_portfolio_value, free_cash_eur, balances_json)
            VALUES (?, ?, ?, ?)
            """,
            portfolio_row,
        )
        conn.commit()
    print("✅ Seed insertado en market_data y portfolio_history")


if __name__ == "__main__":
    seed_once()
