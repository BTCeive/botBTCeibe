# ⚠️ Parámetros Críticos - Guía de Configuración

## 🔴 PARÁMETROS QUE DEBES VIGILAR

### 1. `jump_heat_score_difference` (Umbral de Salto)

**Ubicación**: `config/strategy.json` → `trading.jump_heat_score_difference`

**Valor por defecto**: `15`

**¿Qué hace?**
- Controla cuánto mejor debe ser el "Heat Score" de una moneda para que el bot salte desde la actual
- Si una moneda tiene Heat Score 50 y otra tiene 65, con umbral 15, el bot saltará
- Si el umbral fuera 20, necesitaría que la otra tenga al menos 70

**Riesgo de Overtrading**:
- ⚠️ **Valor bajo (10-15)**: El bot saltará frecuentemente entre monedas
  - Genera muchas comisiones (cada salto = 2 operaciones: venta + compra)
  - Puede perder dinero en comisiones aunque las señales sean buenas
  - Ejemplo: 10 saltos/día × 0.1% comisión × 2 operaciones = 2% en comisiones
  
- ✅ **Valor medio (20-25)**: Balance entre agilidad y estabilidad
  - Salta solo cuando hay una mejora significativa
  - Reduce comisiones pero mantiene flexibilidad
  
- ✅ **Valor alto (30-40)**: Muy conservador
  - Solo salta en casos excepcionales
  - Minimiza comisiones pero puede perder oportunidades

**Recomendaciones**:
- **Empezar con**: 15-20 (para aprender el comportamiento)
- **Si ves muchos saltos**: Aumentar a 25-30
- **Si ves pocos saltos pero pierdes oportunidades**: Reducir a 12-15 (con cuidado)

**Cómo detectar overtrading**:
1. Revisa los logs: busca mensajes `🔄 [Slot X] Asset1 ➔ Asset2`
2. Cuenta los saltos en 24 horas
3. Si hay más de 5-10 saltos por slot en 24h, considera aumentar el umbral
4. Calcula comisiones: cada salto = ~0.1-0.2% en comisiones (depende del exchange)

**Ejemplo de configuración**:
```json
{
  "trading": {
    "jump_heat_score_difference": 25  // Más conservador, menos saltos
  }
}
```

## 📊 Otros Parámetros Importantes

### 2. `min_profit_step` (Mínimo Beneficio para Salto)
**Valor**: `2.5%`
**Qué hace**: Además del heat score, el profit potencial debe ser al menos 2.5% mayor que el actual
**Recomendación**: No bajar de 2.0% para evitar saltos por diferencias mínimas

### 3. `trailing_activation` (Activación Trailing Stop)
**Valor**: `3.0%`
**Qué hace**: Solo activa trailing stop si el profit alcanza 3%
**Recomendación**: No bajar de 2.5% para evitar ventas prematuras

### 4. `safe_exit_threshold` (Umbral Safe Exit)
**Valor**: `1.5%`
**Qué hace**: Si el profit alcanza 1.5%, activa stop loss en 0.5%
**Recomendación**: Mantener entre 1.0-2.0% para proteger ganancias pequeñas

## 🔍 Monitoreo Recomendado

### Logs a Revisar
```bash
# Buscar saltos
grep "🔄" botceibe.log | wc -l

# Buscar advertencias de umbral bajo
grep "ADVERTENCIA.*umbral" botceibe.log
```

### Dashboard
- Revisa la sección "Operaciones Abiertas"
- Si ves que los slots cambian frecuentemente de activo, el umbral puede ser muy bajo

## ⚙️ Ajuste Dinámico

**Proceso recomendado**:
1. **Semana 1**: Usar valor por defecto (15)
2. **Observar**: Contar saltos y calcular comisiones
3. **Ajustar**: Si hay overtrading, aumentar a 20-25
4. **Monitorear**: Revisar resultados después de ajuste
5. **Optimizar**: Ajustar según resultados

**Fórmula rápida**:
```
Si saltos/día > 10 por slot → Aumentar umbral en +5
Si saltos/día < 2 por slot → Considerar reducir umbral en -3 (con cuidado)
```

