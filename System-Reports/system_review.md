# System Review & Architecture Report

## 1. Bug and Testing Report

### Identified Bugs and Potential Issues
1. **Database Race Condition on Startup**: In `docker-compose.yml`, the `web` service depends on `db` (`postgres`). However, `depends_on` only waits for the container to start, not for the database to be fully ready to accept connections. Since `app.py` runs `db.create_all()` immediately upon startup, the app may crash with a connection refused error if Postgres takes too long to initialize. 
   - *Fix*: Add a `healthcheck` to the `db` service and use `depends_on: db: condition: service_healthy` in the `web` service.
2. **Gunicorn & OpenTelemetry Tracing Issue**: In the `Dockerfile`, Gunicorn is started with `-w 4`. Since `app.py` initializes the `BatchSpanProcessor` (which spawns a background thread) at the module level, the background thread may not survive the `fork()` when Gunicorn creates its worker processes. This can result in traces not being exported.
   - *Fix*: Use the `opentelemetry-instrument` CLI command in the Dockerfile `CMD` or configure a Gunicorn `post_worker_init` hook to initialize the tracer provider.
3. **Concurrency in Donations**: In `routes/donor.py`, the `campaign.raised_amount += amount` logic does not use database row locking (e.g., `with_for_update()`). In a high-traffic scenario where multiple donations happen concurrently for the same campaign, this could lead to a race condition where some donations are not correctly added to the total.
4. **Fluentd Logging Driver Address**: The Docker Compose `web` service configures the Fluentd logging driver with `fluentd-address: localhost:24224`. Depending on the host OS (especially Docker Desktop on Mac/Windows), the Docker daemon might not resolve `localhost` correctly to the host's published port. 
   - *Fix*: It's often safer to use `127.0.0.1:24224` or `host.docker.internal:24224`.
5. **Security/Credentials in Plain Text**: `docker-compose.yml` contains hardcoded passwords for PostgreSQL, Grafana, and Elasticsearch. Elasticsearch also has `xpack.security.enabled=false`. This is acceptable for local development but must be secured via `.env` files and Docker secrets for production.
6. **OpenTelemetry Thrift Exporter**: The code uses `JaegerExporter` (Thrift) which is considered deprecated in recent OpenTelemetry Python versions in favor of OTLP (`opentelemetry-exporter-otlp`). It will still work with the `jaegertracing/all-in-one` image, but updating to OTLP is highly recommended.

### Testing Report
- **Unit/Integration Tests**: There is currently no `tests/` directory or testing framework (like `pytest`) set up. Automated testing coverage is currently at 0%.
- **Manual Testing Verification**: The routes are properly mapped, form data is validated safely using SQLAlchemy, and SQL Injection risks are mitigated via the ORM. The dummy data generation route (`/admin/generate_dummy_data`) serves as a robust manual integration test.

---

## 2. Containers Layout & Architecture

The application operates as a multi-container Docker deployment, heavily focused on a modern observability stack.

### Container Layout
- **`web` (Flask Application)**: The core Python/Flask backend served by Gunicorn on port `5001`. It connects to Postgres and pushes traces/metrics.
- **`db` (PostgreSQL 15)**: The primary relational database holding users, campaigns, and donations. Data is persisted via a Docker volume (`postgres_data`).
- **`fluentd`**: A unified logging layer that captures standard output from the `web` container via Docker's native Fluentd logging driver, processes it, and forwards it to Elasticsearch.
- **`elasticsearch`**: A single-node search engine used to index and store the application logs captured by Fluentd.
- **`prometheus`**: Scrapes HTTP application metrics natively exposed by the Flask app's `/metrics` endpoint (provided by `prometheus-flask-exporter`).
- **`grafana`**: A visualization dashboard that connects to Prometheus to render graphs of application performance, traffic, and database health.
- **`jaeger`**: A distributed tracing system. The Flask app sends OpenTelemetry trace spans directly to Jaeger to trace request flows and database query latencies.

---

## 3. System Architecture & Tech Stack

### High-Level Architecture
The system follows a classic **Client-Server monolithic architecture** wrapped within a **Microservices Observability Framework**:
1. **Client Layer**: Standard Web Browser interacting via HTTP/POST/GET requests.
2. **Application Layer (Flask)**: Processes business logic, handles user sessions, and structures data via SQLAlchemy ORM.
3. **Data Layer (Postgres)**: Ensures ACID compliance for transactional donation data.
4. **Telemetry/Observability Layer**: Running entirely decoupled from the business logic, extracting logs, metrics, and traces for health monitoring.

### Tech Stack Used
- **Backend Framework**: Python 3.11, Flask 3.0, Werkzeug
- **Database & ORM**: PostgreSQL 15, Flask-SQLAlchemy 3.1 (with `psycopg2-binary`)
- **Web Server**: Gunicorn (WSGI)
- **Frontend**: HTML5, CSS3, Jinja2 Templates (Server-Side Rendering)
- **Logging**: Python JSON Logger, Fluentd, Elasticsearch
- **Metrics**: Prometheus Flask Exporter, Prometheus, Grafana
- **Tracing**: OpenTelemetry (API/SDK), Jaeger
- **Infrastructure**: Docker, Docker Compose
