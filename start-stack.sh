#!/bin/bash
set -e

# ── Config ──────────────────────────────────────────────
URL="https://lamprey-useful-slug.ngrok-free.app"
SVC_NAME="web-service"
LOCAL_PORT=30001
CLUSTER_NAME="kind"
# ────────────────────────────────────────────────────────

echo "🧹 Cleaning up existing tunnels..."
pkill -f "ngrok" 2>/dev/null || true
sleep 1

# 1. Start Kind only if it's not already running
KIND_STATUS=$(kind get clusters 2>/dev/null | grep -x "$CLUSTER_NAME" || true)
if [ -z "$KIND_STATUS" ]; then
    echo "🚀 Starting Kind cluster..."
    kind create cluster --name "$CLUSTER_NAME" --config k8s/kind-config.yaml
else
    echo "✅ Kind cluster '$CLUSTER_NAME' already running — skipping start."
fi

# 2. Extract the pod selector from the service
echo "🔍 Extracting pod selector from $SVC_NAME..."
SELECTOR=$(kubectl get svc $SVC_NAME -o jsonpath='{.spec.selector.app}' 2>/dev/null || true)

if [ -z "$SELECTOR" ]; then
    echo "❌ Error: Could not find a selector for $SVC_NAME."
    echo "   Run 'kubectl apply -k k8s/' to deploy the stack first."
    exit 1
fi

# 3. Wait for the pod to be ready (up to 120s)
echo "⏳ Waiting for pod 'app=$SELECTOR' to be Ready..."
kubectl wait --for=condition=ready pod -l app=$SELECTOR --timeout=120s

# 4. Verify native port mapping (retry loop instead of blind sleep)
echo "   Verifying native port mapping at 127.0.0.1:$LOCAL_PORT..."
for i in {1..10}; do
    if curl -s --max-time 1 http://127.0.0.1:$LOCAL_PORT > /dev/null 2>&1; then
        echo "   ✅ Web service is accessible locally."
        break
    fi
    if [ $i -eq 10 ]; then
        echo "❌ Failed to connect to Web service after 10 attempts."
        echo "   Please check if the pod is running and kind-config.yaml port mapping is active."
        exit 1
    fi
    sleep 1
done

# 5. Launch Ngrok
echo ""
echo "🌐 Site Live at: $URL"
echo "   (Press Ctrl+C to stop)"
echo ""
ngrok http http://127.0.0.1:$LOCAL_PORT --url=$URL
