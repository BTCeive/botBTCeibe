#!/bin/bash
# Script para iniciar el dashboard Flask (sin JavaScript) en el puerto 80

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Activar entorno virtual
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "⚠️  Entorno virtual no encontrado. Usando Python del sistema."
fi

# Verificar que Flask esté instalado
python3 -c "import flask" 2>/dev/null || {
    echo "Instalando Flask..."
    pip install flask
}

# Detener procesos anteriores
pkill -f "dashboard_flask.py" 2>/dev/null
sleep 1

# Iniciar dashboard Flask (sin JavaScript) en puerto 80
echo "🚀 Iniciando dashboard Flask (sin JavaScript) en puerto 80..."
echo "📊 El dashboard se auto-actualiza cada 10 segundos sin necesidad de JavaScript"
nohup python3 dashboard_flask.py > dashboard_flask.log 2>&1 &
DASHBOARD_PID=$!

sleep 2

# Verificar que se inició correctamente
if ps -p $DASHBOARD_PID > /dev/null; then
    echo "✅ Dashboard iniciado correctamente. PID: $DASHBOARD_PID"
    echo "🌐 Accede en: http://$(hostname -I | awk '{print $1}'):80"
    echo "📝 Logs en: dashboard_flask.log"
else
    echo "❌ Error al iniciar el dashboard. Revisa dashboard_flask.log"
    exit 1
fi

