Normalización post-emergencia

Resumen de cambios realizados para volver al estado normal de operación:

- Implementado y verificado el **Stop universal**: Stop = PNL_max - 0.50% (mostrado en la columna `ESTADO` del dashboard).
- Persistencia de la cronometría de vigilancia: creado `shared/vigilancia_state.json` y funciones de lectura/escritura en `engine/trading_logic.py` y `dashboard/app.py`.
- Añadidas pruebas:
  - `scripts/test_vigilancia_persistence.py` — verifica que `vigilancia_state.json` puede ser escrito y leído.
  - `scripts/test_vigilancia_buffer.py` — simula 3 ciclos idénticos de líder para comprobar que el buffer reinicia el vigilante.
  - `scripts/test_radar_watchdog.py` — prueba básica que añade entradas de reinicio en `bitacora.txt` (simulación del watchdog).
- Radar watchdog: lógica para reiniciar `start_radar_dynamic_updates()` si las tareas del radar están ausentes, con backoff (`RADAR_RESTART_COOLDOWN`).
- Dashboard:
  - Fórmula de **FONDOS** verificada: Fondos = (EUR_disponible + Valor_Actual_Inversiones + Valor_BNB_Gas) - Saldo_Hucha.
  - Umbral de stale radar reducido a 30s y mensaje discreto en UI.
  - El par `XRP/EUR` ya **no** recibe resaltado visual especial.
- Eliminada la excepción/emergency bypass permanente para XRP/EUR tras cierre forzado de la posición.

Siguientes pasos recomendados:

- Añadir tests de integración que arranquen el motor y comprueben que el watchdog efectivamente reinicia las tareas (requiere entorno con dependencias como `ccxt`).
- Ejecutar el dashboard en un entorno con `streamlit` y verificar en UI el valor de FONDOS afficheado (debería mostrar ~59.43€ con los datos actuales).
- Monitorizar `bitacora.txt` para confirmar lecturas de `[RADAR_RESTART]` y entradas de auditoría.

Fecha: 2025-12-26
