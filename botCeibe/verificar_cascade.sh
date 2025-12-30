#!/bin/bash
# Script de verificación rápida del sistema de cascada

echo "============================================================"
echo "🔍 VERIFICACIÓN RÁPIDA - Sistema de Cascada"
echo "============================================================"
echo ""

# 1. Verificar archivo .env
echo "1️⃣  Verificando config/.env..."
if [ -f "config/.env" ]; then
    echo "   ✅ config/.env existe"
    # No mostrar contenido por seguridad, solo verificar que tenga claves
    if grep -q "BINANCE_API_KEY=" config/.env && grep -q "BINANCE_SECRET_KEY=" config/.env; then
        echo "   ✅ Claves API configuradas"
    else
        echo "   ❌ Faltan claves API en config/.env"
        echo "   💡 Edita config/.env con tus credenciales reales"
    fi
else
    echo "   ❌ config/.env NO existe"
    echo "   💡 Copia: cp config/.env.example config/.env"
    echo "   💡 Edita: nano config/.env"
fi
echo ""

# 2. Verificar si el bot está corriendo
echo "2️⃣  Verificando proceso del bot..."
BOT_PID=$(pgrep -f "python3 main.py")
if [ -n "$BOT_PID" ]; then
    echo "   ✅ Bot corriendo (PID: $BOT_PID)"
else
    echo "   ❌ Bot NO está corriendo"
    echo "   💡 Inicia con: ./start_bot.sh"
fi
echo ""

# 3. Verificar logs de cascada
echo "3️⃣  Verificando logs de cascada (últimos 30s)..."
if [ -f "bot_run.log" ]; then
    # Buscar logs de Grupo A
    GRUPO_A=$(tail -n 200 bot_run.log | grep -c "GRUPO A")
    CASCADE_CONFIG=$(tail -n 200 bot_run.log | grep -c "Cascada configurada")
    
    if [ "$GRUPO_A" -gt 0 ]; then
        echo "   ✅ Logging de Grupo A detectado ($GRUPO_A líneas)"
        echo "   📊 Últimas asignaciones Grupo A:"
        tail -n 200 bot_run.log | grep "GRUPO A" | tail -3 | sed 's/^/      /'
    else
        echo "   ⚠️  No se detectó logging de Grupo A"
        echo "   💡 El bot puede estar inicializándose (espera 60s)"
    fi
    
    if [ "$CASCADE_CONFIG" -gt 0 ]; then
        echo "   ✅ Cascada configurada"
        tail -n 200 bot_run.log | grep "Cascada configurada" | tail -1 | sed 's/^/      /'
    else
        echo "   ⚠️  No se detectó configuración de cascada"
    fi
else
    echo "   ❌ bot_run.log NO existe"
    echo "   💡 Inicia el bot primero"
fi
echo ""

# 4. Verificar vigilancia_state.json
echo "4️⃣  Verificando vigilancia_state.json..."
if [ -f "shared/vigilancia_state.json" ]; then
    echo "   ✅ vigilancia_state.json existe"
    
    # Verificar si start_ts es float
    START_TS=$(cat shared/vigilancia_state.json | grep -o '"start_ts":[^,}]*' | cut -d: -f2 | tr -d ' ')
    
    if [[ "$START_TS" =~ ^[0-9]+\.[0-9]+$ ]]; then
        echo "   ✅ start_ts es FLOAT: $START_TS"
    elif [[ "$START_TS" =~ ^\".*\"$ ]]; then
        echo "   ❌ start_ts es STRING: $START_TS"
        echo "   💡 Reinicia el bot para actualizar formato"
    else
        echo "   ⚠️  start_ts tiene formato desconocido: $START_TS"
    fi
    
    CURRENT_PAIR=$(cat shared/vigilancia_state.json | grep -o '"current_pair":"[^"]*"' | cut -d: -f2 | tr -d '"')
    if [ -n "$CURRENT_PAIR" ]; then
        echo "   📍 Par vigilado: $CURRENT_PAIR"
    fi
else
    echo "   ⚠️  vigilancia_state.json NO existe"
    echo "   💡 Se creará en el primer ciclo del radar"
fi
echo ""

# 5. Verificar state.json y radar
echo "5️⃣  Verificando state.json..."
if [ -f "shared/state.json" ]; then
    echo "   ✅ state.json existe"
    
    # Contar pares en radar
    RADAR_COUNT=$(cat shared/state.json | grep -o '"pair":' | wc -l)
    echo "   📊 Radar tiene $RADAR_COUNT pares"
    
    # Verificar si hay claves '24h' y 'vol_pct'
    HAS_24H=$(cat shared/state.json | grep -c '"24h":')
    HAS_VOL_PCT=$(cat shared/state.json | grep -c '"vol_pct":')
    
    if [ "$HAS_24H" -gt 0 ] && [ "$HAS_VOL_PCT" -gt 0 ]; then
        echo "   ✅ Claves '24h' y 'vol_pct' presentes"
    else
        echo "   ⚠️  Claves cortas no detectadas (24h: $HAS_24H, vol_pct: $HAS_VOL_PCT)"
        echo "   💡 Espera a que el bot complete un ciclo de radar"
    fi
else
    echo "   ❌ state.json NO existe"
    echo "   💡 Inicia el bot para generar el estado"
fi
echo ""

# 6. Verificar errores recientes
echo "6️⃣  Verificando errores recientes..."
if [ -f "bot_run.log" ]; then
    ERRORS=$(tail -n 200 bot_run.log | grep -c "ERROR")
    WARNINGS=$(tail -n 200 bot_run.log | grep -c "WARNING")
    
    echo "   📊 Últimos 200 logs: $ERRORS errores, $WARNINGS advertencias"
    
    if [ "$ERRORS" -gt 0 ]; then
        echo "   ⚠️  Últimos errores:"
        tail -n 200 bot_run.log | grep "ERROR" | tail -3 | sed 's/^/      /'
    fi
fi
echo ""

# Resumen
echo "============================================================"
echo "📋 RESUMEN"
echo "============================================================"

CHECKS=0
TOTAL=6

[ -f "config/.env" ] && grep -q "BINANCE_API_KEY=" config/.env && ((CHECKS++))
[ -n "$BOT_PID" ] && ((CHECKS++))
[ "$GRUPO_A" -gt 0 ] && ((CHECKS++))
[[ "$START_TS" =~ ^[0-9]+\.[0-9]+$ ]] && ((CHECKS++))
[ -f "shared/state.json" ] && [ "$RADAR_COUNT" -gt 0 ] && ((CHECKS++))
[ "$HAS_24H" -gt 0 ] && [ "$HAS_VOL_PCT" -gt 0 ] && ((CHECKS++))

echo "✅ Verificaciones pasadas: $CHECKS/$TOTAL"
echo ""

if [ "$CHECKS" -eq "$TOTAL" ]; then
    echo "🎉 Sistema completamente operativo"
    echo "💡 Abre el dashboard: streamlit run dashboard/app.py"
elif [ "$CHECKS" -ge 3 ]; then
    echo "⚠️  Sistema parcialmente operativo"
    echo "💡 Revisa las advertencias arriba"
else
    echo "❌ Sistema requiere configuración"
    echo "💡 Sigue los pasos en ACTIVACION_FINAL.md"
fi
echo ""
