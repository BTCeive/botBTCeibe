"""
Módulo de base de datos para el bot de trading.
Gestiona trades, treasury y operaciones.
"""
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class Database:
    """Clase para gestionar la base de datos SQLite del bot."""
    
    def __init__(self, db_path: str):
        """
        Inicializa la conexión con la base de datos.
        
        Args:
            db_path: Ruta al archivo de base de datos SQLite
        """
        self.db_path = db_path
        self._init_database()
    
    def _get_connection(self):
        """Obtiene una conexión a la base de datos."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_database(self):
        """Inicializa las tablas de la base de datos si no existen."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Tabla de trades
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slot_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                base_asset TEXT NOT NULL,
                target_asset TEXT NOT NULL,
                amount REAL NOT NULL,
                entry_price REAL NOT NULL,
                initial_fiat_value REAL NOT NULL,
                path_history TEXT,
                highest_price REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                deactivated_at TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        # Tabla de treasury (incluye Hucha Oportunista y Tesoro Guardado)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS treasury (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP NOT NULL,
                amount_eur REAL NOT NULL DEFAULT 0.0,
                amount_btc REAL NOT NULL DEFAULT 0.0,
                description TEXT
            )
        """)
        
        # Tabla de snapshots del portfolio
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP NOT NULL,
                total_value REAL NOT NULL,
                free_cash_eur REAL NOT NULL
            )
        """)
        
        conn.commit()
        conn.close()
        logger.debug(f"Base de datos inicializada: {self.db_path}")
    
    def execute_query(self, query: str, params: tuple = ()):
        """Ejecuta una query y retorna el resultado."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            conn.commit()
            return cursor.fetchall()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error ejecutando query: {e}")
            raise
        finally:
            conn.close()
    
    # ========== MÉTODOS DE TRADES ==========
    
    def create_trade(self, slot_id: int, symbol: str, base_asset: str,
                     target_asset: str, amount: float, entry_price: float,
                     initial_fiat_value: float, path_history: str = "",
                     highest_price: Optional[float] = None, **kwargs) -> int:
        """
        Crea un nuevo trade.
        
        Returns:
            ID del trade creado
        """
        query = """
            INSERT INTO trades 
            (slot_id, symbol, base_asset, target_asset, amount, entry_price, 
             initial_fiat_value, path_history, highest_price, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """
        params = (slot_id, symbol, base_asset, target_asset, amount, 
                 entry_price, initial_fiat_value, path_history, highest_price or entry_price)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            conn.commit()
            trade_id = cursor.lastrowid
            return trade_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creando trade: {e}")
            raise
        finally:
            conn.close()
    
    def get_active_trade(self, slot_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene el trade activo de un slot."""
        query = """
            SELECT * FROM trades 
            WHERE slot_id = ? AND is_active = 1
            ORDER BY created_at DESC
            LIMIT 1
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query, (slot_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()
    
    def get_all_active_trades(self) -> List[Dict[str, Any]]:
        """Obtiene todos los trades activos."""
        query = """
            SELECT * FROM trades 
            WHERE is_active = 1
            ORDER BY slot_id
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    
    def deactivate_trade(self, trade_id: int):
        """Desactiva un trade."""
        query = """
            UPDATE trades 
            SET is_active = 0, deactivated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """
        self.execute_query(query, (trade_id,))
    
    def update_trade(self, trade_id: int, **kwargs):
        """Actualiza campos de un trade."""
        if not kwargs:
            return
        
        set_clauses = []
        params = []
        for key, value in kwargs.items():
            set_clauses.append(f"{key} = ?")
            params.append(value)
        
        params.append(trade_id)
        query = f"UPDATE trades SET {', '.join(set_clauses)} WHERE id = ?"
        self.execute_query(query, tuple(params))
    
    def update_highest_price(self, trade_id: int, price: float):
        """Actualiza el precio más alto alcanzado por un trade."""
        query = """
            UPDATE trades 
            SET highest_price = MAX(highest_price, ?)
            WHERE id = ?
        """
        self.execute_query(query, (price, trade_id))
    
    # ========== MÉTODOS DE TREASURY ==========
    
    def add_to_treasury(self, amount_eur: float, amount_btc: float, description: str = ""):
        """
        Registra una entrada en la hucha/tesorería.
        
        Args:
            amount_eur: Cantidad en EUR a agregar
            amount_btc: Cantidad en BTC a agregar
            description: Descripción de la transacción
        """
        query = """
            INSERT INTO treasury (timestamp, amount_eur, amount_btc, description) 
            VALUES (?, ?, ?, ?)
        """
        params = (datetime.now(), amount_eur, amount_btc, description)
        self.execute_query(query, params)
        logger.info(
            f"💰 Treasury actualizado: {amount_eur:.2f} EUR + {amount_btc:.8f} BTC - {description}"
        )
    
    def get_total_treasury(self) -> Dict[str, float]:
        """
        Obtiene el total acumulado del treasury (EUR y BTC).
        
        Returns:
            Dict con 'total_eur' y 'total_btc'
        """
        query = """
            SELECT 
                COALESCE(SUM(amount_eur), 0.0) as total_eur,
                COALESCE(SUM(amount_btc), 0.0) as total_btc
            FROM treasury
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query)
            row = cursor.fetchone()
            if row:
                return {
                    'total_eur': row[0] or 0.0,
                    'total_btc': row[1] or 0.0
                }
            return {'total_eur': 0.0, 'total_btc': 0.0}
        finally:
            conn.close()
    
    def save_portfolio_snapshot(self, total_value: float, free_cash_eur: float):
        """
        Guarda un snapshot del portfolio.
        
        Args:
            total_value: Valor total del portfolio en EUR
            free_cash_eur: Efectivo libre en EUR
        """
        query = """
            INSERT INTO portfolio_snapshots (timestamp, total_value, free_cash_eur)
            VALUES (?, ?, ?)
        """
        params = (datetime.now(), total_value, free_cash_eur)
        self.execute_query(query, params)
        logger.debug(f"📊 Snapshot guardado: Portfolio={total_value:.2f}€, Free Cash={free_cash_eur:.2f}€")

