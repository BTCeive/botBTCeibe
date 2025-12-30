#!/bin/bash
cd /home/ubuntu/botCeibe
source venv/bin/activate
sudo pkill -9 -f 'streamlit|dashboard_simple'
sleep 2
sudo bash -c 'cd /home/ubuntu/botCeibe && source venv/bin/activate && nohup python3 dashboard_simple.py > dashboard_simple.log 2>&1 &'
sleep 3
ps aux | grep dashboard_simple | grep -v grep
echo ''
echo 'Dashboard sin JavaScript iniciado en puerto 80'
echo 'URL: http://80.225.189.86:80'
