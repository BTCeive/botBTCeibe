#!/usr/bin/env python3
"""
Test de acceso concurrente a SQLite en modo WAL
Simula escrituras del motor mientras el dashboard lee
"""
import sqlite3
import time
import sys
from pathlib import Path
from threading import Thread

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))
from storage import save_market_data, save_portfolio_snapshot, connect

def writer_thread():
    """Simula escrituras continuas del motor"""
    print("🔵 Escritor iniciado")
    for i in range(10):
        try:
            # Simular datos de radar
            radar = [
                {
                    'origin': 'EUR',
                    'destination': 'BTC',
                    'pair': 'BTC/EUR',
                    'swap_label': 'BTC→EUR',
                    'heat_score': 85.5 + i,
                    '24h': 2.3,
                    'vol_pct': 0.456,
                    'vol': 125000
                }
            ]
            save_market_data(radar, ts=int(time.time()))
            
            # Simular snapshot de portfolio
            portfolio = {
                'total_portfolio_value': 10000 + i*100,
                'free_cash_eur': 5000 + i*50,
                'balances': {'BTC': 0.1, 'EUR': 5000}
            }
            save_portfolio_snapshot(portfolio)
            
            print(f"✅ Escritura #{i+1} completada")
            time.sleep(0.5)
        except Exception as e:
            print(f"❌ Error en escritura #{i+1}: {e}")
    print("🔵 Escritor finalizado")

def reader_thread():
    """Simula lecturas continuas del dashboard"""
    print("🟢 Lector iniciado")
    for i in range(20):
        try:
            conn = connect()
            cur = conn.cursor()
            
            # Leer últimos datos del radar
            cur.execute("SELECT COUNT(*) FROM market_data")
            count = cur.fetchone()[0]
            
            # Leer último portfolio
            cur.execute("SELECT COUNT(*) FROM portfolio_history")
            port_count = cur.fetchone()[0]
            
            conn.close()
            print(f"📖 Lectura #{i+1}: {count} radar, {port_count} portfolio")
            time.sleep(0.3)
        except Exception as e:
            print(f"❌ Error en lectura #{i+1}: {e}")
    print("🟢 Lector finalizado")

if __name__ == '__main__':
    print("=" * 60)
    print("Test de Acceso Concurrente SQLite (WAL)")
    print("=" * 60)
    
    # Verificar WAL
    conn = connect()
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    print(f"Modo journal: {mode}")
    conn.close()
    
    if mode != 'wal':
        print("⚠️  ADVERTENCIA: WAL no está activado!")
    
    # Lanzar threads concurrentes
    writer = Thread(target=writer_thread, daemon=True)
    reader = Thread(target=reader_thread, daemon=True)
    
    print("\n🚀 Iniciando test de concurrencia...")
    print("   - Escritor: 10 escrituras (cada 0.5s)")
    print("   - Lector: 20 lecturas (cada 0.3s)")
    print()
    
    writer.start()
    time.sleep(0.2)  # Pequeño delay para que el escritor empiece primero
    reader.start()
    
    # Esperar a que terminen
    writer.join()
    reader.join()
    
    print("\n" + "=" * 60)
    print("✅ Test completado - No debe haber errores de bloqueo")
    print("=" * 60)
