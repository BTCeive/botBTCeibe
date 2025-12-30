#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "[EMERGENCY_RESTART] Iniciando procedimiento de reinicio de Engine y Dashboard"

# Activar venv si existe
if [ -f "$ROOT_DIR/venv/bin/activate" ]; then
  echo "Activando venv"
  # shellcheck disable=SC1091
  source "$ROOT_DIR/venv/bin/activate"
fi

# Validar sintaxis python
echo "Compilando archivos modificados (py_compile)"
python3 -m py_compile engine/trading_logic.py dashboard/app.py || true

# Iniciar Engine
echo "Iniciando Engine (main.py)"
nohup python3 main.py > botceibe.log 2>&1 &
sleep 2

# Iniciar Dashboard (Streamlit)
echo "Iniciando Dashboard (streamlit run dashboard/app.py)"
nohup streamlit run dashboard/app.py --server.port 8501 --server.headless true > dashboard.log 2>&1 &

sleep 2

# Mostrar estado de procesos
echo "Procesos relevantes (ps):"
ps aux | grep -E 'main.py|streamlit|dashboard/app.py' | grep -v grep || true

# Mostrar últimas entradas de logs y bitacora
echo "Últimas líneas de botceibe.log (si existe):"
[ -f botceibe.log ] && tail -n 50 botceibe.log || echo "botceibe.log no existe"

echo "Últimas líneas de dashboard.log (si existe):"
[ -f dashboard.log ] && tail -n 50 dashboard.log || echo "dashboard.log no existe"

echo "Últimas líneas de bitacora.txt (si existe):"
[ -f bitacora.txt ] && tail -n 50 bitacora.txt || echo "bitacora.txt no existe"

echo "[EMERGENCY_RESTART] Completado"