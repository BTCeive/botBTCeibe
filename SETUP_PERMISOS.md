# Configuración de Permisos y Rutas

## 🔧 Problemas Corregidos

### 1. Rutas de Archivos

#### `.env` (Variables de Entorno)
- **Problema**: `load_dotenv()` busca `.env` en el directorio actual de trabajo, no donde está el script
- **Solución**: `trading_logic.py` ahora busca explícitamente `.env` en `ROOT_DIR/.env`
- **Ubicación esperada**: `/home/lorenzo/Escritorio/proyect/botCeibe/.env`

#### Base de Datos (`multibot.db`)
- **Problema**: Ruta relativa podría causar problemas si se ejecuta desde diferentes directorios
- **Solución**: Se usa ruta absoluta `ROOT_DIR / DB_PATH`
- **Ubicación**: `/home/lorenzo/Escritorio/proyect/botCeibe/multibot.db`

#### `bitacora.txt`
- **Solución**: Usa `ROOT_DIR / 'bitacora.txt'` (ruta absoluta)
- **Ubicación**: `/home/lorenzo/Escritorio/proyect/botCeibe/bitacora.txt`

### 2. Permisos de `state.json`

#### Problema
Si el motor se ejecuta con `sudo` y el dashboard sin `sudo`, pueden tener diferentes usuarios y el dashboard no podrá leer los cambios.

#### Solución Implementada
- **Permisos**: `664` (rw-rw-r--) - Permite lectura/escritura para usuario y grupo
- **Aplicación automática**: Los permisos se establecen cada vez que se escribe el archivo
- **Ubicación**: `shared/state.json`

#### Verificación Manual
```bash
# Verificar permisos actuales
ls -la shared/state.json

# Debería mostrar: -rw-rw-r-- (664)
# Si no, corregir manualmente:
chmod 664 shared/state.json
```

## 📝 Recomendaciones

### Ejecutar sin `sudo` (Recomendado)
```bash
# Motor
python3 main.py

# Dashboard
streamlit run dashboard/app.py
```

### Si necesitas usar `sudo`
1. Asegúrate de que el usuario del dashboard esté en el mismo grupo
2. O cambia los permisos a `666` (rw-rw-rw-):
```bash
chmod 666 shared/state.json
```

### Verificar Permisos del Directorio
```bash
# El directorio shared también debe tener permisos adecuados
ls -ld shared/
# Debería mostrar: drwxrwxr-x (775) o similar
```

## 🔍 Verificación de Rutas

### Verificar que `.env` se carga correctamente
```bash
# Desde el directorio raíz del proyecto
cd /home/lorenzo/Escritorio/proyect/botCeibe
python3 -c "from pathlib import Path; from dotenv import load_dotenv; load_dotenv(Path('.env')); import os; print('API Key cargada:', 'Sí' if os.getenv('BINANCE_API_KEY') else 'No')"
```

### Verificar rutas en el código
```python
# En trading_logic.py, ROOT_DIR apunta a:
# /home/lorenzo/Escritorio/proyect/botCeibe

# Archivos buscados en:
# - ROOT_DIR / '.env'
# - ROOT_DIR / 'multibot.db'
# - ROOT_DIR / 'bitacora.txt'
# - Path(__file__).parent.parent / "config" / "strategy.json"
# - Path(__file__).parent.parent / "shared" / "state.json"
```

