# Sistema de Escaneo en Cascada v2.0 - botCeibe

## Resumen Ejecutivo

Se ha implementado un **sistema de escaneo en cascada de 3 niveles** para optimizar el rendimiento del motor y asegurar fluidez en el Dashboard.

## Arquitectura del Sistema

### 1. Clasificación Dinámica por Heat Score

El motor clasifica automáticamente la whitelist en 3 niveles de prioridad según el heat_score almacenado en SQLite.

**Niveles:**
- **HOT (Nivel 1)**: Top 10 activos con mayor heat_score
- **WARM (Nivel 2)**: Posiciones 11-20
- **COLD (Nivel 3)**: Resto de la whitelist

### 2. Frecuencias de Escaneo

| Nivel | Activos | Frecuencia | Intervalo | Timeout |
|-------|---------|------------|-----------|---------|
| HOT   | Top 10  | Cada tick  | ~5s       | 15s     |
| WARM  | Pos 11-20| Cada 3 ticks| ~15s     | 12s     |
| COLD  | Resto   | Cada 10 ticks| ~50s    | 20s     |

### 3. Radar Dinámico Top 20

El Dashboard muestra exactamente 20 filas (10 en cada columna), correspondientes al Top 20 por heat_score.

### 4. Vigilante Enfocado en #1

El Slot Vigilante siempre muestra el líder del ranking con cronómetro estable.

### 5. Riesgo BTC Actualizado

BTC/USDT se actualiza cada tick (Nivel HOT) para mantener el termómetro del sistema preciso.

## Logs de Ejemplo

```
✅ Escáner multi-bases completado: 10 activos actualizados
✅ Radar generado: 19 pares (cache: 14, placeholders: 5)
✅ Vigilancia actualizada: BTC/USDT (heat 20)
✅ Estado compartido guardado: 19 pares en radar
```

## Verificación

### Ver Top 20 Actual
```bash
sqlite3 -readonly shared/bot_data.db "SELECT destination, heat_score FROM market_data ORDER BY heat_score DESC LIMIT 20;"
```

### Ver Riesgo BTC
```bash
cat shared/state.json | jq '.market_status'
```

### Ver Vigilante
```bash
cat shared/vigilancia_state.json | jq '.current_pair, .start_ts'
```

---
**Versión**: Cascade v2.0 (2025-12-29)
