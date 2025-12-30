# botCeibe - Bot de Trading Algorítmico

Bot de trading con arquitectura limpia y separación de responsabilidades.

## 📁 Estructura

```
config/
│   └── strategy.json          # Parámetros de configuración (monto, RSI, stop_loss, etc.)
engine/
│   └── trading_logic.py       # Motor de trading (lee strategy.json)
shared/
│   └── state.json             # Estado compartido (escrito por el motor, leído por el dashboard)
dashboard/
│   └── app.py                 # Dashboard Streamlit (solo lectura de state.json)
main.py                        # Punto de entrada del bot
```

## 🚀 Uso

### Ejecutar el Motor

```bash
cd /home/lorenzo/Escritorio/proyect/botCeibe
python3 main.py
```

### Ejecutar el Dashboard

```bash
cd /home/lorenzo/Escritorio/proyect/botCeibe
streamlit run dashboard/app.py
```

## ⚙️ Configuración

Todos los parámetros se configuran en `config/strategy.json`:

- **trading**: Monto por operación, máximo de slots, trailing stop, etc.
- **indicators**: RSI de compra/venta, EMA200, umbral de volumen
- **risk**: Stop loss, drawdown máximo, modo ahorro
- **whitelist**: Lista de monedas permitidas
- **scan_interval**: Intervalo de escaneo en segundos

Para cambiar la configuración, edita `strategy.json` y reinicia el motor.

### ⚠️ Parámetro Crítico: `jump_heat_score_difference`

**Valor por defecto**: `15`

Este parámetro controla cuánto mejor debe ser el Heat Score de una moneda para que el bot "salte" desde la actual. 

**Riesgo**: Si el valor es muy bajo (10-15), el bot puede hacer **overtrading** (saltos excesivos), generando muchas comisiones.

**Recomendación**: 
- Si ves muchos saltos en los logs, aumenta este valor a **25-30**
- Revisa `PARAMETROS_CRITICOS.md` para más detalles

**Ejemplo**:
```json
{
  "trading": {
    "jump_heat_score_difference": 25  // Más conservador
  }
}
```

## 🔄 Flujo de Datos

1. **Motor** (`main.py` → `trading_logic.py`):
   - Lee `config/strategy.json`
   - Ejecuta lógica de trading
   - Escribe `shared/state.json`

2. **Dashboard** (`app.py`):
   - Lee `shared/state.json`
   - Muestra información en tiempo real
   - No hace llamadas directas a la API

## 📝 Notas

- El motor y el dashboard son independientes
- El dashboard se actualiza automáticamente cada 5 segundos
- El estado compartido se actualiza cada N ticks (configurable)

