#!/bin/bash
# Script para iniciar el dashboard Streamlit en el puerto 8501

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Activar entorno virtual
source venv/bin/activate

# Verificar que Streamlit esté instalado
python3 -c "import streamlit" 2>/dev/null || {
    echo "Instalando Streamlit..."
    pip install streamlit
}

# Iniciar dashboard Streamlit en puerto 8501
echo "Iniciando dashboard Streamlit en puerto 8501..."
echo "URL: http://localhost:8501"
streamlit run dashboard/app.py --server.port 8501 --server.address localhost

