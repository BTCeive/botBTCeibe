# 📊 Métricas de Compra y Venta - Revisión

## 🟢 CONDICIONES DE COMPRA

### 1. Triple Verde (Confidence: 100%)
**Ubicación**: `_scan_fiat_entry()` línea ~336

**Condiciones requeridas**:
- ✅ RSI < `rsi_compra` (default: 45)
- ✅ EMA200 distancia < `ema200_traditional_threshold` (default: -2.0%) O
- ✅ EMA200 distancia > `ema200_buy_dip_threshold` (default: 0.0%) Y RSI < `rsi_compra`
- ✅ Volumen alto (`volume_status == 'high'`)

**Lógica actual**:
```python
triple_green = signal_result.get('triple_green', False)
buy_the_dip = False
if ema200_distance is not None and rsi is not None:
    ema_threshold = self.strategy["indicators"].get("ema200_buy_dip_threshold", 0.0)
    buy_the_dip = ema200_distance > ema_threshold and rsi < self.strategy["indicators"]["rsi_compra"]

if triple_green or buy_the_dip:
    # Ejecutar compra
```

**✅ CORREGIDO**: 
- Ahora se verifica explícitamente Triple Verde con las 3 condiciones:
  - RSI < `rsi_compra` (45)
  - EMA200 < `ema200_traditional_threshold` (-2.0%) O (EMA200 > `ema200_buy_dip_threshold` (0.0%) Y RSI < `rsi_compra`)
  - Volumen alto
- Se usa `triple_green` del signal_result si está disponible, sino se calcula localmente

### 2. Buy the Dip (Confidence: 75%)
**Condiciones requeridas**:
- ✅ RSI < `rsi_compra` (default: 45)
- ✅ EMA200 distancia > `ema200_buy_dip_threshold` (default: 0.0%)
- ⚠️ No se verifica volumen explícitamente

**Lógica actual**: ✅ CORRECTA

## 🔴 CONDICIONES DE VENTA

### 1. Safe Exit
**Ubicación**: `_check_trailing_stop()` línea ~400

**Condiciones**:
- ✅ Profit >= `safe_exit_threshold` (default: 1.5%)
- ✅ Profit < `safe_exit_stop_loss` (default: 0.5%)

**Lógica actual**:
```python
if profit_percent >= safe_exit_threshold:  # >= 1.5%
    if profit_percent < safe_exit_stop_loss:  # < 0.5%
        # VENDER
```

**✅ CORREGIDO**: 
- La lógica ahora es correcta:
  - Si el profit máximo (desde `highest_price`) alcanzó >= `safe_exit_threshold` (1.5%)
  - Y el profit actual cayó por debajo de `safe_exit_stop_loss` (0.5%)
  - Entonces se vende para proteger ganancias
- Esto protege las ganancias: si alguna vez llegaste a +1.5%, no perderás más de lo que te permite el stop loss en +0.5%

### 2. Trailing Stop
**Condiciones**:
- ✅ Profit >= `trailing_activation` (default: 3.0%)
- ✅ Caída desde máximo >= `trailing_drop` (default: 0.5%)

**Lógica actual**: ✅ CORRECTA

### 3. Salto (Jump)
**Condiciones**:
- ✅ Heat score destino >= Heat score actual + `jump_heat_score_difference` (default: 15)
- ✅ Profit potencial > Profit actual + `min_profit_step` (default: 2.5%)

**Lógica actual**: ✅ CORRECTA

## 📈 CÁLCULO DE HEAT SCORE

**Ubicación**: `_calculate_heat_score()` línea ~450

**Puntos base**:
- RSI < `rsi_radar_threshold` (default: 48): +33 puntos
- EMA200 < `ema200_traditional_threshold` (-2.0%): +33 puntos
- EMA200 > `ema200_buy_dip_threshold` (0.0%) Y RSI < `rsi_compra`: +33 puntos
- Volumen alto: +33 puntos

**Bonificaciones**:
- Triple Verde: +10 puntos
- 2 condiciones cumplidas: +5 puntos
- RSI < 50: +5 puntos
- EMA200 < 0: +5 puntos

**Máximo**: 100 puntos

## ✅ CORRECCIONES APLICADAS

1. **Safe Exit**: ✅ CORREGIDO - Ahora verifica si el profit máximo alcanzó el threshold y luego cayó
2. **Triple Verde**: ✅ CORREGIDO - Ahora se verifica explícitamente con las 3 condiciones (RSI, EMA, Volumen)
3. **Buy the Dip**: ⚠️ MANTIENE LÓGICA ORIGINAL - No requiere volumen alto (es intencional, compra "dips" en tendencia alcista)

## 📋 RESUMEN DE MÉTRICAS

### Compra
- **Triple Verde**: RSI < 45, EMA < -2% O (EMA > 0% Y RSI < 45), Volumen alto → Confidence 100%
- **Buy the Dip**: RSI < 45, EMA > 0% → Confidence 75%

### Venta
- **Safe Exit**: Profit máximo >= 1.5% Y profit actual < 0.5%
- **Trailing Stop**: Profit >= 3.0% Y caída desde máximo >= 0.5%
- **Salto**: Heat score destino >= actual + 15 Y profit potencial > actual + 2.5%

