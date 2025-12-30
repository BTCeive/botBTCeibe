# 🔐 Configuración Final - Sistema de Cascada

## ✅ Estado de la Implementación

### Código Completado

1. **Backend** ([engine/trading_logic.py](engine/trading_logic.py))
   - ✅ Sistema de cascada A/B/C/D implementado (líneas 6843-6867)
   - ✅ Claves forzadas `'24h'`, `'vol'`, `'vol_pct'` (líneas 6161-6168)
   - ✅ Vigilancia con timestamp float (líneas 6894-6905)
   - ✅ **NUEVO**: Logging detallado Grupo A (líneas 6850-6858)
   - ✅ **NUEVO**: Debug de ticker.percentage (líneas 6149-6155)

2. **Frontend** ([dashboard/app.py](dashboard/app.py))
   - ✅ Lectura de claves cortas `'24h'` y `'vol_pct'`
   - ✅ Cronómetro vigilante con conversión float/ISO (líneas 1120-1180)

3. **Configuración** ([bot_config.py](bot_config.py))
   - ✅ Carga de .env desde `config/.env` (línea 12)
   - ✅ Fallback a raíz `.env` si no existe

---

## 🚀 Instrucciones de Activación

### Paso 1: Crear archivo de credenciales

```bash
cd /home/lorenzo/Escritorio/proyect/botCeibe/config
cp .env.example .env
nano .env  # Editar con tus claves reales
```

**Contenido de `config/.env`:**
```ini
BINANCE_API_KEY=tu_clave_api_real
BINANCE_SECRET_KEY=tu_secreto_api_real
BINANCE_TESTNET=false
DB_PATH=multibot.db
```

### Paso 2: Reiniciar el bot

```bash
cd /home/lorenzo/Escritorio/proyect/botCeibe
./start_bot.sh
```

O manualmente:
```bash
pkill -f "python3 main.py"
nohup python3 main.py > bot_run.log 2>&1 &
```

### Paso 3: Verificar logs de cascada

Espera **60 segundos** (ciclo completo del Grupo D) y verifica:

```bash
tail -f bot_run.log | grep -E "GRUPO A|Cascada configurada|Vigilante INICIADO"
```

**Salida esperada:**
```
📊 GRUPO A [1]: XRP/BTC | HEAT=85 | 24h=+2.5% | VOL_CHANGE=+34.2%
📊 GRUPO A [2]: ETH/BTC | HEAT=78 | 24h=+1.8% | VOL_CHANGE=+12.5%
...
Cascada configurada: Grupo A (5s): 5, Grupo B (15s): 3, Grupo C (30s): 4, Grupo D (60s): 8
🔴 Vigilante INICIADO: XRP/BTC | start_ts=1735311245.678 (tipo=float)
```

### Paso 4: Abrir el dashboard

```bash
streamlit run dashboard/app.py
```

Navega a: `http://localhost:8501`

---

## 🔍 Diagnóstico de Problemas

### ❌ Problema: Dashboard muestra guiones (---)

**Causa posible**: API de Binance no responde o falta `.env`

**Solución**:
```bash
# 1. Verificar que .env existe y tiene claves
cat config/.env

# 2. Ver logs del bot
tail -n 100 bot_run.log | grep -E "ERROR|WARNING|percentage=None"

# 3. Si ves "⚠️ XRP/BTC: ticker.percentage=None", hay problema de API
# Reiniciar con kill -9 y volver a lanzar
```

### ❌ Problema: Cronómetro muestra "Iniciando..." siempre

**Causa posible**: `start_ts` no se guarda como float

**Solución**:
```bash
# Ver contenido de vigilancia_state.json
cat shared/vigilancia_state.json

# Debe verse así:
# {"current_pair": "XRP/BTC", "start_ts": 1735311245.678, ...}

# Si ves start_ts como string ISO ("2025-12-27T..."), reiniciar bot
```

### ❌ Problema: No aparece logging de "GRUPO A"

**Causa posible**: Bot atascado en inicialización

**Solución**:
```bash
# Matar proceso
pkill -9 -f "python3 main.py"

# Ver último error
tail -n 50 bot_run.log

# Reinstalar dependencias si falta alguna
pip3 install -r requirements.txt --break-system-packages
```

---

## 📊 Grupos de Cascada Detallados

| Grupo | Frecuencia | Criterio | Ejemplo |
|-------|-----------|----------|---------|
| **A** | 5s | Top 5 radar | XRP/BTC, ETH/BTC, BNB/BTC... |
| **B** | 15s | HEAT > 60 | SOL/EUR, ADA/BTC... |
| **C** | 30s | HEAT > 40 | MATIC/EUR, LINK/BTC... |
| **D** | 60s | Resto | Pares fríos o sin volumen |

### Prioridades adicionales:
- **Slots activos** → Siempre Grupo A (actualización cada 5s)
- **Vigilante (*)** → Siempre Grupo A mientras espera confirmación

---

## 🎯 Claves de Datos

El motor genera **dos conjuntos de claves** por compatibilidad:

### Claves CORTAS (preferidas - nuevas):
```python
{
    '24h': 2.5,        # % cambio 24h
    'vol': 125000.0,   # Volumen quote en USDT/EUR
    'vol_pct': 34.2    # % cambio volumen 24h
}
```

### Claves LARGAS (fallback - antiguas):
```python
{
    'change_24h': 2.5,
    'price_change_24h': 2.5,
    'volume_change': 34.2,
    'volume_change_24h': 34.2
}
```

El dashboard lee **primero las cortas**, si no existen usa las largas.

---

## ✅ Checklist Final

- [ ] Archivo `config/.env` creado con claves reales
- [ ] Bot reiniciado: `./start_bot.sh`
- [ ] Logs muestran "GRUPO A" y "Cascada configurada"
- [ ] Dashboard muestra números en lugar de guiones
- [ ] Cronómetro vigilante (*) muestra "Xm Ys" en lugar de "Iniciando..."
- [ ] LEDs muestran colores (verde/rojo) según cambios 24h y volumen

---

## 📖 Archivos Relacionados

- [SISTEMA_CASCADE.md](SISTEMA_CASCADE.md) - Documentación técnica del sistema
- [config/.env.example](config/.env.example) - Plantilla de credenciales
- [bot_config.py](bot_config.py) - Carga de variables de entorno
- [start_bot.sh](start_bot.sh) - Script de inicio automático
