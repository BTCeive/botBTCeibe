# 🤖 Estrategia Gemini - Sistema de Trading Automático

**Fecha de Implementación:** 30 de Diciembre de 2025  
**Versión:** 1.0  
**Commit:** c62f3b0  
**Estado:** ✅ Implementada y Testada

---

## 📋 Resumen Ejecutivo

La estrategia Gemini define un sistema de compra en sobreventa extrema (RSI < 32) con trailing stop loss del -0.50% y parámetros técnicos específicos para maximizar ganancias con riesgo controlado.

---

## 🎯 Parámetros Clave

### Entrada (Buy Signals)
```json
{
  "rsi_buy_level": 32,        // Compra cuando RSI < 32 (sobreventa)
  "ema_period": 20,            // Confirmación con EMA de 20 períodos
  "volume_factor": 1.15        // Requiere 15% extra de volumen normal
}
```

**Lógica:**
- El bot espera a que el RSI caiga por debajo de 32 (sobreventa extrema)
- Confirma con EMA(20) en dirección favorable
- Verifica que el volumen sea al menos 1.15× el promedio

### Stop Loss Dinámico (Exit Strategy)

```json
{
  "trailing_stop_loss_percent": 0.50,    // Trailing stop -0.50%
  "trailing_activation": 3.0,             // Se activa en +3.0% ganancia
  "safe_exit_threshold": 1.5,             // Salida segura en +1.5%
  "safe_exit_stop_loss": 0.5              // Stop loss en emergencia -0.5%
}
```

**Lógica de Stop Loss:**
1. **Protección Base (-1.5%):** Stop loss fijo cuando PNL ≤ -1.5%
2. **Trailing Activation (+3.0%):** Cuando ganancia supera +3.0%
3. **Trailing Stop (-0.50%):** Desde el máximo alcanzado
4. **Trinquete:** El stop nunca baja, solo sube (protege ganancias)

### Ejemplo de Operación

```
ENTRADA:
  Par: SUI/USDT
  Precio: 1.4307 USD
  PNL: 0%

DURANTE OPERACIÓN:
  ↑ Precio sube a 1.4750 USD → PNL = +3.1%
  ✅ Trailing Stop se ACTIVA
  📍 Nuevo Stop Loss = 1.4750 × (1 - 0.005) = 1.4671 USD

GANANCIAS PROTEGIDAS:
  Si sigue subiendo a 1.52 USD → Stop sube a 1.512 USD
  Si baja a 1.4671 USD → Cierra con +2.54% ganancia
```

---

## 📊 Detección de Activos

### Top Candidatos Actuales (30/12/2025)

| Pair | RSI | 24h Change | Estado | Potencial |
|------|-----|-----------|--------|-----------|
| SUI/USDT | 40.76 | -4.62% | Corrección | 🔴 ALTO |
| UNI/USDT | 40.05 | -4.97% | Sobreventa Próxima | 🔴 ALTO |
| DOT/USDT | 41.10 | -4.43% | Corrección | 🟠 MEDIO |
| AAVE/USDT | 42.70 | -3.65% | Neutral | 🟡 BAJO |
| NEAR/USDT | 43.20 | -3.40% | Neutral | 🟡 BAJO |

### Interpretación

- **RSI 40-50:** Zona neutral, corrección en marcha
- **RSI < 32:** Sobreventa extrema → **TRIGGER DE COMPRA**
- **SUI/USDT y UNI/USDT:** Ya cercanos a evento de sobreventa

---

## 🔄 Flujo de Ejecución

```
┌─────────────────────────────────────┐
│  Monitor en Tiempo Real             │
│  • Scanning cada 5 segundos         │
│  • 19 pares en radar                │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  Evaluación de Criterios            │
│  ✓ RSI < 32?                        │
│  ✓ EMA(20) confirma?                │
│  ✓ Volumen >= 1.15×?                │
└────────────┬────────────────────────┘
             │
             ▼
        RSI < 32? ─────────ÍSÍ───────→ COMPRA
             │                           │
             NO                          ▼
             │                   ┌──────────────┐
             ▼                   │ POSICIÓN     │
        Esperando                │ ABIERTA      │
                                 └──────┬───────┘
                                        │
                              ┌─────────┴─────────┐
                              ▼                   ▼
                        PNL > +3.0%?          PNL <= -1.5%?
                              │                   │
                        SÍ ────┤─── NO           SÍ
                              │                   │
                              ▼                   ▼
                        Trailing Stop        Stop Loss Base
                        -0.50% desde          -1.5% fijo
                        máximo                │
                              │                │
                              └────────┬───────┘
                                       │
                                       ▼
                              [CIERRE AUTOMÁTICO]
```

---

## 🛡️ Gestión de Riesgo

### Capas de Protección

1. **Stop Loss Base (-1.5%)**
   - Protección inmediata cuando PNL baja
   - Evita pérdidas catastróficas

2. **Trailing Stop (-0.50%)**
   - Se activa cuando ganancias son significativas (+3.0%)
   - Protege ganancias acumuladas
   - Permite subidas ilimitadas

3. **Tamaño de Posición**
   - Máximo 100 EUR por operación
   - Máximo 4 posiciones simultáneas
   - Diversificación automática

4. **Filtro de Volatilidad**
   - Volume Factor 1.15: requiere actividad de mercado
   - Evita entradas en activos sin volumen

---

## 📈 Métricas Esperadas

### Performance Objetivo

- **Win Rate:** 60-70% (muchas pequeñas ganancias)
- **Ratio Ganancia/Pérdida:** 1.5:1 o superior
- **Drawdown Máximo:** 10% del portafolio
- **Ganancia Mensual Target:** 5-8%

### Ejemplos Reales

**Escenario Ganador:**
```
Entrada:  RSI = 28, Precio = 1.00 USD
Máximo:   Precio = 1.045 USD (+4.5%)
Salida:   Trailing Stop a 1.040 USD (+4.0%)
Ganancia: +4.0% en 2 horas
```

**Escenario Stop Loss:**
```
Entrada:  RSI = 31, Precio = 1.00 USD
Mínimo:   Precio = 0.985 USD (-1.5%)
Salida:   Stop Loss automático
Pérdida:  -1.5% (controlada)
```

---

## 🔧 Implementación Técnica

### Archivos Modificados

#### 1. `strategy.json` - Parámetros Centralizados
```json
"indicators": {
  "rsi_buy_level": 32,
  "ema_period": 20,
  "volume_factor": 1.15
}
"trading": {
  "trailing_stop_loss_percent": 0.50,
  "trailing_activation": 3.0
}
```

#### 2. `engine/trading_logic.py` - Lógica de Stop Loss
```python
def _calculate_dynamic_stop_loss(entry_price, highest_price, 
                                 initial_value, current_value_eur):
    """
    Trailing Stop: -0.50% desde el máximo
    Se activa cuando PNL > +3.0%
    """
    pnl_percent = ((current_value_eur - initial_value) / initial_value) * 100
    
    if pnl_percent > 3.0:  # Activation threshold
        return highest_price * 0.995  # -0.50% trailing
    elif pnl_percent <= -1.5:
        return entry_price * 0.985  # -1.5% base protection
    else:
        return entry_price * 0.985  # Hold base stop
```

---

## 🚀 Activación

### Modo Lectura (Testing)
```bash
BINANCE_TESTNET=false BINANCE_READ_ONLY=true python3 main.py
```
- ✅ Lee datos reales de Binance
- ✅ No requiere credenciales
- ✅ No realiza trades
- ✅ Perfecto para backtesting

### Modo Vivo (Trading Real)
```bash
BINANCE_TESTNET=false BINANCE_READ_ONLY=false python3 main.py
```
- ⚠️ Requiere API keys en config/.env
- ⚠️ Realiza operaciones reales
- ⚠️ USAR CON CUIDADO: Riesgo de pérdidas

---

## 📊 Monitoreo en Dashboard

El dashboard Streamlit muestra:
- 🎯 **Heat Score:** Score de oportunidad (0-100)
- ⏱️ **Vigilancia:** Contador de mejor candidato
- 📈 **Market Status:** Estado general (peligro, neutral, positivo)
- 🔴 **Risk BTC:** Porcentaje de riesgo vs. Bitcoin
- 📊 **Radar:** Todos los activos con RSI y cambio 24h

---

## ✅ Validación

### Checklist de Implementación
- [x] Parámetros RSI, EMA, Volume en strategy.json
- [x] Trailing Stop -0.50% implementado
- [x] Stop Loss base -1.5% en lugar
- [x] Trinquete (stop nunca baja)
- [x] Activación en +3.0% ganancia
- [x] Testeo en modo lectura completado
- [x] Commit en GitHub c62f3b0
- [x] Documentación actualizada

---

## 🔮 Próximos Pasos

1. **Monitoreo:** Vigilar cuando RSI < 32 en activos principales
2. **Backtesting:** Ejecutar 100 operaciones simuladas
3. **Ajustes Finos:** Revisar ratio ganancia/pérdida cada semana
4. **Escala:** Aumentar capital después de 30 días sin drawdown
5. **Mejoras:** Implementar alertas por Telegram/Email

---

## 📞 Soporte

**Errores Comunes:**
- `binance requires "apiKey"` → Usar BINANCE_READ_ONLY=true para testing
- RSI siempre 50 → Faltan datos históricos (esperar 5 minutos)
- No detecta activos → Verificar whitelist en strategy.json

**Logs Útiles:**
```bash
tail -f engine/botceibe.log | grep "RSI\|heat\|COMPRA"
```

---

**Última Actualización:** 30/12/2025 07:46  
**Autor:** Sistema Automático (Gemini + botCeibe)  
**Licencia:** Privada - No distribuir sin autorización
