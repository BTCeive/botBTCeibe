#!/bin/bash
cd /home/ubuntu/botCeibe
source venv/bin/activate
pkill -9 -f "streamlit.*app.py"
sleep 2
nohup streamlit run dashboard/app.py --server.port 80 --server.address 0.0.0.0 --server.headless true --server.enableCORS false --server.enableXsrfProtection false > dashboard.log 2>&1 &
echo "Dashboard iniciado. PID: $!"
sleep 3
ps aux | grep streamlit | grep -v grep
