import sqlite3
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ruta absoluta única para la base de datos
DB_PATH = Path("/home/lorenzo/Escritorio/proyect/botCeibe/shared/bot_data.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = {
    "market_data": (
        """
        CREATE TABLE IF NOT EXISTS market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            origin TEXT,
            destination TEXT,
            pair TEXT,
            swap_label TEXT,
            heat_score REAL,
            change_24h REAL,
            vol_pct REAL,
            vol REAL,
            extra_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_market_ts ON market_data(ts);
        CREATE INDEX IF NOT EXISTS idx_market_pair ON market_data(pair);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_market_pair_unique ON market_data(pair);
        """
    ),
    "portfolio_history": (
        """
        CREATE TABLE IF NOT EXISTS portfolio_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            total_portfolio_value REAL,
            free_cash_eur REAL,
            balances_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_portfolio_ts ON portfolio_history(ts);
        """
    ),
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        for _, ddl in SCHEMA.items():
            for stmt in ddl.split(";"):
                s = stmt.strip()
                if s:
                    conn.execute(s)
        conn.commit()
    finally:
        conn.close()


def save_market_data(entries: List[Dict[str, Any]], ts: Optional[int] = None) -> int:
    if ts is None:
        ts = int(time.time())
    conn = connect()
    try:
        rows = []
        for e in entries:
            rows.append((
                ts,
                e.get('origin'),
                e.get('destination'),
                e.get('pair') or (f"{e.get('origin')}/{e.get('destination')}" if e.get('origin') and e.get('destination') else None),
                e.get('swap_label'),
                float(e.get('heat_score', 0) or 0),
                float(e.get('24h') if e.get('24h') is not None else e.get('price_change_24h') or 0),
                float(e.get('vol_pct', 0) or 0),
                float(e.get('vol', 0) or 0),
                json.dumps(e, ensure_ascii=False)
            ))
        conn.executemany(
            "REPLACE INTO market_data (ts, origin, destination, pair, swap_label, heat_score, change_24h, vol_pct, vol, extra_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def save_portfolio_snapshot(snapshot: Dict[str, Any]) -> None:
    ts = int(time.time())
    total_portfolio_value = float(snapshot.get('total_portfolio_value', 0) or 0)
    free_cash_eur = float(snapshot.get('free_cash_eur', 0) or 0)
    balances = snapshot.get('balances', {}).get('total', {})
    balances_json = json.dumps(balances, ensure_ascii=False)
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO portfolio_history (ts, total_portfolio_value, free_cash_eur, balances_json) VALUES (?,?,?,?)",
            (ts, total_portfolio_value, free_cash_eur, balances_json)
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_market_data(limit: int = 50) -> List[Dict[str, Any]]:
    """Recupera los últimos N registros de market_data ordenados por timestamp descendente.
    
    Reconstruye los objetos desde extra_json para obtener todos los campos originales.
    """
    conn = connect()
    try:
        cursor = conn.execute(
            """
            SELECT pair, origin, destination, heat_score, change_24h, vol, extra_json, ts
            FROM market_data
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,)
        )
        rows = cursor.fetchall()
        results = []
        for row in rows:
            try:
                # Intentar parsear extra_json primero (tiene datos completos)
                extra = json.loads(row[6]) if row[6] else {}
                # Combinar con campos básicos (en caso de que extra_json esté incompleto)
                entry = {
                    'pair': row[0] or extra.get('pair'),
                    'origin': row[1] or extra.get('origin'),
                    'destination': row[2] or extra.get('destination'),
                    'heat_score': row[3] if row[3] is not None else extra.get('heat_score', 0),
                    '24h': row[4] if row[4] is not None else extra.get('24h', 0),
                    'vol': row[5] if row[5] is not None else extra.get('vol', 0),
                    'timestamp': row[7],
                }
                # Agregar campos adicionales de extra_json
                for key in ['rsi', 'ema200_distance', 'volume_status', 'swap_label', 
                           'current_price', 'price_change_24h', 'vol_pct', 'triple_green',
                           'from_currency', 'to_currency', 'profit_potential', 'note']:
                    if key in extra:
                        entry[key] = extra[key]
                
                results.append(entry)
            except Exception as e:
                # Si falla el parsing, usar datos básicos
                results.append({
                    'pair': row[0],
                    'origin': row[1],
                    'destination': row[2],
                    'heat_score': row[3] or 0,
                    '24h': row[4] or 0,
                    'vol': row[5] or 0,
                    'timestamp': row[7]
                })
        return results
    finally:
        conn.close()


def migrate_from_files(radar_path: Path, state_path: Path) -> Dict[str, Any]:
    """Lee radar.json y state.json y guarda su contenido en la base de datos."""
    init_db()
    migrated = {"market": 0, "portfolio": 0}

    # Migrar radar.json -> market_data
    try:
        if radar_path.exists():
            with open(radar_path, 'r', encoding='utf-8') as rf:
                radar = json.load(rf)
            entries = radar.get('radar_data', []) or []
            migrated['market'] = save_market_data(entries)
    except Exception as e:
        migrated['market_error'] = str(e)

    # Migrar state.json -> portfolio_history (snapshot único)
    try:
        if state_path.exists():
            with open(state_path, 'r', encoding='utf-8') as sf:
                state = json.load(sf)
            save_portfolio_snapshot(state)
            migrated['portfolio'] = 1
    except Exception as e:
        migrated['portfolio_error'] = str(e)

    return migrated


if __name__ == "__main__":
    radar = Path(__file__).parent / "shared" / "radar.json"
    state = Path(__file__).parent / "shared" / "state.json"
    result = migrate_from_files(radar, state)
    print("Migración completada:", result)
