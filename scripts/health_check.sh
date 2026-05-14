#!/bin/bash
# Health check for Docker/Kubernetes
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
response=$(curl -s -o /dev/null -w "%{http_code}" "${BACKEND_URL}/health")
if [ "$response" -eq 200 ]; then
    echo "✓ Healthy"
    exit 0
else
    echo "✗ Unhealthy (HTTP $response)"
    exit 1
fi
