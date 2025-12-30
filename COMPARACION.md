# Comparación: Código Antiguo vs Nuevo

## ✅ Archivos Completamente Adaptados

### 1. `core.py` → `botCeibe/engine/trading_logic.py`
- ✅ Toda la lógica de trading adaptada
- ✅ Lee configuración desde `strategy.json` en lugar de `config.py`
- ✅ Rutas corregidas (ROOT_DIR para bitácora, rutas relativas para config/state)
- ✅ Base de datos usa ruta absoluta
- **Estado**: COMPLETO - `core.py` puede eliminarse

### 2. `main.py` → `botCeibe/main.py`
- ✅ Bucle principal adaptado
- ✅ Inicialización mejorada (detección de posiciones, gestión BNB)
- ✅ Snapshots del portfolio agregados
- ✅ Intervalos configurables desde `strategy.json`
- **Estado**: COMPLETO - `main.py` antiguo puede eliminarse

### 3. `dashboard.py` → `botCeibe/dashboard/app.py`
- ✅ Lectura de `shared/state.json` (en lugar de `shared_state.json`)
- ✅ Manejo de errores de lectura mejorado
- ✅ Bitácora agregada
- ✅ Todas las secciones principales adaptadas
- **Estado**: COMPLETO - `dashboard.py` puede eliminarse

### 4. `run_bot.py`
- ⚠️ Similar a `botCeibe/main.py` pero más simple
- ❌ No tiene detección de posiciones
- ❌ No tiene gestión de BNB
- ❌ No tiene snapshots
- **Estado**: OBSOLETO - Puede eliminarse (usar `botCeibe/main.py`)

## 📁 Archivos Compartidos (NO eliminar)

Estos archivos son compartidos y se usan desde ambos sistemas:
- `config.py` - Configuración de Binance API (se usa desde botCeibe)
- `database.py` - Base de datos (se usa desde botCeibe)
- `vault.py` - Gestión de activos (se usa desde botCeibe)
- `router.py` - Gestión de pares (se usa desde botCeibe)
- `signals.py` - Indicadores técnicos (se usa desde botCeibe)

## 🔧 Correcciones Realizadas

### Rutas de Archivos
- ✅ `bitacora.txt`: Usa `ROOT_DIR / 'bitacora.txt'` (ruta absoluta)
- ✅ `state.json`: Usa `Path(__file__).parent.parent / "shared" / "state.json"` (ruta relativa)
- ✅ `strategy.json`: Usa `Path(__file__).parent.parent / "config" / "strategy.json"` (ruta relativa)
- ✅ `multibot.db`: Usa ruta absoluta desde `ROOT_DIR / DB_PATH`

### Permisos
- ✅ `state.json`: Permisos 664 (rw-rw-r--) - Permite lectura/escritura para usuario y grupo

### Funcionalidades Agregadas
- ✅ Snapshots del portfolio (cada 30 min, configurable)
- ✅ Manejo mejorado de errores en lectura de state.json
- ✅ Bitácora en dashboard

## 🗑️ Archivos a Eliminar

Una vez verificado que todo funciona:
1. `core.py` - Reemplazado por `botCeibe/engine/trading_logic.py`
2. `main.py` (raíz) - Reemplazado por `botCeibe/main.py`
3. `dashboard.py` - Reemplazado por `botCeibe/dashboard/app.py`
4. `run_bot.py` - Obsoleto, usar `botCeibe/main.py`
5. `shared_state.json` (raíz) - Reemplazado por `botCeibe/shared/state.json`

## ⚠️ Archivos a Mantener

- `bitacora.txt` - Se usa desde ambos sistemas (en raíz)
- `multibot.db` - Base de datos compartida (en raíz)
- `config.py`, `database.py`, `vault.py`, `router.py`, `signals.py` - Módulos compartidos

