# Despliegue del bot en servidor remoto ✅

## Requisitos locales
- Tener la clave SSH: por ejemplo `/home/lorenzo/Descargas/ssh-key-2025-12-19.key`
- Ejecutar el script `scripts/deploy_to_server.sh` desde la raíz del repo

## Comando recomendado (desde tu máquina local)

```bash
chmod +x ./scripts/deploy_to_server.sh
./scripts/deploy_to_server.sh -k /home/lorenzo/Descargas/ssh-key-2025-12-19.key -h ubuntu@80.225.189.86
```

El script hará:
- Copiar el código al directorio remoto `/home/ubuntu/botCeibe` (puedes cambiarlo con `-r`)
- Crear/actualizar un `venv` y ejecutar `pip install -r requirements.txt`
- Crear la unidad systemd `/etc/systemd/system/botceibe.service`
- Habilitar y arrancar el servicio `botceibe.service`

## Comprobaciones y recuperación
- Ver el estado del servicio:
  - `ssh -i /ruta/tu_key ubuntu@host "sudo systemctl status -l --no-pager botceibe.service"`
- Ver logs en tiempo real:
  - `ssh -i /ruta/tu_key ubuntu@host "sudo journalctl -u botceibe.service -f"`
- Ver archivo de arranque del bot (creado por `start_bot.sh`):
  - `tail -n 200 /home/ubuntu/botCeibe/bot_startup.log`

## Notas de seguridad
- Crea `config/.env` en el servidor con tus claves de API y da permisos restringidos:
  - `chmod 600 /home/ubuntu/botCeibe/config/.env`
- El script no copia claves privadas ni secretos; asegúrate de cargar `config/.env` manualmente si contiene datos sensibles.

## Si prefieres pasos manuales
1. Conectar por SSH:
   - `ssh -i /ruta/tu_key ubuntu@80.225.189.86`
2. Clonar/rsync el repo en `/home/ubuntu/botCeibe`
3. Crear venv: `python3 -m venv venv && source venv/bin/activate`
4. Instalar dependencias: `pip install -r requirements.txt`
5. Colocar `config/.env` y ajustar permisos
6. Crear unit systemd (usar `config/botceibe.service`) y ejecutar:
   - `sudo cp config/botceibe.service /etc/systemd/system/botceibe.service`
   - `sudo systemctl daemon-reload && sudo systemctl enable --now botceibe.service`

---
Si quieres, puedo: (1) ajustar el script para usar otro usuario/remoto, (2) añadir comprobaciones extra o (3) añadir la plantilla `.env.example`. Dime cuál prefieres y lo implemento.
