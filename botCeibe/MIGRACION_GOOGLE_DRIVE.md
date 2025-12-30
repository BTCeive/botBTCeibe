# Migración a Google Drive - BotCeibe

## ✅ Migración Completada

Fecha: 29 de diciembre de 2025

### 📍 Ubicación del Proyecto en Google Drive

El proyecto ha sido migrado exitosamente a:

```
Google Drive > Mi unidad > botCeibe
```

**Ruta del sistema de archivos (GVFS):**
```bash
/run/user/$(id -u)/gvfs/google-drive:host=gmail.com,user=dz.loren/0AD1z3-9XB8J_Uk9PVA/1w1_H_GkWUnhzWkeW0hqtewcQDjEgd9ma/1IRnkVFIpHAdpC-eOxNZqBUbQwKQD2xJt/botCeibe
```

### 📦 Archivos Migrados

✅ **Archivos Python**: Todos los `.py` principales
✅ **Carpeta `config/`**: Incluye `.env`, `strategy.json`, etc.
✅ **Carpeta `engine/`**: Lógica de trading
✅ **Carpeta `dashboard/`**: Dashboard Streamlit
✅ **Carpeta `shared/`**: Base de datos (`bot_data.db`) y archivos de estado
✅ **Documentación**: Todos los archivos `.md`
✅ **Configuración**: `requirements.txt`, scripts `.sh`

❌ **Archivos NO migrados** (según filtro):
- Carpeta `venv/` (entorno virtual)
- Carpetas `__pycache__/`
- Archivos `.log.old`
- Archivos `.pid`
- Archivos temporales del sistema

### 🔧 Ajustes Realizados

#### Rutas Convertidas a Relativas:

1. **`bot_config.py`**: 
   - ❌ Antes: `/home/lorenzo/Escritorio/proyect/botCeibe/config/.env`
   - ✅ Ahora: `ROOT_DIR / 'config' / '.env'`

2. **`test_portfolio_calc.py`**:
   - ❌ Antes: `/home/lorenzo/Escritorio/proyect/botCeibe`
   - ✅ Ahora: `ROOT_DIR = Path(__file__).parent`

3. **`engine/trading_logic.py`**:
   - ❌ Antes: `/home/lorenzo/Escritorio/proyect/botCeibe/shared/radar_emergency.csv`
   - ✅ Ahora: `ROOT_DIR / 'shared' / 'radar_emergency.csv'`

### 🚀 Cómo Trabajar desde Google Drive

#### Opción 1: Alias de Bash (Recomendado)

Añade esto a tu `~/.bashrc`:

```bash
export BOTCEIBE_GDRIVE="/run/user/$(id -u)/gvfs/google-drive:host=gmail.com,user=dz.loren/0AD1z3-9XB8J_Uk9PVA/1w1_H_GkWUnhzWkeW0hqtewcQDjEgd9ma/1IRnkVFIpHAdpC-eOxNZqBUbQwKQD2xJt/botCeibe"
alias cdbot='cd "$BOTCEIBE_GDRIVE"'
```

Luego:
```bash
source ~/.bashrc
cdbot  # Te lleva directamente al proyecto en Google Drive
```

#### Opción 2: Script de Acceso Rápido

Crear `~/go_botceibe.sh`:

```bash
#!/bin/bash
cd "/run/user/$(id -u)/gvfs/google-drive:host=gmail.com,user=dz.loren/0AD1z3-9XB8J_Uk9PVA/1w1_H_GkWUnhzWkeW0hqtewcQDjEgd9ma/1IRnkVFIpHAdpC-eOxNZqBUbQwKQD2xJt/botCeibe"
exec bash
```

```bash
chmod +x ~/go_botceibe.sh
~/go_botceibe.sh
```

### 🎯 Verificación Post-Migración

✅ **Carga de configuración**: `.env` se carga correctamente
✅ **Base de datos accesible**: `shared/bot_data.db` (12 MB) presente
✅ **Dashboard funcional**: Streamlit arranca sin errores desde Google Drive
✅ **Rutas relativas**: Todos los paths son portables

### 🔍 Comandos de Verificación

```bash
# Acceder al proyecto
BOTCEIBE_GDRIVE="/run/user/$(id -u)/gvfs/google-drive:host=gmail.com,user=dz.loren/0AD1z3-9XB8J_Uk9PVA/1w1_H_GkWUnhzWkeW0hqtewcQDjEgd9ma/1IRnkVFIpHAdpC-eOxNZqBUbQwKQD2xJt/botCeibe"

# Ver estructura
ls -la "$BOTCEIBE_GDRIVE"

# Verificar base de datos
ls -lh "$BOTCEIBE_GDRIVE/shared/bot_data.db"

# Probar carga de config
cd "$BOTCEIBE_GDRIVE"
python3 bot_config.py

# Arrancar dashboard
cd "$BOTCEIBE_GDRIVE"
streamlit run dashboard/app.py --server.port 8501
```

### 📝 Notas Importantes

1. **Google Drive debe estar montado**: Si no ves los archivos, asegúrate de que Google Drive está conectado en la configuración de GNOME Online Accounts.

2. **Permisos en GVFS**: Algunas operaciones (como `rsync` con archivos temporales) no son compatibles con GVFS. Usa `cp` para copiar archivos.

3. **Sincronización automática**: Los cambios se sincronizan automáticamente con la nube.

4. **Backup local recomendado**: Aunque Google Drive es confiable, mantén copias de seguridad locales periódicas de `shared/bot_data.db`.

### ⚠️ Limitaciones de GVFS

- No se pueden establecer permisos Unix tradicionales
- Algunos comandos avanzados de terminal pueden tener comportamiento diferente
- La sincronización puede añadir latencia a operaciones de I/O intensivas

### 🎉 Ventajas de la Migración

✅ **Acceso desde cualquier lugar**: Tu bot en la nube
✅ **Backup automático**: Google Drive guarda versiones
✅ **Sincronización multi-dispositivo**: Trabaja desde varios equipos
✅ **Sin rutas hardcodeadas**: El código es totalmente portable

---

## 🔄 Próximos Pasos

1. Verificar que el bot funcione correctamente desde la nueva ubicación
2. Configurar un entorno virtual en la nueva ubicación si es necesario:
   ```bash
   cd "$BOTCEIBE_GDRIVE"
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Actualizar cualquier servicio systemd o cron job que apunte a la ubicación antigua

4. Considerar eliminar la carpeta antigua una vez confirmado que todo funciona:
   ```bash
   # NO EJECUTAR hasta confirmar que todo funciona
   # rm -rf /home/lorenzo/Escritorio/proyect/botCeibe
   ```
