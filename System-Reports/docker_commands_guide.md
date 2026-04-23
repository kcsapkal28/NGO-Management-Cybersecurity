# Docker Commands Guide for NGO Management Platform

This guide outlines the most important and frequently used Docker and Docker Compose commands for operating the NGO management and observability stack.

## 1. Managing the Full Stack

**Start the entire stack in the background (detached mode):**
```bash
docker-compose up -d
```
*Tip: Use `--build` if you have modified the `Dockerfile` or any Python/HTML code to ensure the `web` image is rebuilt.*
```bash
docker-compose up --build -d
```

**Stop the stack (stops all running containers without destroying data):**
```bash
docker-compose stop
```

**Tear down the stack (stops and removes containers, networks, and images):**
```bash
docker-compose down
```
*Tip: To completely wipe the database and start fresh, remove the named volumes by appending `-v`.*
```bash
docker-compose down -v
```

## 2. Viewing Logs

**View logs for the `web` service (Flask application):**
```bash
docker-compose logs -f web
```
*(The `-f` flag "follows" the logs in real-time. Press `Ctrl+C` to exit).*

**View logs for the database (`db`):**
```bash
docker-compose logs -f db
```

**View logs for Fluentd (useful if logs aren't appearing in Elasticsearch):**
```bash
docker-compose logs -f fluentd
```

## 3. Interacting with the Containers

**Open an interactive shell inside the Flask `web` container:**
```bash
docker-compose exec web /bin/bash
```

**Access the PostgreSQL database via `psql`:**
```bash
docker-compose exec db psql -U postgres -d ngo_db
```
*(You can run SQL queries directly from here. Type `\q` to exit).*

**Check if Elasticsearch is receiving data:**
```bash
curl -X GET "localhost:9200/_cat/indices?v"
```

## 4. Container Maintenance & Pruning

**List all running services and their statuses:**
```bash
docker-compose ps
```

**Restart a specific service (e.g., if the `web` container crashes):**
```bash
docker-compose restart web
```

**Clean up unused Docker resources (free up disk space):**
```bash
docker system prune -a --volumes
```
*(Warning: This will delete ALL stopped containers, unused networks, and dangling images on your machine).*

## 5. Important Ports Reference
When accessing the services locally, use these ports in your browser or API client:
- **Web Application**: [http://localhost:5001](http://localhost:5001)
- **Grafana (Dashboards)**: [http://localhost:3000](http://localhost:3000) (Default login: `admin` / `admin`)
- **Jaeger (Tracing UI)**: [http://localhost:16686](http://localhost:16686)
- **Prometheus (Metrics UI)**: [http://localhost:9090](http://localhost:9090)
- **PostgreSQL**: `localhost:5432`
