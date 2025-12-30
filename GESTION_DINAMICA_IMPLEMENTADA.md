# Gestión Dinámica de Capital - Implementación Completa

## ✅ Funciones Implementadas

### 1. `_calculate_real_investment_balance()`
**Ubicación**: `engine/trading_logic.py` línea ~440

Calcula el saldo real de inversión excluyendo:
- **Reserva de Gas (BNB)**: 2.5% - 5% del valor total (intocable)
- **Hucha diversificada**: Activos guardados en `hucha_diversificada.json`

**Retorna**:
```python
{
    'total_portfolio_eur': float,
    'gas_reserve_eur': float,
    'hucha_total_eur': float,
    'real_investment_balance_eur': float,  # Capital disponible para trading
    'gas_percentage': float
}
```

### 2. `_detect_overexposure()`
**Ubicación**: `engine/trading_logic.py` línea ~440

Detecta activos que superan el 25% del capital real.

**Retorna**: Lista de activos sobreexpuestos con:
- `currency`: Activo sobreexpuesto
- `current_value_eur`: Valor actual
- `current_percent`: Porcentaje actual del portfolio
- `excess_value_eur`: Valor que excede el 25% (capital disponible para swaps)
- `excess_percent`: Porcentaje de exceso

### 3. `scan_new_opportunities()` - ACTUALIZADO
**Ubicación**: `engine/trading_logic.py` línea ~1149

**Cambios**:
- ✅ Slots variables: No hay máximo fijo de 4
- ✅ Calcula capacidad estimada dinámicamente (25% por posición)
- ✅ Detecta sobreexposición y prioriza reequilibrio
- ✅ Llama a `_assign_from_radar_dynamic()` para nuevas oportunidades

**Lógica**:
```python
# Capacidad estimada = real_investment_balance / (real_investment_balance * 0.25)
estimated_capacity = int(real_investment_balance / (real_investment_balance * MAX_POSITION_PCT))
```

### 4. `_assign_from_radar_dynamic()` - NUEVO
**Ubicación**: `engine/trading_logic.py` línea ~1204

Asignación dinámica sin límite de slots fijos:
- Respeta 25% del capital real por posición
- Mínimo 10€ por posición
- Prioriza reequilibrio de activos sobreexpuestos
- Usa `_select_best_origin_asset_improved()` para selección de origen

### 5. `_select_best_origin_asset_improved()` - NUEVO
**Ubicación**: `engine/trading_logic.py` línea ~1277

**Orden de prioridad**:
1. **FIAT (EUR/USDC)** si hay saldo > 10€
2. **Activo sobreexpuesto (>25%)** con menor Heat Score
3. **Activo con menor Heat Score** (eslabón más débil)

**Retorna**: `(origin_asset, pair, origin_heat_score, is_overexposed)`

### 6. `execute_buy_dynamic()` - NUEVO
**Ubicación**: `engine/trading_logic.py` línea ~1367

Ejecución de compra con tamaño dinámico:
- Busca slot disponible dinámicamente (hasta 100 slots)
- Usa `position_size_eur` (25% del capital real)
- Llama a `execute_buy()` existente

### 7. `execute_swap_dynamic()` - NUEVO
**Ubicación**: `engine/trading_logic.py` línea ~1405

Ejecución de swap con tamaño dinámico:
- Maneja swaps desde activos sobreexpuestos
- Calcula cantidad a vender (exceso + posición nueva)
- Llama a `execute_swap()` existente

### 8. `_scan_fiat_entry_dynamic()` - NUEVO
**Ubicación**: `engine/trading_logic.py` línea ~1440

Escaneo dinámico desde FIAT sin límite de slots:
- Respeta 25% del capital real
- Busca slots disponibles dinámicamente

## 📊 Dashboard - Actualizado

### Sección SLOTS (Resumen General)
**Ubicación**: `dashboard_flask.py` línea ~382

**Muestra**:
- `[Nº Activos Operables] / [Capacidad estimada]`
- Capacidad estimada calculada dinámicamente: `real_investment_balance / (real_investment_balance * 0.25)`

### Tabla SLOTS ACTIVOS
**Ubicación**: `dashboard_flask.py` línea ~427

**Nuevas columnas**:
- **% Portfolio**: Porcentaje del portfolio que ocupa cada activo
- **Sobreexposición**: Activos >25% se resaltan en rojo con ⚠️
- **Precio Equilibrio**: Precio de equilibrio incluyendo comisiones

**Visualización**:
- Activos sobreexpuestos: Fila con fondo rojo oscuro
- Porcentaje >25%: Texto rojo con "(SOBREEXPUESTO)"

## 🔄 Flujo de Ejecución

1. **Inicio de ciclo** (`run_bot_cycle`):
   - Verifica gas (BNB) primero
   - Monitorea trades activos
   - Llama a `scan_new_opportunities()`

2. **Escaneo de oportunidades** (`scan_new_opportunities`):
   - Calcula saldo real de inversión (excluyendo Gas y Hucha)
   - Detecta sobreexposición
   - Calcula capacidad estimada (slots variables)
   - Llama a `_assign_from_radar_dynamic()`

3. **Asignación desde radar** (`_assign_from_radar_dynamic`):
   - Busca oportunidad caliente (Heat Score alto)
   - Selecciona origen mejorado (`_select_best_origin_asset_improved`)
   - Ejecuta compra/swap dinámico

4. **Selección de origen** (`_select_best_origin_asset_improved`):
   - Prioridad 1: FIAT disponible
   - Prioridad 2: Activo sobreexpuesto con menor Heat Score
   - Prioridad 3: Activo con menor Heat Score

## 🛡️ Protecciones Implementadas

### 1. Reserva de Gas (BNB)
- **2.5% - 5%** del valor total reservado
- **Intocable**: No se usa para trading
- Verificado al inicio de cada ciclo

### 2. Exclusión de Hucha
- Activos en `hucha_diversificada.json` excluidos
- **Prohibición**: Nunca vender activos de hucha para trading
- Leído automáticamente en cada cálculo

### 3. Protección contra Polvo
- Si resto < 10€ después de swap, vende 100%
- Implementado en `_calculate_swap_order_size()`

### 4. Control de Sobreexposición
- Detecta activos >25%
- Marca exceso como "capital disponible para swaps"
- Prioriza reequilibrio en nuevas oportunidades

## 📋 Resumen de Cambios

1. ✅ Cálculo de saldo real (excluyendo Gas y Hucha)
2. ✅ Detección de sobreexposición (>25%)
3. ✅ Slots variables (no máximo fijo)
4. ✅ Reequilibrio proactivo
5. ✅ Selección de origen mejorada (FIAT → Sobreexpuesto → Eslabón débil)
6. ✅ Dashboard actualizado con slots dinámicos y sobreexposición
7. ✅ Funciones de ejecución dinámicas implementadas

## 🔍 Verificación

- ✅ Código compila sin errores
- ✅ Todas las funciones implementadas
- ✅ Dashboard muestra información correctamente
- ✅ Lógica de 25% respetada en todos los cálculos
