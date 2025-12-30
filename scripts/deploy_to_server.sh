#!/usr/bin/env bash
set -euo pipefail

# Script de despliegue para BotCeibe
# Uso:
#   ./scripts/deploy_to_server.sh -k /ruta/a/ssh_key -h ubuntu@80.225.189.86 [-r /home/ubuntu/botCeibe]

SSH_KEY=""
REMOTE_HOST=""
REMOTE_DIR="/home/ubuntu/botCeibe"

print_help() {
  echo "Uso: $0 -k /ruta/a/ssh_key -h user@host [-r /ruta/remota]"
  exit 1
}

while getopts "k:h:r:" opt; do
  case $opt in
    k) SSH_KEY="$OPTARG" ;; 
    h) REMOTE_HOST="$OPTARG" ;; 
    r) REMOTE_DIR="$OPTARG" ;; 
    *) print_help ;;
  esac
done

if [ -z "$SSH_KEY" ] || [ -z "$REMOTE_HOST" ]; then
  print_help
fi

echo "Desplegando a $REMOTE_HOST -> $REMOTE_DIR"

# Excluir entornos y caches
RSYNC_EXCLUDES=("--exclude" "venv" "--exclude" "__pycache__" "--exclude" ".git" "--exclude" "*.pyc")

# Copiar proyecto al servidor
rsync -az ${RSYNC_EXCLUDES[@]} -e "ssh -i $SSH_KEY" ./ $REMOTE_HOST:$REMOTE_DIR

# Comandos remotos para preparar entorno y servicio
read -r -d '' REMOTE_CMD <<'EOF'
set -euo pipefail
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip rsync
mkdir -p "${REMOTE_DIR}"
cd "${REMOTE_DIR}"

# Crear venv si no existe
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi

# Activar e instalar dependencias
source venv/bin/activate
python3 -m pip install --upgrade pip
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi

# Comprobar fichero de configuración .env
if [ ! -f config/.env ]; then
  echo "WARNING: config/.env no encontrado. Debes crear el archivo con tus variables (API keys)." >&2
fi

# Crear unit systemd
SERVICE_FILE="/etc/systemd/system/botceibe.service"
sudo tee "$SERVICE_FILE" > /dev/null <<SERV
[Unit]
Description=Bot Ceibe
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=${REMOTE_DIR}
ExecStart=/bin/bash ${REMOTE_DIR}/start_bot.sh
EnvironmentFile=${REMOTE_DIR}/config/.env
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=botceibe

[Install]
WantedBy=multi-user.target
SERV

sudo systemctl daemon-reload
sudo systemctl enable --now botceibe.service
sudo systemctl restart botceibe.service || true
sudo systemctl status -l --no-pager botceibe.service
EOF

# Ejecutar comandos remotos
ssh -i "$SSH_KEY" "$REMOTE_HOST" "bash -s" <<REMOTE
REMOTE_DIR="$REMOTE_DIR"
$REMOTE_CMD
REMOTE

echo "Despliegue completado. Revisa el servicio y los logs con: sudo journalctl -u botceibe.service -f"