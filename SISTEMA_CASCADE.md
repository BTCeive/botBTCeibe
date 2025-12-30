# 🔄 Sistema de Actualización en Cascada - botCeibe

## 📋 Resumen

Sistema implementado para **optimizar llamadas a la API de Binance** y evitar rate limits que causan datos N/A.

## 🎯 Grupos de Actualización

### Grupo A: Prioridad Máxima (5s)
- **Top 5** del radar por HEAT score
- **Slots activos** (posiciones abiertas)
- **Vigilante** (slot con *)

### Grupo B: Alta Prioridad (15s)
- Pares con **HEAT > 60**

### Grupo C: Prioridad Media (30s)
- Pares con **HEAT > 40**

### Grupo D: Baja Prioridad (60s)
- Resto de pares

## 📊 Claves de Datos Forzadas

El motor ahora genera estas **claves cortas**:

```python
{
    '24h': float,          # Cambio 24h (%)
    'vol': float,          # Volumen quote (USDT/EUR)
    'vol_pct': float       # Cambio volumen 24h (%)
}
```

El dashboard lee primero estas claves, con fallback a las antiguas para compatibilidad.

## ⏱️ Vigilante con Float Timestamp

```python
{
    "current_pair": "XRP/BTC",
    "start_ts": 1735310684.523  # time.time() float, no ISO string
}
```

El dashboard calcula el tiempo real como "Xm Ys" (ej: "14m 20s").

## 🔧 Implementación

### Backend (engine/trading_logic.py)

**Líneas 6830-6875**: Asignación de grupos
```python
for idx, item in enumerate(radar_data):
    heat = item.get('heat_score', 0)
    
    if idx < 5:  # Top 5
        item['update_group'] = 'A'
        item['update_frequency'] = 5
    elif heat > 60:
        item['update_group'] = 'B'
        item['update_frequency'] = 15
    elif heat > 40:
        item['update_group'] = 'C'
        item['update_frequency'] = 30
    else:
        item['update_group'] = 'D'
        item['update_frequency'] = 60
    
    item['last_update_ts'] = current_time
```

**Líneas 6142-6170**: Claves forzadas
```python
return {
    # Claves cortas (preferidas)
    '24h': float(price_change_24h),
    'vol': float(quote_volume_raw),
    'vol_pct': float(volume_change_24h),
    
    # Claves antiguas (fallback)
    'change_24h': float(price_change_24h),
    'volume_change': float(volume_change_24h),
}
```

### Frontend (dashboard/app.py)

**Líneas ~1322 y ~1399**: Mapeo de claves
```python
# Leer '24h' y 'vol_pct' primero
cambio_24h = (item.get('24h') or item.get('change_24h') or 
              item.get('price_change_24h') or 0.0)
vol_change = (item.get('vol_pct') or item.get('volume_change') or 0.0)
```

**Líneas 1124-1179**: Cronómetro vigilante
```python
start_ts = vigilancia.get('start_ts', 0)
if isinstance(start_ts, float) and start_ts > 0:
    elapsed = int(current_time - start_ts)
    mins = elapsed // 60
    secs = elapsed % 60
    time_display = f"{mins}m {secs}s"
else:
    time_display = "Iniciando..."
```

## ✅ Estado Actual

- ✅ Código implementado en trading_logic.py
- ✅ Código implementado en dashboard/app.py
- ⚠️ **Falta .env** con API keys de Binance
- ⏳ Pendiente prueba real con bot corriendo

## 🚀 Próximos Pasos

1. Configurar archivo `.env` con credenciales:
   ```bash
   BINANCE_API_KEY=tu_api_key
   BINANCE_API_SECRET=tu_api_secret
   ```

2. Reiniciar bot:
   ```bash
   ./start_bot.sh
   ```

3. Verificar logs de cascada:
   ```bash
   tail -f bot_run.log | grep -E "(Grupo|update_group|CASCADE)"
   ```

4. Ver dashboard:
   ```bash
   streamlit run dashboard/app.py
   ```

## 🎨 Estética del Dashboard

- ✅ Tablas paralelas 2x10 (impares/pares)
- ✅ Botón ➕/➖ para expandir a 15 filas
- ✅ LEDs con box-shadow (5 colores)
- ✅ Texto blanco (#FFFFFF)
- ✅ Sin bordes negros (border: none)
- ✅ Cronómetro vigilante en tiempo real

## 📈 Beneficios Esperados

1. **Menos errores 429** de Binance (Too Many Requests)
2. **Datos N/A eliminados** gracias a claves forzadas
3. **Refresh inteligente** - actualiza lo importante más seguido
4. **Mejor UX** - cronómetro real, LEDs funcionales, estética Bloomberg
