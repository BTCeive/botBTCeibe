#!/bin/bash
# Script para iniciar el dashboard limpiando sesiones anteriores

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo "🧹 Limpiando sesiones anteriores del dashboard..."

# Detener todos los procesos del dashboard
pkill -9 -f "dashboard_flask.py" 2>/dev/null
pkill -9 -f "python.*dashboard" 2>/dev/null
sleep 2

# Verificar que no queden procesos
REMAINING=$(ps aux | grep -E "dashboard_flask|python.*dashboard" | grep -v grep | wc -l)
if [ "$REMAINING" -gt 0 ]; then
    echo "⚠️ Aún hay $REMAINING procesos. Forzando cierre..."
    pkill -9 -f "dashboard_flask" 2>/dev/null
    sleep 2
fi

# Verificar que el puerto esté libre
PORT_IN_USE=$(netstat -tlnp 2>/dev/null | grep ':8080 ' || ss -tlnp 2>/dev/null | grep ':8080 ' || echo "")
if [ -n "$PORT_IN_USE" ]; then
    echo "⚠️ Puerto 8080 en uso. Esperando liberación..."
    sleep 3
fi

# Activar entorno virtual
if [ ! -d "venv" ]; then
    echo "❌ Error: No se encuentra el entorno virtual (venv)"
    exit 1
fi

source venv/bin/activate

# Verificar que Flask esté instalado
python3 -c "import flask" 2>/dev/null || {
    echo "Instalando Flask..."
    pip install flask
}

# Limpiar log anterior
if [ -f "dashboard_flask.log" ]; then
    mv dashboard_flask.log dashboard_flask.log.old 2>/dev/null
fi

echo "✅ Iniciando dashboard Flask en puerto 8080..."
echo "   El dashboard se auto-actualiza cada 10 segundos"
echo ""

# Iniciar dashboard
nohup python3 dashboard_flask.py > dashboard_flask.log 2>&1 &
DASHBOARD_PID=$!

sleep 3

# Verificar que se inició correctamente
if ps -p $DASHBOARD_PID > /dev/null 2>&1; then
    echo "✅ Dashboard iniciado correctamente. PID: $DASHBOARD_PID"
    echo ""
    echo "📊 URLs disponibles:"
    echo "   - http://localhost:8080"
    echo "   - http://192.168.1.137:8080"
    echo ""
    echo "📝 Logs: tail -f dashboard_flask.log"
    echo ""
    echo "🛑 Para detener: pkill -f dashboard_flask.py"
else
    echo "❌ Error: El dashboard no se inició correctamente"
    echo "Revisa los logs: cat dashboard_flask.log"
    exit 1
fi

