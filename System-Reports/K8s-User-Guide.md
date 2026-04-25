# Kubernetes User Guide & Migration Documentation

This guide provides operational instructions, architectural details, and a migration summary for the **Cybersecurity NGO Management** platform running on Minikube.

---

## 1. Operational User Guide

### 🚀 Starting the Environment
To bring up the entire stack from scratch:

```bash
# 1. Start the cluster
minikube start --cpus 4 --memory 4096

# 2. Build local images inside Minikube
eval $(minikube docker-env)
docker build -t ngo-web-app:latest .
docker build -t ngo-fluentd:latest ./monitoring/fluentd

# 3. Enable Ingress (for future routing)
minikube addons enable ingress

# 4. Deploy all resources
kubectl apply -k k8s/
```

### 🔍 Accessing Applications
Since we use `NodePort` services for local access:

| Service | Command to Open | URL (via minikube ip) |
| :--- | :--- | :--- |
| **Web App** | `minikube service web-service` | `http://$(minikube ip):30001` |
| **Grafana** | `minikube service grafana-service` | `http://$(minikube ip):30002` |
| **Jaeger** | `kubectl port-forward svc/jaeger-service 16686:16686` | `http://localhost:16686` |
| **Prometheus**| `kubectl port-forward svc/prometheus-service 9090:9090` | `http://localhost:9090` |

### 🛠️ Useful kubectl Commands

**Check Health of All Pods:**
```bash
kubectl get pods
```

**Stream Application Logs:**
```bash
kubectl logs -f deployment/web
```

**Restart a Specific Service (e.g., Fluentd):**
```bash
kubectl rollout restart daemonset/fluentd
```

**Scale the Web Tier:**
```bash
kubectl scale deployment/web --replicas=3
```

**Enter a Database Shell (PostgreSQL):**
```bash
kubectl exec -it db-0 -- psql -U postgres -d ngo_db
```

---

## 2. Cluster Architecture & Persistence

### 🏗️ Workload Architecture
The project has transitioned from a standard `docker-compose.yml` to a structured Kubernetes hierarchy:

*   **Data Tier (StatefulSets)**: `db` and `elasticsearch` are managed as `StatefulSets`. Unlike standard Deployments, StatefulSets provide stable network IDs (`db-0`) and ensure that specific volumes are re-attached to the same pod instance during restarts.
*   **App Tier (Deployments)**: `web`, `prometheus`, `grafana`, and `jaeger` use standard `Deployments`. They are stateless or store their configuration in ConfigMaps, allowing them to scale horizontally across the cluster.
*   **Observability Agent (DaemonSet)**: `fluentd` runs as a `DaemonSet`. This ensures exactly one instance runs on every node of the cluster to capture logs from `/var/log/containers/`.

### 💾 Persistence Configuration
Kubernetes handles storage through **PersistentVolumeClaims (PVCs)** and **Dynamic Provisioning**:

1.  **Volume Templates**: Inside `k8s/app/db.yaml` and `k8s/monitoring/elasticsearch.yaml`, we define `volumeClaimTemplates`.
2.  **Mounting**: The system automatically requests a volume from Minikube's `standard` storage class.
3.  **Stability**: If the `db-0` pod is deleted, the data remains in the volume. When Kubernetes recreates the pod, it automatically re-mounts the volume to `/var/lib/postgresql/data`.
4.  **Permission Management**: We implemented an `initContainer` in `elasticsearch.yaml` that runs as root to `chown` the volume directory to the Elasticsearch user (uid: 1000) before the main service starts.

---

## 3. Migration Walkthrough: Step-by-Step

The migration followed a 4-phase transformation to ensure a stable, production-ready Kubernetes environment.

### Phase 1: Resource Mapping & Translation
*   **Action**: Converted `docker-compose` services into Kubernetes `Deployment`, `Service`, `Secret`, and `ConfigMap` objects.
*   **Result**: Created a structured `k8s/` directory to separate App, Monitoring, and Persistence layers.

### Phase 2: Resolving Data Initialization & Dependencies
*   **Challenge**: The Flask app would crash if it attempted to connect to Postgres before the database was ready.
*   **Action**: Implemented an **Init Container** in `web.yaml`. This container uses Python/SQLAlchemy to poll the database connection and runs `db.create_all()` only once the connection is successful.

### Phase 3: Fixing Networking & DNS Resolution
*   **Challenge**: Services like Fluentd and Grafana were hardcoded to use `http://elasticsearch:9200`. In K8s, service discovery requires the full service name.
*   **Action**: Updated all configurations and `datasources.yml` to use `-service` suffixes (e.g., `elasticsearch-service`). We also converted `elasticsearch-service` from "Headless" to a standard ClusterIP to ensure reliable internal DNS resolution.

### Phase 4: Enabling Cluster-Wide Observability
*   **Challenge**: Standard Docker logging drivers do not exist in Kubernetes.
*   **Action**: 
    1.  Modified `app.py` to output JSON logs to `stdout`.
    2.  Deployed Fluentd as a `DaemonSet` to scrape logs from the node's `/var/log` directory.
    3.  Modified Fluentd's `securityContext` to allow root access for log-scraping, ensuring logs flow smoothly into the Elasticsearch backend.

---

*This guide will be updated as the cluster evolves. For troubleshooting, always check `kubectl describe pod <pod-name>` first.*
