# Setup Guide - Cybersecurity NGO Management Platform

This guide outlines the steps to set up and run the Cybersecurity NGO Management Platform locally using Kubernetes (Minikube).

## Prerequisites
- Docker Desktop
- Minikube
- kubectl
- ngrok

## Quick Start

1. **Start Minikube**:
   ```bash
   minikube start
   ```

2. **Deploy the Infrastructure**:
   ```bash
   kubectl apply -k k8s/
   ```

3. **Launch the Application**:
   Wait for all pods to be ready, then run:
   ```bash
   ./start-stack.sh
   ```

## Service Access
- **Web Application**: `http://localhost:5001` (or the ngrok URL provided by the script)
- **Grafana (Monitoring)**: `minikube service grafana-service`
- **Jaeger (Tracing)**: `minikube service jaeger-query`
- **Prometheus (Metrics)**: `minikube service prometheus-service`

## Development
To update the application after code changes:
```bash
eval $(minikube docker-env)
docker build -t ngo-web-app:latest .
kubectl rollout restart deployment web-deployment
```

For more detailed information, see the [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md) (if generated) or refer to the `k8s/` directory for manifest details.
