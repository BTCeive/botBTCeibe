# 📋 Tipos de Eventos del Historial (Bitácora)

Este documento lista todos los tipos de eventos que se registran en `bitacora.txt` y que aparecen en el Dashboard en la sección "HISTORIAL DE EVENTOS".

---

## 🔄 SWAPS Y OPERACIONES DE TRADING

### `[SWAP_DIVERSIFICACIÓN]`
**Descripción:** Swaps dinámicos fraccionados para diversificar capital.
**Formato:**
```
[SWAP_DIVERSIFICACIÓN] {origin_asset} → {target_asset}: {swap_value_eur:.2f}€ (25% del capital, remanente: {remaining_value_eur:.2f}€ en {origin_asset})
```
**Ejemplo:**
```
[SWAP_DIVERSIFICACIÓN] XRP → ETH: 21.50€ (25% del capital, remanente: 65.30€ en XRP)
```

### `[SWAP_CENTINELA]`
**Descripción:** Rotación de capital estancado cuando hay oportunidad hirviente (Heat Score > 95).
**Formato:**
```
[SWAP_CENTINELA] {weakest_asset} (Heat: {weakest_heat_score}) → {hot_currency} (Heat: {hot_heat_score}, Diff: +{heat_score_diff}): {position_size_eur:.2f}€ rotados
```
**Ejemplo:**
```
[SWAP_CENTINELA] XRP (Heat: 40) → ETH (Heat: 95, Diff: +55): 25.00€ rotados
```

### `Compra: #Slot {slot_id} | COMPRA: {target_asset}`
**Descripción:** Registro de compra de un activo en un slot específico.
**Formato:**
```
Compra: #Slot {slot_id} | COMPRA: {target_asset} - RSI ({rsi}) | Dist. EMA ({ema200_distance}%) | Vol ({volume_status})
```
**Ejemplo:**
```
Compra: #Slot 0 | COMPRA: ETH - RSI (45.2) | Dist. EMA (-2.5%) | Vol (Alto)
```

### `Venta: #Slot {slot_id} | VENTA: {target_asset}`
**Descripción:** Registro de venta de un activo desde un slot específico.
**Formato:**
```
Venta: #Slot {slot_id} | VENTA: {target_asset} (Ruta: {route_info}){hucha_info_msg} - Resultado: {profit_percent:+.2f}%
```
**Ejemplo:**
```
Venta: #Slot 0 | VENTA: XRP (Ruta: XRP/ETH (directo a ETH)) (Hucha: 0.50000000 XRP guardado) - Resultado: +15.30%
```

### `Radar → Slot {slot_id + 1}: {currency} asignada`
**Descripción:** Asignación de un activo desde el Radar a un slot.
**Formato:**
```
Radar → Slot {slot_id + 1}: {currency} asignada (heat_score: {heat_score})
```
**Ejemplo:**
```
Radar → Slot 1: ETH asignada (heat_score: 85)
```

---

## ⛽ GESTIÓN DE GAS (BNB)

### `⛽ Gas: Retenidos {bnb_to_retain} BNB`
**Descripción:** Retención pasiva de BNB para mantener nivel de gas.
**Formato:**
```
⛽ Gas: Retenidos {bnb_to_retain:.4f} BNB ({bnb_value_eur:.2f}€) para mantener gas al {target_percent}%
```
**Ejemplo:**
```
⛽ Gas: Retenidos 0.0125 BNB (5.25€) para mantener gas al 5.0%
```

### `[RECARGA_GAS] Emergencia`
**Descripción:** Recarga de gas en modo emergencia (< 1%).
**Formato:**
```
[RECARGA_GAS] Emergencia: Gas recargado desde {current_gas_percent:.2f}% hasta {new_gas_percent:.2f}%
```
**Ejemplo:**
```
[RECARGA_GAS] Emergencia: Gas recargado desde 0.50% hasta 3.20%
```

### `[RECARGA_GAS] Estratégico`
**Descripción:** Recarga de gas en modo estratégico (< 2%).
**Formato:**
```
[RECARGA_GAS] Estratégico: Gas recargado desde {current_gas_percent:.2f}% hasta {new_gas_percent:.2f}%
```
**Ejemplo:**
```
[RECARGA_GAS] Estratégico: Gas recargado desde 1.80% hasta 5.00%
```

### `⛽ Gas EMERGENCIA: Comprado BNB usando {best_asset}`
**Descripción:** Compra de BNB en modo emergencia usando un activo específico.
**Formato:**
```
⛽ Gas EMERGENCIA: Comprado BNB usando {best_asset} ({amount_to_sell:.8f}) para restaurar gas al {target_percent}%
```
**Ejemplo:**
```
⛽ Gas EMERGENCIA: Comprado BNB usando XRP (10.50000000) para restaurar gas al 2.5%
```

### `⛽ Gas ESTRATÉGICO: Comprado BNB usando {best_currency}`
**Descripción:** Compra de BNB en modo estratégico usando un activo específico.
**Formato:**
```
⛽ Gas ESTRATÉGICO: Comprado BNB usando {best_currency} ({amount_to_sell:.8f}) para alcanzar {target_percent}%
```
**Ejemplo:**
```
⛽ Gas ESTRATÉGICO: Comprado BNB usando XRP (5.25000000) para alcanzar 5.0%
```

### `⛽ Gas: Comprado {needed_bnb_value}€ en BNB`
**Descripción:** Compra de BNB para restablecer fondo de comisiones.
**Formato:**
```
⛽ Gas: Comprado {needed_bnb_value:.2f}€ en BNB. El fondo para comisiones se ha restablecido a {new_bnb_percent:.2f}%.
```
**Ejemplo:**
```
⛽ Gas: Comprado 10.50€ en BNB. El fondo para comisiones se ha restablecido a 5.00%.
```

---

## 💰 HUCHA Y AHORROS

### `[HUCHA_SAVE] {target_asset}: {hucha_value_eur}€ guardados`
**Descripción:** Guardado de hucha selectiva desde swap fraccionado.
**Formato:**
```
[HUCHA_SAVE] {target_asset}: {hucha_value_eur:.2f}€ guardados (5% de beneficio de porción extraída: {portion_profit_eur:.2f}€)
```
**Ejemplo:**
```
[HUCHA_SAVE] BTC: 2.50€ guardados (5% de beneficio de porción extraída: 50.00€)
```

### `💎 Hucha diversificada: Guardados {hucha_amount} {target_asset}`
**Descripción:** Guardado de hucha diversificada desde venta con profit.
**Formato:**
```
💎 Hucha diversificada: Guardados {hucha_amount:.8f} {target_asset} ({hucha_value_eur:.2f}€) desde venta con profit {profit_percent:.2f}%
```
**Ejemplo:**
```
💎 Hucha diversificada: Guardados 0.00125000 BTC (50.00€) desde venta con profit 15.30%
```

### `💰 Hucha: {hucha_eur_amount}€ EUR + {hucha_btc_amount} BTC guardados`
**Descripción:** Guardado de hucha oportunista (EUR + BTC) desde venta.
**Formato:**
```
💰 Hucha: {hucha_eur_amount:.2f}€ EUR + {hucha_btc_amount:.8f} BTC ({hucha_btc_amount_eur:.2f}€) guardados desde venta de {target_asset}
```
**Ejemplo:**
```
💰 Hucha: 25.00€ EUR + 0.00062500 BTC (25.00€) guardados desde venta de XRP
```

### `💰 Hucha: {hucha_btc_amount} BTC guardados desde swap hacia BTC`
**Descripción:** Guardado de hucha oportunista desde swap hacia BTC.
**Formato:**
```
💰 Hucha: {hucha_btc_amount:.8f} BTC ({hucha_btc_value_eur:.2f}€) guardados desde swap hacia BTC
```
**Ejemplo:**
```
💰 Hucha: 0.00050000 BTC (20.00€) guardados desde swap hacia BTC
```

### `💎 Tesoro: Se han enviado {savings_eur}€ al Tesoro Guardado`
**Descripción:** Envío de ahorros al Tesoro Guardado.
**Formato:**
```
💎 Tesoro: Se han enviado {savings_eur:.2f}€ al Tesoro Guardado.
```
**Ejemplo:**
```
💎 Tesoro: Se han enviado 100.00€ al Tesoro Guardado.
```

---

## 🔄 REBALANCE Y DIVERSIFICACIÓN

### `[REBALANCE] {currency} → {destination}: {excess_value_eur}€ vendidos`
**Descripción:** Reequilibrio automático de activo sobreexpuesto hacia destino.
**Formato:**
```
[REBALANCE] {currency} → {destination}: {excess_value_eur:.2f}€ vendidos (Diversificación automática)
```
**Ejemplo:**
```
[REBALANCE] XRP → ETH: 30.00€ vendidos (Diversificación automática)
```

### `[REBALANCE] {currency} → {destination_asset}: {excess_value_eur}€ vendidos (Heat: {destination_heat_score})`
**Descripción:** Reequilibrio hacia activo con Heat Score específico.
**Formato:**
```
[REBALANCE] {currency} → {destination_asset}: {excess_value_eur:.2f}€ vendidos (Heat: {destination_heat_score})
```
**Ejemplo:**
```
[REBALANCE] XRP → ETH: 30.00€ vendidos (Heat: 85)
```

### `[REBALANCE] {currency} → {fiat}: {filled_value_eur}€ vendidos para reequilibrio`
**Descripción:** Reequilibrio hacia FIAT (EUR/USDC).
**Formato:**
```
[REBALANCE] {currency} → {fiat}: {filled_value_eur:.2f}€ vendidos para reequilibrio
```
**Ejemplo:**
```
[REBALANCE] XRP → EUR: 30.00€ vendidos para reequilibrio
```

---

## 📊 RESUMEN DE TIPOS DE EVENTOS

| Tipo de Evento | Prefijo/Etiqueta | Categoría |
|----------------|-----------------|-----------|
| Swap Diversificación | `[SWAP_DIVERSIFICACIÓN]` | Trading |
| Swap Centinela | `[SWAP_CENTINELA]` | Trading |
| Compra | `Compra: #Slot` | Trading |
| Venta | `Venta: #Slot` | Trading |
| Asignación Radar | `Radar → Slot` | Trading |
| Retención Gas | `⛽ Gas: Retenidos` | Gas |
| Recarga Gas Emergencia | `[RECARGA_GAS] Emergencia` | Gas |
| Recarga Gas Estratégico | `[RECARGA_GAS] Estratégico` | Gas |
| Compra Gas Emergencia | `⛽ Gas EMERGENCIA` | Gas |
| Compra Gas Estratégico | `⛽ Gas ESTRATÉGICO` | Gas |
| Compra Gas General | `⛽ Gas: Comprado` | Gas |
| Hucha Save | `[HUCHA_SAVE]` | Hucha |
| Hucha Diversificada | `💎 Hucha diversificada` | Hucha |
| Hucha Oportunista | `💰 Hucha:` | Hucha |
| Tesoro | `💎 Tesoro:` | Hucha |
| Rebalance | `[REBALANCE]` | Rebalance |

---

## 🎨 COLORES EN EL DASHBOARD

El Dashboard aplica colores específicos a cada tipo de evento:

- **`[SWAP_DIVERSIFICACIÓN]`**: Color azul/cyan
- **`[SWAP_CENTINELA]`**: Color naranja/amarillo
- **`[RECARGA_GAS]`**: Color amarillo
- **`[HUCHA_SAVE]`**: Color verde
- **`[REBALANCE]`**: Color morado/violeta
- **`Compra:`**: Color verde claro
- **`Venta:`**: Color rojo/verde (según profit)
- **`⛽ Gas:`**: Color amarillo/naranja
- **`💰 Hucha:`**: Color verde
- **`💎 Tesoro:`**: Color dorado

---

## 📝 NOTAS

1. **Formato de tiempo:** El Dashboard muestra `[X min/sec ago]` calculado desde el timestamp del evento.
2. **Orden:** Los eventos se muestran en orden cronológico inverso (más recientes primero).
3. **Límite:** El Dashboard muestra los últimos N eventos (configurable).
4. **Persistencia:** Todos los eventos se guardan en `bitacora.txt` en el directorio raíz del proyecto.

---

## 🔍 BÚSQUEDA DE EVENTOS

Para buscar eventos específicos en `bitacora.txt`:

```bash
# Buscar todos los swaps de diversificación
grep "SWAP_DIVERSIFICACIÓN" bitacora.txt

# Buscar todas las recargas de gas
grep "RECARGA_GAS" bitacora.txt

# Buscar todas las operaciones de hucha
grep "HUCHA" bitacora.txt

# Buscar todos los rebalances
grep "REBALANCE" bitacora.txt

# Buscar todas las compras
grep "COMPRA" bitacora.txt

# Buscar todas las ventas
grep "VENTA" bitacora.txt
```

