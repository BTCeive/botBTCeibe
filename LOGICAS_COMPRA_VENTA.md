# 📖 LÓGICAS DE COMPRA/VENTA DE ACTIVOS - botCeibe

## 🎯 RESUMEN EJECUTIVO

El bot opera con un sistema de **gestión dinámica de capital** donde:
- Cada posición representa aproximadamente el **25% del capital real de inversión**
- El capital real excluye: **Gas BNB (2.5-5%)** y **Hucha diversificada (reserva)**
- Mínimo por operación: **10€** (requisito de Binance)
- Slots variables: No hay máximo fijo, se adapta al capital disponible

---

## 1. 🔵 LÓGICA DE COMPRA (`execute_buy`)

### 1.1. Flujo General

```
1. Verificar balance disponible (base_asset)
2. Calcular capital por slot (25% del capital real)
3. Validar mínimo de Binance (10€)
4. Ejecutar orden de compra (market order)
5. Registrar trade en base de datos
6. Actualizar estado compartido
```

### 1.2. Cálculo de Capital por Slot

```python
# Capital real = Total - Gas - Hucha
total_portfolio_eur = calculate_total_portfolio_value()
gas_reserve_eur = total_portfolio_eur * 0.05  # 5% para gas
available_for_trading = total_portfolio_eur - gas_reserve_eur

# Capital por slot (25% del disponible)
monto_por_slot_eur = available_for_trading * 0.25
```

### 1.3. Validaciones Previas

- ✅ **Balance suficiente**: `base_balance > 0`
- ✅ **Mínimo Binance**: `order_value_eur >= 10.0€`
- ✅ **Exclusión de Hucha**: Si `base_asset` es EUR/USDC, excluir `treasury_eur`
- ✅ **Reserva de Gas**: Si `target_asset` es BNB, reservar 5% para gas

### 1.4. Ejecución

```python
# Obtener precio de mercado
ticker = exchange.fetch_ticker(pair)
price = ticker['last']

# Calcular cantidad a comprar
amount = capital_to_use / price
amount = exchange.amount_to_precision(pair, amount)

# Ejecutar orden
order = exchange.create_market_buy_order(pair, amount)

# Registrar en DB
trade_id = db.create_trade(
    slot_id=slot_id,
    symbol=pair,
    base_asset=base_asset,
    target_asset=target_asset,
    amount=executed_amount,
    entry_price=executed_price,
    initial_fiat_value=initial_fiat_value
)
```

### 1.5. Casos Especiales

**Compra desde FIAT (EUR/USDC):**
- `is_fiat_entry = True`
- `initial_fiat_value` = valor en EUR de la compra
- Se registra en bitácora con indicadores técnicos (RSI, EMA, Volumen)

**Compra desde otro activo (Swap):**
- `is_fiat_entry = False`
- `initial_fiat_value = 0` (no hay entrada desde FIAT)
- Se calcula desde el valor del activo origen

---

## 2. 🔴 LÓGICA DE VENTA (`execute_sell`)

### 2.1. Flujo General

```
1. Buscar mejor destino en Radar (oportunidad caliente)
2. Si no hay destino en Radar → Fallback a EUR
3. Calcular Hucha (5% si profit > 1% y destino en RESERVE_ASSETS)
4. Ejecutar venta/swap (puede ser ruta directa o intermedia)
5. Guardar Hucha si aplica
6. Cerrar trade en base de datos
7. Registrar en bitácora
```

### 2.2. Selección de Destino

**Prioridad 1: Radar de Oportunidades**
```python
destination_result = await _find_best_destination_from_radar(
    exclude_assets=[target_asset]
)
if destination_result:
    destination_asset, heat_score = destination_result
    # Usar swap directo al destino del radar
```

**Prioridad 2: Fallback a EUR**
```python
if not destination_result:
    destination_asset = 'EUR'
    # Venta tradicional a FIAT
```

### 2.3. Cálculo de Hucha Selectiva

**Condiciones para guardar Hucha:**
- ✅ `profit_percent > 1.0%`
- ✅ `destination_asset` está en `RESERVE_ASSETS` = ['EUR', 'USDC', 'BTC', 'ETH', 'SOL', 'DOT']
- ✅ El 95% restante cubre el capital inicial

```python
if estimated_profit_percent > 1.0 and target_asset_for_hucha in RESERVE_ASSETS:
    hucha_amount = amount * 0.05  # 5% del total
    amount_to_sell = amount * 0.95  # 95% para vender
```

**Si no se cumple:**
- Transferencia 100% (maximizar interés compuesto)
- No se guarda Hucha

### 2.4. Rutas de Venta

**Ruta Directa:**
```
target_asset → destination_asset
Ejemplo: XRP → BTC (par XRP/BTC)
```

**Ruta Intermedia (2 pasos):**
```
target_asset → intermediate → destination_asset
Ejemplo: XRP → EUR → BTC
```

### 2.5. Ejecución

```python
# Ejecutar primer swap
order1 = exchange.create_market_sell_order(best_pair, amount_to_sell)

# Si hay ruta intermedia, ejecutar segundo swap
if intermediate:
    order2 = exchange.create_market_sell_order(intermediate_pair, intermediate_amount)

# Calcular profit real
profit_eur = final_value_eur - initial_fiat_value
profit_percent = (profit_eur / initial_fiat_value * 100)

# Guardar Hucha si aplica
if hucha_amount > 0:
    _save_hucha_diversificada(target_asset, hucha_amount, profit_eur)

# Cerrar trade
db.deactivate_trade(trade_id)
```

---

## 3. 🔄 LÓGICA DE SWAP (`execute_swap`)

### 3.1. Propósito

Intercambiar un activo por otro **sin pasar por FIAT**, optimizando comisiones.

### 3.2. Flujo

```
1. Obtener balance total del activo actual
2. Buscar mejor destino en Radar
3. Encontrar ruta óptima (directa o intermedia)
4. Ejecutar swap
5. Actualizar trade con nuevo activo
```

### 3.3. Actualización de Precios

**Crítico:** Después de un swap, se actualizan:
- `entry_price` = precio de mercado del nuevo activo
- `highest_price` = precio de mercado del nuevo activo
- `target_asset` = nuevo activo
- `symbol` = nuevo par

Esto permite que el **Trailing Stop** funcione correctamente desde el nuevo activo.

---

## 4. 📊 SEGUIMIENTO DE PRECIOS Y PNL

### 4.1. Actualización en Tiempo Real

**Función:** `_evaluate_slot_optimized()` (ejecutada cada 5 segundos)

```python
# Obtener valor actual
trade_value_eur = vault.get_asset_value(target_asset, amount, 'EUR')

# Calcular PNL
pnl_percent = ((trade_value_eur - initial_fiat_value) / initial_fiat_value) * 100

# Obtener precio actual
current_price = trade_value_eur / amount if amount > 0 else 0

# Actualizar highest_price si subió
if current_price > highest_price:
    db.update_highest_price(trade_id, current_price)
```

### 4.2. Estados de Protección

**Zona de Rotación (-0.5% a -1.5%):**
- Busca oportunidad mejor en Radar (heat_score > 90)
- Si encuentra, ejecuta swap automático

**Hard Stop Loss (< -1.5%):**
- Venta inmediata sin preguntas
- Protección de capital

**Trailing Stop (> 0.6%):**
- Stop loss dinámico que sube con el precio
- Escalonado: 0.6%, 1.0%, 2.0%, 3.0%, 4.0%, 5.0%
- Principio de trinquete: solo sube, nunca baja

---

## 5. 🎯 RE-EQUILIBRIO AUTOMÁTICO

### 5.1. Detección de Sobreexposición

**Función:** `_detect_overexposure()`

```python
# Calcular % de cada activo sobre el total
for asset in operable_assets:
    asset_value_eur = vault.get_asset_value(asset, balance, 'EUR')
    asset_percent = (asset_value_eur / real_investment_balance) * 100
    
    if asset_percent > 25.0:
        excess_value_eur = asset_value_eur - (real_investment_balance * 0.25)
        overexposed.append({
            'currency': asset,
            'current_percent': asset_percent,
            'excess_value_eur': excess_value_eur
        })
```

### 5.2. Corrección Automática

**Función:** `_rebalance_overexposed_asset()`

**Estrategia:**
1. **Prioridad 1:** Convertir exceso a oportunidad caliente del Radar
2. **Prioridad 2:** Vender exceso a FIAT (EUR)

**Ejecución:**
```python
# Calcular cantidad a vender (exceso)
excess_percent = (excess_value_eur / current_value_eur)
excess_amount = total_balance * excess_percent

# Buscar destino en Radar
destination_result = await _find_best_destination_from_radar(
    exclude_assets=[currency]
)

# Ejecutar swap o venta
if destination_result:
    # Swap a destino del Radar
    order = exchange.create_market_sell_order(best_pair, excess_amount)
else:
    # Venta a FIAT
    order = exchange.create_market_sell_order(f"{currency}/EUR", excess_amount)
```

---

## 6. 📈 GESTIÓN DINÁMICA DE CAPITAL

### 6.1. Cálculo de Capital Real

```python
def _calculate_real_investment_balance():
    # Total del portfolio
    total_portfolio_eur = vault.calculate_total_portfolio_value()
    
    # Excluir Gas BNB (2.5-5%)
    gas_bnb_eur = vault.get_asset_value('BNB', bnb_balance, 'EUR')
    gas_reserve_eur = total_portfolio_eur * 0.025  # 2.5% mínimo
    
    # Excluir Hucha diversificada
    hucha_data = load_hucha_diversificada()
    hucha_total_eur = sum(item['value_eur'] for item in hucha_data)
    
    # Capital real de inversión
    real_investment_balance_eur = (
        total_portfolio_eur 
        - max(gas_bnb_eur, gas_reserve_eur) 
        - hucha_total_eur
    )
    
    return {
        'real_investment_balance_eur': real_investment_balance_eur,
        'gas_reserve_eur': gas_reserve_eur,
        'hucha_total_eur': hucha_total_eur
    }
```

### 6.2. Capacidad de Slots

```python
MAX_POSITION_PCT = 0.25  # 25% por posición
MIN_SLOT_VALUE_EUR = 10.0  # Mínimo de Binance

position_size = real_investment_balance * MAX_POSITION_PCT
if position_size >= MIN_SLOT_VALUE_EUR:
    estimated_capacity = int(real_investment_balance / position_size)
else:
    estimated_capacity = 0
```

---

## 7. 🔍 SELECCIÓN DE ORIGEN (Para Nuevas Entradas)

### 7.1. Prioridad de Origen

**Función:** `_select_best_origin_asset_improved()`

**Orden de prioridad:**
1. **FIAT disponible** (>10€): EUR o USDC
2. **Activo sobreexpuesto** (>25%) con menor Heat Score
3. **Activo con menor Heat Score** (de todos los operables)

### 7.2. Ejemplo

```
Capital disponible: 100€
- XRP: 91€ (91%, Heat: 50) ← SOBREEXPUESTO
- EUR: 9€ (9%, Heat: N/A)

Nueva oportunidad: BTC (Heat: 85)

Origen seleccionado: XRP (sobreexpuesto + menor Heat)
Cantidad a vender: 66€ (para dejar XRP en 25% = 25€)
```

---

## 8. 📝 REGISTRO Y BITÁCORA

### 8.1. Eventos Registrados

- `[SWAP]`: Intercambio entre activos
- `[GAS_REFILL]`: Recarga de BNB para gas
- `[HUCHA_SAVE]`: Guardado de Hucha diversificada
- `[PROTECTION_UPDATE]`: Actualización de stop loss
- `[REBALANCE]`: Reequilibrio automático

### 8.2. Formato

```
[REBALANCE] XRP → BTC: 64.91€ vendidos (Heat: 85)
[SWAP] Origen: XRP (Heat: 50) → Destino: BTC (Heat: 85) | Motivo: Optimización de Inventario
```

---

## 9. ⚠️ CASOS ESPECIALES

### 9.1. Dust Cleaning

Si tras una venta/swap el remanente es < 10€:
- Forzar venta del 100% de la posición
- Evitar saldos inoperables

### 9.2. Validación de Mínimos

**Antes de comprar:**
- Verificar que `order_value_eur >= 10.0€`

**Antes de vender:**
- Verificar que `amount_to_sell >= min_amount` (límite de Binance)

**Si no se cumple:**
- Operación rechazada
- Trade desactivado si no se puede vender

### 9.3. Actualización de Precios

**Problema detectado:** El dashboard no actualiza precios en tiempo real.

**Solución implementada:**
- Dashboard obtiene precios desde `Vault` (más preciso)
- Fallback a `state.json` si Vault no está disponible
- Cálculo directo: `current_price = vault.get_asset_value(asset, 1.0, base_asset)`

---

## 10. 🎯 RESUMEN DE FLUJOS

### Compra Nueva
```
Radar detecta oportunidad → Seleccionar origen → Calcular 25% → Validar 10€ → Comprar → Registrar
```

### Venta con Profit
```
PNL > 1% → Buscar destino Radar → Calcular Hucha (5%) → Vender 95% → Guardar Hucha → Cerrar trade
```

### Swap/Rotación
```
PNL -0.5% a -1.5% → Buscar mejor oportunidad → Swap directo → Actualizar entry_price
```

### Reequilibrio
```
Sobreexposición > 25% → Calcular exceso → Vender exceso → Redistribuir
```

---

**Última actualización:** 2025-12-25
**Versión del bot:** botCeibe v2.0 (Gestión Dinámica de Capital)

