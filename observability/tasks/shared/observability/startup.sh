#!/bin/bash

# Startup script to run both Django test server and task web wrapper

echo "Starting Django #14792 observability test environment..."

# Start Django test server in background
echo "Starting Django test server..."
cd /testbed
# Run test_bug_14792.py directly, which will use Django from /testbed
python /app/observability/test_bug_14792.py > /tmp/django.log 2>&1 &
DJANGO_PID=$!

# Wait for Django to start
echo "Waiting for Django to initialize..."
# Give Django time to start and run migrations
sleep 5

# Now check if Django is responding
for i in {1..30}; do
    if curl -s http://localhost:8000/health/ > /dev/null 2>&1; then
        echo "✓ Django is responding on port 8000"
        break
    fi
    echo -n "."
    sleep 1
done

# Final check
if ! curl -s http://localhost:8000/health/ > /dev/null 2>&1; then
    echo "Error: Django failed to start properly. Checking if process is running..."
    if ps aux | grep -v grep | grep "runserver" > /dev/null; then
        echo "Django process is running but not responding on port 8000"
        echo "Last logs:"
        tail -20 /tmp/django.log
    else
        echo "Django process died. Last logs:"
        tail -20 /tmp/django.log
    fi
    exit 1
fi

echo "Django server started on port 8000 (PID: $DJANGO_PID)"

# Now start the task web wrapper on a different port
echo "Starting task web wrapper on port 8001..."
export FLASK_PORT=8001
python /app/observability/task_web_wrapper.py &
WRAPPER_PID=$!

echo "Task web wrapper started on port 8001 (PID: $WRAPPER_PID)"

# Wait a moment for other services to initialize, then check observability stack
echo ""
echo "🔍 Checking observability stack status..."
sleep 10

# Check Loki
echo -n "🗂️  Loki (logs): "
if curl -s http://loki:3100/ready | grep -q "ready"; then
    echo "✅ READY (http://loki:3100)"
else
    echo "❌ NOT READY"
fi

# Check Prometheus
echo -n "📊 Prometheus (metrics): "
if curl -s http://prometheus:9090/-/ready | grep -q "Ready"; then
    echo "✅ READY (http://prometheus:9090)"
else
    echo "❌ NOT READY"
fi

# Check Grafana
echo -n "📈 Grafana (dashboards): "
GRAFANA_RESPONSE=$(curl -s http://grafana:3000/api/health 2>/dev/null)
if echo "$GRAFANA_RESPONSE" | grep -q '"database":"ok"'; then
    GRAFANA_VERSION=$(echo "$GRAFANA_RESPONSE" | jq -r '.version // "unknown"' 2>/dev/null || echo "unknown")
    echo "✅ READY v$GRAFANA_VERSION (http://grafana:3000)"
else
    echo "❌ NOT READY"
fi

# Check Locust
echo -n "🔥 Locust (load testing): "
if curl -s http://locust:8089/ 2>/dev/null | grep -q "Locust"; then
    echo "✅ READY (http://locust:8089)"
elif curl -s http://localhost:8089/ 2>/dev/null | grep -q "Locust"; then
    echo "✅ READY (http://localhost:8089)"
else
    echo "❌ NOT READY (still starting)"
fi

echo ""
echo "🎯 Observability stack health check complete!"
echo "📋 Available services:"
echo "   • Django app: http://localhost:8000"
echo "   • Task wrapper: http://localhost:8001"
echo "   • Loki logs: http://loki:3100"
echo "   • Prometheus metrics: http://prometheus:9090"
echo "   • Grafana dashboards: http://grafana:3000"
echo "   • Locust load testing: http://locust:8089"
echo ""

# Function to handle shutdown
cleanup() {
    echo "Shutting down..."
    kill $DJANGO_PID $WRAPPER_PID 2>/dev/null
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Keep the script running and monitor both processes
while true; do
    # Check if Django is still running
    if ! kill -0 $DJANGO_PID 2>/dev/null; then
        echo "Django process died, restarting..."
        cd /testbed && python /app/observability/test_bug_14792.py > /tmp/django.log 2>&1 &
        DJANGO_PID=$!
        sleep 5
    fi

    # Check if wrapper is still running
    if ! kill -0 $WRAPPER_PID 2>/dev/null; then
        echo "Web wrapper died, restarting..."
        export FLASK_PORT=8001
        python /app/observability/task_web_wrapper.py &
        WRAPPER_PID=$!
    fi

    # Use interruptible sleep to allow proper signal handling
    sleep 10 &
    wait $!
done
