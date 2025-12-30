# Dashboard botCeibe - Sin JavaScript

## Versión sin JavaScript

El proyecto ahora usa **dashboard_flask.py** que funciona completamente sin JavaScript.

### Características

- ✅ **Sin JavaScript**: Solo HTML y CSS puro
- ✅ **Auto-actualización**: Usa meta refresh cada 10 segundos
- ✅ **Compatible**: Funciona en cualquier navegador, incluso sin JavaScript habilitado
- ✅ **Ligero**: No requiere librerías JavaScript pesadas

### Iniciar el Dashboard

```bash
./start_dashboard.sh
```

O específicamente:

```bash
./start_dashboard_flask.sh
```

### Acceso

Una vez iniciado, accede a:
- http://localhost:80
- http://[IP_DEL_SERVIDOR]:80

### Archivos

- `dashboard_flask.py` - Dashboard principal sin JavaScript (Flask)
- `dashboard/app.py` - Dashboard original con Streamlit (requiere JavaScript)
- `start_dashboard.sh` - Script de inicio (ahora usa Flask por defecto)
- `start_dashboard_flask.sh` - Script específico para Flask

### Notas

- El dashboard se actualiza automáticamente cada 10 segundos
- No requiere JavaScript en el navegador
- Funciona con cualquier navegador moderno
