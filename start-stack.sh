#!/bin/bash
set -e

# ── Config ──────────────────────────────────────────────
URL="https://lamprey-useful-slug.ngrok-free.app"
SVC_NAME="web-service"
LOCAL_PORT=5001
# ────────────────────────────────────────────────────────

echo "🧹 Cleaning up existing tunnels..."
pkill -f "kubectl port-forward" 2>/dev/null || true
pkill -f "ngrok" 2>/dev/null || true
sleep 1

# 1. Start Minikube only if it's not already running
MINIKUBE_STATUS=$(minikube status --format='{{.Host}}' 2>/dev/null || echo "Stopped")
if [ "$MINIKUBE_STATUS" != "Running" ]; then
    echo "🚀 Starting Minikube..."
    minikube start
else
    echo "✅ Minikube already running — skipping start."
fi

# 2. Extract the pod selector from the service
echo "🔍 Extracting pod selector from $SVC_NAME..."
SELECTOR=$(kubectl get svc $SVC_NAME -o jsonpath='{.spec.selector.app}')

if [ -z "$SELECTOR" ]; then
    echo "❌ Error: Could not find a selector for $SVC_NAME."
    echo "   Run 'kubectl apply -k k8s/' to deploy the stack first."
    exit 1
fi

# 3. Wait for the pod to be ready (up to 120s)
echo "⏳ Waiting for pod 'app=$SELECTOR' to be Ready..."
kubectl wait --for=condition=ready pod -l app=$SELECTOR --timeout=120s

# 4. Port Forward (Force IPv4 to avoid loopback issues)
echo "🔗 Port-forwarding 127.0.0.1:$LOCAL_PORT -> $SVC_NAME..."
kubectl port-forward --address 127.0.0.1 svc/$SVC_NAME $LOCAL_PORT:$LOCAL_PORT > /tmp/pf.log 2>&1 &
PF_PID=$!

# 5. Verify port-forward actually connected (retry loop instead of blind sleep)
echo "   Verifying port-forward..."
for i in {1..10}; do
    if curl -s --max-time 1 http://127.0.0.1:$LOCAL_PORT > /dev/null 2>&1; then
        echo "   ✅ Port-forward is live."
        break
    fi
    if [ $i -eq 10 ]; then
        echo "❌ Port-forward failed to connect after 10 attempts."
        echo "   Check logs: cat /tmp/pf.log"
        kill $PF_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# 6. Launch Ngrok
echo ""
echo "🌐 Site Live at: $URL"
echo "   (Press Ctrl+C to stop)"
echo ""
ngrok http http://127.0.0.1:$LOCAL_PORT --url=$URL
