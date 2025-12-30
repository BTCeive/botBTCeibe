# Arquitectura BotCeibe - Motor de 4 Slots

## Contexto

Bot de trading de alta precisión llamado botCeibe. El sistema está desacoplado: el motor (`engine/trading_logic.py`) gestiona la lógica y escribe el estado en `shared/state.json`, mientras que el dashboard (`dashboard/dashboard.html` y `dashboard/dashboard.js`) solo lee dicho estado.

## Objetivo

Implementar la lógica de gestión de slots y ejecución de órdenes en `engine/trading_logic.py` y `main.py` siguiendo estas directrices estrictas.

## 1. Gestión de Capital (Sistema de 4 Slots)

### División
- Divide el capital total disponible en la wallet (según `config/.env`) en exactamente 4 slots independientes.
- **Ubicación actual**: `engine/trading_logic.py` - función `execute_buy()` (líneas ~1020-1060)
- **Configuración**: `config/strategy.json` → `trading.max_slots` (actualmente: 4)

### Asignación
- Cada slot representa el **1/4 del fondo total disponible** (después de reservar 5% para gas BNB).
- **Cálculo actual**: 
  ```python
  # En execute_buy():
  total_portfolio_eur = self.vault.calculate_total_portfolio_value()
  gas_reserve_eur = total_portfolio_eur * 0.05
  available_for_trading = max(0.0, total_portfolio_eur - gas_reserve_eur)
  max_slots = self.strategy["trading"]["max_slots"]
  monto_por_slot_eur = available_for_trading / max_slots if max_slots > 0 else 0.0
  ```
- Un activo solo puede entrar en un slot si este está libre (`is_active = 0` en la base de datos).
- **Verificación de slots libres**: `database.py` → `get_active_trade(slot_id)` retorna `None` si el slot está libre.

### Moneda Base
- El objetivo final de cada operación es liquidar el activo para maximizar el beneficio y terminar siempre en **EUR**.
- **Implementación actual**: En `execute_sell()` y `execute_swap()`, las operaciones se liquidan a EUR.

## 2. Lógica de Entrada (Compra)

Un activo ocupa un slot solo cuando se cumplan simultáneamente estas condiciones:

### RSI
- **Configurable en**: `config/strategy.json` → `indicators.rsi_compra` (actualmente: 45)
- **Ubicación**: `engine/trading_logic.py` → función `_evaluate_signal()` (líneas ~945-990)
- Condición: RSI < `rsi_compra`

### EMA
- **Configuración**: `config/strategy.json` → `indicators.ema200_period` (200), `ema200_traditional_threshold` (-2.0), `ema200_buy_dip_threshold` (0.0)
- **Ubicación**: `engine/trading_logic.py` → función `_evaluate_signal()`
- El precio debe estar en una posición específica respecto a las medias móviles EMA200.

### Volumen
- **Configuración**: `config/strategy.json` → `indicators.volume_threshold` (1.5)
- **Ubicación**: `engine/trading_logic.py` → función `_evaluate_signal()`
- Confirmación de incremento de volumen relativo.

### Filtro Whitelist
- **Ubicación**: `config/strategy.json` → `whitelist` (array de monedas permitidas)
- **Archivo de referencia**: `WHITELIST_PARES.md`
- Solo operar con monedas de la whitelist.
- **Verificación**: `engine/trading_logic.py` → función `_scan_fiat_entry()` verifica que el activo esté en la whitelist.

### Función Principal de Escaneo
- **Ubicación**: `engine/trading_logic.py` → función `_scan_fiat_entry()` (líneas ~530-680)
- Escanea oportunidades de compra cuando un slot está libre.

## 3. Lógica de Salida y Gestión de Beneficios (Trailing Stop Loss)

Una vez el activo ocupa el slot, el bot queda a la espera vigilando la venta con esta lógica:

### Take Profit Dinámico
- **Configuración**: `config/strategy.json` → `trading.trailing_activation` (3.0%)
- **Ubicación**: `engine/trading_logic.py` → función `_check_trailing_stop()` (líneas ~690-790)
- Si el beneficio llega a `trailing_activation`%, activar modo "Seguimiento".

### Maximización (Trailing Stop)
- **Configuración**: `config/strategy.json` → `trading.trailing_drop` (0.5%)
- Si el precio sigue subiendo, el Stop Loss sube dinámicamente (Trailing Stop) para capturar la tendencia máxima.
- Se actualiza `highest_price` en la base de datos cuando el precio sube.

### Venta
- Vender inmediatamente si:
  - El precio cae un `trailing_drop`% desde su punto máximo alcanzado (protegiendo ganancias)
  - O si toca el Stop Loss inicial (evitar pérdidas mayores)
- **Configuración Stop Loss**: `config/strategy.json` → `risk.stop_loss` (5.0%)
- **Ubicación de venta**: `engine/trading_logic.py` → función `execute_sell()` (líneas ~1170-1300)

### Safe Exit
- **Configuración**: `config/strategy.json` → `trading.safe_exit_threshold` (1.5%), `safe_exit_stop_loss` (0.5%)
- Si el profit alcanza >= `safe_exit_threshold`%, activar stop loss virtual en +`safe_exit_stop_loss`%.
- Si luego cae por debajo de `safe_exit_stop_loss`%, vender para proteger ganancias.

## 4. Gestión de Wallet y Comisiones

### Búsqueda de Pares
- **Ubicación**: `router.py` → función `find_swap_route()`
- El bot busca la ruta más eficiente para vender (ej. ALT/BTC → BTC/EUR o ALT/EUR) para maximizar el retorno final en Euro.
- Se usa para optimizar las rutas de swap en `execute_swap()`.

### La Hucha (Treasury)
- **Configuración**: `config/strategy.json` → `hucha.enabled` (true), `hucha.hucha_eur_pct` (2.5%), `hucha.hucha_btc_pct` (2.5%)
- De cada operación exitosa, separar un % configurable como beneficio neto ("La Hucha").
- Guardar este beneficio en EUR o BTC según la tendencia del mercado para optimizar el valor y evitar comisiones innecesarias.
- **Ubicación**: `engine/trading_logic.py` → función `execute_sell()` calcula y guarda la hucha.
- **Almacenamiento**: `database.py` → tabla `treasury`, función `add_to_treasury()`.

### Recarga BNB (Gas)
- **Configuración**: `config/strategy.json` → `gas_management.max_target` (5.0%), `gas_management.low_warning` (2.5%), `gas_management.critical` (1.0%)
- Monitorizar el saldo de BNB para comisiones.
- Si baja de un umbral, usar una pequeña parte de un slot libre para comprar BNB automáticamente.
- **Ubicación**: `engine/trading_logic.py` → función `_manage_gas()` (si existe) o lógica en `scan_opportunities()`.
- **Estado actual**: El bot reserva 5% del portfolio para gas BNB en `execute_buy()`.

## 5. Output de Datos

### Estado Compartido (shared/state.json)
- **Ubicación de escritura**: `engine/trading_logic.py` → función `_save_shared_state()` (líneas ~1738-1950)
- **Ubicación de lectura**: `dashboard/dashboard.js` → función `loadState()`
- Actualizar `shared/state.json` en cada iteración con el estado de los 4 slots.
- **Estructura actual**:
  ```json
  {
    "open_trades": [
      {
        "slot_id": 0,
        "trade_id": 8,
        "pair": "XRP/EUR",
        "base_asset": "EUR",
        "target_asset": "XRP",
        "amount": 14.083749999999998,
        "entry_price": 1.5936000000000001,
        "initial_fiat_value": 22.443863999999998,
        "current_value_eur": 22.45,  // Calculado en _save_shared_state()
        "created_at": "2025-12-23 13:51:55"
      }
    ],
    "market_status": {...},
    "balances": {...},
    "prices": {...},
    "treasury": {...},
    "gas_bnb": {...}
  }
  ```

### Base de Datos (multibot.db)
- **Ubicación**: Raíz del proyecto (`multibot.db`)
- **Gestión**: `database.py` → clase `Database`
- Tablas principales:
  - `trades`: Almacena todos los trades activos e históricos
  - `treasury`: Almacena la hucha (EUR y BTC)
  - `portfolio_snapshots`: Snapshots del valor del portfolio a lo largo del tiempo

## 6. Estructura de Archivos Relevante

```
botCeibe/
├── config/
│   ├── strategy.json          # Configuración principal (RSI, EMA, slots, trailing stops, etc.)
│   └── .env                   # Credenciales Binance (BINANCE_API_KEY, BINANCE_SECRET_KEY)
├── engine/
│   └── trading_logic.py       # Motor principal de trading (lógica de slots, compra, venta)
├── shared/
│   └── state.json             # Estado compartido (escrito por el motor, leído por el dashboard)
├── dashboard/
│   ├── dashboard.html         # Dashboard HTML estático
│   ├── dashboard.js           # Lógica JavaScript del dashboard
│   └── dashboard.css          # Estilos del dashboard
├── database.py                # Gestión de base de datos SQLite
├── vault.py                   # Cálculo de valores de activos y conversiones
├── router.py                  # Búsqueda de rutas de trading y pares disponibles
├── main.py                    # Punto de entrada del bot (bucle principal)
├── signals.py                 # Módulo de señales técnicas (si existe)
└── multibot.db                # Base de datos SQLite
```

## 7. Entorno Virtual y Dependencias

- **Ubicación del venv**: `./venv` (o `venv/` en la raíz del proyecto)
- **Activar entorno**: `source venv/bin/activate`
- **Dependencias**: Verificar `requirements.txt` o `setup.py` (si existe)
- **Variables sensibles**: Leer exclusivamente de `config/.env`
- **Scripts de inicio**: 
  - `start_bot.sh`: Inicia el bot por fases
  - `reset_bot.sh`: Limpia slots activos y reinicia el bot

## 8. Flujo de Ejecución

1. **Inicio**: `main.py` → crea instancia de `TradingEngine` → carga `config/strategy.json`
2. **Ciclo principal**: `main.py` → bucle infinito que llama a `engine.run_bot_cycle()`
3. **Escaneo**: `engine.scan_opportunities()` → para cada slot:
   - Si está libre: `_scan_fiat_entry()` busca oportunidades
   - Si está ocupado: `_evaluate_slot()` verifica trailing stop y condiciones de venta
4. **Guardado de estado**: `engine._save_shared_state()` → escribe `shared/state.json`
5. **Dashboard**: Lee `shared/state.json` y muestra información en tiempo real

## 9. Notas Importantes

- El bot está desacoplado: el motor no depende del dashboard y viceversa.
- El dashboard solo lee `shared/state.json`, no hace llamadas directas a la API de Binance.
- La configuración se lee de `config/strategy.json`, no de variables de entorno (excepto credenciales en `.env`).
- El cálculo de `current_value_eur` para cada trade se realiza en `_save_shared_state()` usando `vault.get_asset_value()`.
- Los slots se identifican por `slot_id` (0-3) y se almacenan en la base de datos con `is_active = 1`.

