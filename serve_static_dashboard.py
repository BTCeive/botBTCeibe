#!/usr/bin/env python3
"""Servidor HTTP simple para servir el dashboard estático"""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import subprocess
from pathlib import Path

class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/dashboard":
            # Regenerar dashboard antes de servir
            subprocess.run(["python3", "generate_dashboard.py"], cwd=os.getcwd())
            self.path = "/dashboard_static.html"
        # Llamar al handler padre correctamente (sin pasar 'self')
        return super().do_GET()

if __name__ == "__main__":
    port = 8080
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"Servidor iniciado en http://0.0.0.0:{port}")
    print("Dashboard accesible en: http://80.225.189.86:8080")
    server.serve_forever()
