# Gestión Dinámica de Capital - Implementación

## ✅ Funciones Implementadas

### 1. `_calculate_real_investment_balance()`
- Calcula el saldo real de inversión excluyendo:
  - Reserva de Gas (BNB): 2.5% - 5% del valor total (intocable)
  - Hucha diversificada: Activos guardados en hucha_diversificada.json
- Retorna dict con todos los valores calculados

### 2. `_detect_overexposure()`
- Detecta activos que superan el 25% del capital real
- Retorna lista de activos sobreexpuestos con:
  - Valor actual y porcentaje
  - Valor excedente (capital disponible para swaps)
  - Porcentaje de exceso

### 3. `scan_new_opportunities()` - ACTUALIZADO
- Slots variables: No hay máximo fijo de 4
- Calcula capacidad estimada dinámicamente (25% por posición)
- Detecta sobreexposición y prioriza reequilibrio
- Llama a `_assign_from_radar_dynamic()` para nuevas oportunidades

### 4. `_assign_from_radar_dynamic()` - NUEVO
- Asignación dinámica sin límite de slots fijos
- Respeta 25% del capital real por posición
- Mínimo 10€ por posición
- Prioriza reequilibrio de activos sobreexpuestos

### 5. `_select_best_origin_asset_improved()` - NUEVO
- Orden de prioridad:
  1. FIAT (EUR/USDC) si hay saldo > 10€
  2. Activo sobreexpuesto (>25%) con menor Heat Score
  3. Activo con menor Heat Score (eslabón más débil)

## ⚠️ Funciones Pendientes

### 1. `execute_buy_dynamic()`
- Similar a `execute_buy()` pero con tamaño de posición dinámico
- Usa `position_size_eur` en lugar de `monto_por_slot_eur` fijo

### 2. `execute_swap_dynamic()`
- Similar a `execute_swap()` pero con tamaño de posición dinámico
- Maneja swaps desde activos sobreexpuestos

### 3. `_scan_fiat_entry_dynamic()`
- Similar a `_scan_fiat_entry()` pero sin límite de slots
- Respeta 25% del capital real

## 📊 Dashboard - Actualización Pendiente

### Sección SLOTS
- Mostrar: [Nº Activos Operables] / [Capacidad estimada]
- Capacidad estimada = real_investment_balance / (real_investment_balance * 0.25)
- Tabla dinámica que se actualiza en tiempo real

## 🔄 Próximos Pasos

1. Implementar funciones `*_dynamic()` faltantes
2. Actualizar dashboard para mostrar slots dinámicos
3. Probar reequilibrio proactivo
4. Verificar protección contra polvo
