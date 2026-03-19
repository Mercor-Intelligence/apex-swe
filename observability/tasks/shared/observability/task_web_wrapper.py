#!/usr/bin/env python3
"""
Web wrapper for Apex-Code tasks to enable observability testing.
This runs in the client container and provides HTTP endpoints for Locust to test.
"""

import os
import queue
import subprocess
import threading
import time
from datetime import datetime

import psutil
from flask import Flask, jsonify, request

app = Flask(__name__)

# Task execution queue
task_queue = queue.Queue()
execution_results = {}


class TaskExecutor:
    """Executes task commands"""

    def __init__(self):
        self.current_task = None
        self.execution_count = 0

    def execute_command(self, command):
        """Execute a shell command"""
        self.execution_count += 1
        task_id = f"task_{self.execution_count}_{int(time.time() * 1000)}"

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )

            return {
                "task_id": task_id,
                "command": command,
                "status": "success" if result.returncode == 0 else "error",
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timestamp": datetime.now().isoformat(),
            }
        except subprocess.TimeoutExpired:
            return {
                "task_id": task_id,
                "command": command,
                "status": "timeout",
                "error": "Command execution timed out after 30 seconds",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            return {
                "task_id": task_id,
                "command": command,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }


executor = TaskExecutor()


# Background worker
def task_worker():
    """Process tasks in the background"""
    while True:
        try:
            task = task_queue.get(timeout=1)
            if task is None:
                break

            task_id = task["id"]
            command = task["command"]

            result = executor.execute_command(command)
            execution_results[task_id] = result

        except queue.Empty:
            continue
        except Exception as e:
            print(f"Worker error: {e}")


# Start worker thread
worker = threading.Thread(target=task_worker, daemon=True)
worker.start()


# Routes
@app.route("/")
def index():
    """Root endpoint"""
    return jsonify(
        {
            "service": "Apex Task Web Wrapper",
            "status": "running",
            "task_name": os.environ.get("APEX_TASK_NAME", "unknown"),
            "execution_count": executor.execution_count,
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.route("/health")
def health():
    """Health check endpoint"""
    return jsonify(
        {"status": "healthy", "uptime": time.time(), "worker_alive": worker.is_alive()}
    )


@app.route("/api/status")
def status():
    """Detailed status"""
    return jsonify(
        {
            "status": "running",
            "system": {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_usage": psutil.disk_usage("/").percent,
            },
            "task": {
                "name": os.environ.get("APEX_TASK_NAME", "unknown"),
                "executions": executor.execution_count,
                "queue_size": task_queue.qsize(),
            },
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.route("/execute", methods=["POST"])
def execute():
    """Execute a command"""
    data = request.get_json()
    if not data or "command" not in data:
        return jsonify({"error": "command is required"}), 400

    command = data["command"]
    async_mode = data.get("async", False)

    if async_mode:
        # Queue for async execution
        task_id = f"async_{int(time.time() * 1000)}"
        task_queue.put({"id": task_id, "command": command})
        return jsonify(
            {
                "task_id": task_id,
                "status": "queued",
                "queue_position": task_queue.qsize(),
            }
        ), 202
    else:
        # Execute synchronously
        result = executor.execute_command(command)
        return jsonify(result)


@app.route("/run", methods=["POST"])
def run():
    """Alternative execution endpoint"""
    return execute()


@app.route("/api/exec", methods=["POST"])
def api_exec():
    """API execution endpoint"""
    return execute()


@app.route("/output")
def get_output():
    """Get execution output"""
    return jsonify(
        {
            "executions": list(execution_results.values())[-10:],  # Last 10
            "total": len(execution_results),
        }
    )


@app.route("/api/output")
def api_output():
    """API output endpoint"""
    return get_output()


@app.route("/results/<task_id>")
def get_result(task_id):
    """Get specific task result"""
    if task_id in execution_results:
        return jsonify(execution_results[task_id])
    return jsonify({"error": "Task not found"}), 404


@app.route("/metrics")
def metrics():
    """Prometheus-compatible metrics"""
    metrics_text = f"""# HELP task_executions_total Total number of task executions
# TYPE task_executions_total counter
task_executions_total {executor.execution_count}

# HELP task_queue_size Current size of task queue
# TYPE task_queue_size gauge
task_queue_size {task_queue.qsize()}

# HELP task_success_total Total successful executions
# TYPE task_success_total counter
task_success_total {sum(1 for r in execution_results.values() if r.get('status') == 'success')}

# HELP task_error_total Total failed executions
# TYPE task_error_total counter
task_error_total {sum(1 for r in execution_results.values() if r.get('status') == 'error')}
"""
    return metrics_text, 200, {"Content-Type": "text/plain"}


# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    # Install psutil if not available
    try:
        import psutil
    except ImportError:
        subprocess.run(["pip", "install", "psutil"], check=True)
        import psutil

    # Get port from environment or default to 8001
    port = int(os.environ.get("FLASK_PORT", 8001))

    print(f"Starting Apex Task Web Wrapper on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
