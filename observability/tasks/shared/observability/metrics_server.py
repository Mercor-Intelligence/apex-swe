#!/usr/bin/env python3
"""
Simple HTTP server to expose Prometheus metrics from static files.

This server reads metrics from /data/metrics/*.prom files and serves them
at /metrics endpoint for Prometheus to scrape. Used in static data mode.

Usage:
    python metrics_server.py

Serves on: http://localhost:8000/metrics
"""

import glob
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

METRICS_DIR = Path("/data/metrics")
PORT = 8000


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves Prometheus metrics from files"""

    def do_GET(self):
        """Handle GET requests"""
        if self.path == "/metrics":
            self.serve_metrics()
        elif self.path == "/health":
            self.serve_health()
        else:
            self.send_error(404, "Not Found")

    def serve_metrics(self):
        """Serve aggregated metrics from all .prom files"""
        try:
            # Collect all metrics from .prom files
            metrics_content = []
            
            # Add server metadata
            metrics_content.append("# Metrics from static files")
            metrics_content.append(f"# Last updated: {time.time()}")
            metrics_content.append("")
            
            # Read all .prom files
            prom_files = sorted(METRICS_DIR.glob("*.prom"))
            
            if not prom_files:
                metrics_content.append("# No metrics files found in /data/metrics/")
                metrics_content.append("# Generate data first using test_bug script")
            else:
                for prom_file in prom_files:
                    metrics_content.append(f"# From: {prom_file.name}")
                    try:
                        content = prom_file.read_text()
                        metrics_content.append(content)
                        metrics_content.append("")
                    except Exception as e:
                        metrics_content.append(f"# Error reading {prom_file.name}: {e}")
            
            # Send response
            response = "\n".join(metrics_content)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", len(response.encode()))
            self.end_headers()
            self.wfile.write(response.encode())
            
        except Exception as e:
            self.send_error(500, f"Internal Server Error: {e}")

    def serve_health(self):
        """Serve health check endpoint"""
        response = "OK"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", len(response.encode()))
        self.end_headers()
        self.wfile.write(response.encode())

    def log_message(self, format, *args):
        """Override to reduce logging noise"""
        # Only log errors
        if args[1] != "200":
            super().log_message(format, *args)


def run_server():
    """Start the metrics server"""
    # Ensure metrics directory exists
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"[INFO] Starting Prometheus metrics server on port {PORT}")
    print(f"[INFO] Serving metrics from: {METRICS_DIR}")
    print(f"[INFO] Metrics endpoint: http://localhost:{PORT}/metrics")
    print(f"[INFO] Health endpoint: http://localhost:{PORT}/health")
    print("")
    
    # Check if metrics files exist
    prom_files = list(METRICS_DIR.glob("*.prom"))
    if prom_files:
        print(f"[INFO] Found {len(prom_files)} metrics file(s):")
        for f in prom_files:
            print(f"   - {f.name}")
    else:
        print("[WARN] No metrics files found yet!")
        print("       Run the test_bug script to generate metrics first.")
    
    print("")
    print("[INFO] Server ready - Prometheus can now scrape /metrics")
    print("")
    
    # Start server
    server = HTTPServer(("0.0.0.0", PORT), MetricsHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down metrics server...")
        server.shutdown()


if __name__ == "__main__":
    run_server()
