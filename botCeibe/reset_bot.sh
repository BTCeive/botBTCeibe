#!/bin/bash
# Script para limpiar slots activos y reiniciar el bot

BOT_DIR="/home/ubuntu/botCeibe"
DB_FILE="$BOT_DIR/multibot.db"

cd "$BOT_DIR" || exit 1

echo "Limpiando slots activos..."

# Usar Python para limpiar los trades activos
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/ubuntu/botCeibe')

from database import Database

db = Database('multibot.db')
active_trades = db.get_all_active_trades()

print(f"Trades activos encontrados: {len(active_trades)}")

# Cerrar todos los trades activos (marcarlos como cerrados sin ejecutar orden de venta)
for trade in active_trades:
    db.deactivate_trade(trade['id'])
    print(f"Trade cerrado: Slot {trade['slot_id']}, {trade['target_asset']}")

print("✅ Todos los trades activos han sido cerrados")
EOF

echo "Reiniciando bot..."
./start_bot.sh

