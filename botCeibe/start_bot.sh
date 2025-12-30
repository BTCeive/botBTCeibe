#!/bin/bash
# Script para iniciar el bot por fases

BOT_DIR="/home/lorenzo/Escritorio/proyect/botCeibe"
LOG_FILE="$BOT_DIR/bot_startup.log"
PID_FILE="$BOT_DIR/bot.pid"

cd "$BOT_DIR" || exit 1

# Función para loggear
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Fase 1: Verificar entorno
log "Fase 1: Verificando entorno..."
if [ ! -f "$BOT_DIR/venv/bin/activate" ]; then
    log "ERROR: Virtual environment no encontrado"
    exit 1
fi

if [ ! -f "$BOT_DIR/main.py" ]; then
    log "ERROR: main.py no encontrado"
    exit 1
fi

log "✅ Entorno verificado"
sleep 1

# Fase 2: Activar entorno virtual
log "Fase 2: Activando entorno virtual..."
source "$BOT_DIR/venv/bin/activate"
log "✅ Entorno virtual activado"
sleep 1

# Fase 3: Verificar dependencias básicas
log "Fase 3: Verificando dependencias..."
python3 -c "import ccxt; import asyncio" 2>/dev/null
if [ $? -ne 0 ]; then
    log "ERROR: Dependencias faltantes"
    exit 1
fi
log "✅ Dependencias verificadas"
sleep 1

# Fase 4: Verificar configuración
log "Fase 4: Verificando configuración..."
if [ ! -f "$BOT_DIR/config/strategy.json" ]; then
    log "ERROR: strategy.json no encontrado"
    exit 1
fi

if [ ! -f "$BOT_DIR/config/.env" ]; then
    log "ERROR: .env no encontrado"
    exit 1
fi
log "✅ Configuración verificada"
sleep 1

# Fase 5: Matar procesos anteriores si existen
log "Fase 5: Limpiando procesos anteriores..."
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        log "Matando proceso anterior (PID: $OLD_PID)..."
        kill -9 "$OLD_PID" 2>/dev/null
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Matar cualquier proceso de main.py que esté corriendo
pkill -f "python.*main.py" 2>/dev/null
sleep 1
log "✅ Procesos anteriores limpiados"
sleep 1

# Fase 6: Iniciar el bot
log "Fase 6: Iniciando bot..."
nohup python3 main.py > /dev/null 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$PID_FILE"
log "✅ Bot iniciado con PID: $NEW_PID"
sleep 2

# Fase 7: Verificar que el bot está corriendo
log "Fase 7: Verificando que el bot está corriendo..."
if ps -p "$NEW_PID" > /dev/null 2>&1; then
    log "✅ Bot corriendo correctamente (PID: $NEW_PID)"
else
    log "ERROR: El bot no está corriendo después del inicio"
    rm -f "$PID_FILE"
    exit 1
fi

log "=========================================="
log "Bot iniciado exitosamente"
log "PID: $NEW_PID"
log "=========================================="

