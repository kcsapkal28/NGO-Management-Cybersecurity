# Cybersecurity NGO Management - System Knowledge Base

This document serves as a comprehensive guide to the architecture, environment, and configuration of the Cybersecurity NGO Management platform. It provides necessary context for agents or developers to thrive within this repository.

## 1. System Architecture
The application follows a modular, containerized architecture:
- **Web Application (`web`)**: Built on Python/Flask. It handles business logic, route serving, and interacts with the database.
- **Database Layer (`db`)**: Uses PostgreSQL, interfaced by SQLAlchemy (ORM).
- **Observability Stack**: A fully integrated monitoring layer using the "LGTM" philosophy (Logs, Metrics, Traces), substituting Loki with Fluentd+Elasticsearch.
  - **Metrics**: Instrumentated using `PrometheusFlaskExporter`.
  - **Tracing**: Instrumentated using OpenTelemetry (Flask and SQLAlchemy) sending to Jaeger over OTLP.
  - **Logging**: Configured via `pythonjsonlogger` for structured JSON logs, exported out of Docker using the Fluentd logging driver.

## 2. Routes and DB Models
### Routes Modules (located in `routes/` directory):
- `public.py`: Handles public-facing landing pages and general information.
- `auth.py`: Manages user authentication (registration, login, session management).
- `donor.py`: Provides donor-specific dashboards and actions.
- `admin.py`: Administrator panel for campaign creation, donation overview, user management, and dummy data generation.

### Database Models (`models.py`):
- **`User`**: `id`, `username`, `email`, `password`, `phone`, `is_admin`, `created_at`.
- **`Campaign`**: `id`, `title`, `category`, `image_url`, `description`, `goal_amount`, `raised_amount`, `is_active`, `created_at`. Includes a dynamic `@property` for `progress_percentage`.
- **`Donation`**: `id`, `user_id` (ForeignKey), `campaign_id` (ForeignKey), `full_name`, `email`, `amount`, `donation_type`, `payment_method`, `transaction_id`, `status`, `created_at`. Relates back to User and Campaign models via dynamic relationships.

## 3. Monitoring Setup & Services
| Service | Image/Build | Port(s) | Role & Description |
|---|---|---|---|
| **web** | Local build (`.`) | `5001` | Main Flask Application. Routes logs to Fluentd via Docker driver. |
| **db** | `postgres:15-alpine` | `5432` | PostgreSQL Database for persistent relational storage. |
| **elasticsearch** | `elasticsearch:8.10.2` | `9200` | Central data sink for logs (from Fluentd) and traces (from Jaeger). Configured as a single node. |
| **fluentd** | `./monitoring/fluentd` | `24224` | Log aggregator. Formats and forwards incoming logs to Elasticsearch. |
| **prometheus** | `prom/prometheus:latest` | `9090` | Metrics scraper. Periodically pulls metrics from the `web` container. |
| **jaeger** | `jaegertracing/all-in-one` | `16686` (UI), `4317` (OTLP) | Distributed tracing system. Stores spans natively in Elasticsearch. |
| **grafana** | `grafana/grafana:latest` | `3000` | Central visualization dashboard. Connects to Prometheus, Jaeger, and ES. |

## 4. Information Flow (Logs, Metrics, Traces)
- **Logs Flow**: The Flask App uses `pythonjsonlogger` to emit structured JSON to stdout/stderr. Docker's logging driver (`fluentd-address: "localhost:24224"`) captures this output and forwards it to the **Fluentd** container. Fluentd buffers the logs and pushes them into **Elasticsearch** under the index pattern `fluentd-*`.
- **Metrics Flow**: The `web` application exposes an endpoint (`/metrics`) using `prometheus_flask_exporter`. The **Prometheus** container is configured (`prometheus.yml`) to scrape `web:5001` every 15 seconds. **Grafana** then queries Prometheus to visualize system and application performance.
- **Traces Flow**: **OpenTelemetry** auto-instruments Flask requests and SQLAlchemy queries inside the `web` app. It batches the spans and exports them via grpc/OTLP to **Jaeger** (`JAEGER_HOST:4317`). Jaeger is configured with `SPAN_STORAGE_TYPE=elasticsearch` and writes trace data directly to **Elasticsearch**. Grafana can visualize these traces by querying the Jaeger data source.

## 5. Important Configurations
- **Docker Compose Orchestration (`docker-compose.yml`)**:
  - Employs strict startup conditions utilizing `healthcheck` and `depends_on`. For example, `web` waits for `fluentd` and `db`; `fluentd` and `jaeger` wait for `elasticsearch`.
  - Service names act as hostnames inside the Docker network.
- **Datasources (`monitoring/grafana/provisioning/datasources/datasources.yml`)**:
  - `Prometheus` -> `http://prometheus:9090`
  - `Jaeger` -> `http://jaeger:16686`
  - `Elasticsearch` -> `http://elasticsearch:9200` (index: `fluentd-*`, timeField: `@timestamp`)
- **Fluentd (`fluent.conf`)**:
  - Matches all incoming tags (`<match **>`), sets `logstash_format true`, and configures the `logstash_dateformat` as `%Y.%m.%d` to ensure Grafana can seamlessly parse indices.

## 6. System Context & Environment Variables
- **Application Start**: `app.py` initializes the app, configures JSON logging, sets up OpenTelemetry `TracerProvider`, wraps the SQLAlchemy engine (`SQLAlchemyInstrumentor`), and creates database tables dynamically if they don't exist.
- **Key Variables**:
  - `SERVICE_NAME`: "ngo-management-app" (Critical for Jaeger/Grafana trace queries).
  - `DATABASE_URL`: `postgresql://postgres:postgres@db:5432/ngo_db`
  - `JAEGER_HOST`: `jaeger`
- **Known Application Endpoints**:
  - Web UI: `http://localhost:5001`
  - Dummy Log Generator: `http://localhost:5001/test-logs` (generates INFO, WARNING, ERROR, CRITICAL).
  - Admin Setup: `http://localhost:5001/admin/generate_dummy_data` (populates database via `Faker`).

## 7. Project Directory Structure
This map helps in locating specific modules and configurations within the repository.

```text
Cybersecurity-NGO-Management/
├── app.py                 # Application entry point & observability initialization
├── models.py              # SQLAlchemy database models (User, Campaign, Donation)
├── utils.py               # Utility decorators (login_required, admin_required)
├── routes/                # Modular route handlers
│   ├── __init__.py        # Route registration logic
│   ├── admin.py           # Admin panel & data generation routes
│   ├── auth.py            # Authentication & session routes
│   ├── donor.py           # Donor dashboard routes
│   └── public.py          # Landing page & public info routes
├── monitoring/            # Observability stack configuration
│   ├── fluentd/           # Fluentd Dockerfile & fluent.conf
│   ├── prometheus/        # Prometheus scraping configuration (prometheus.yml)
│   └── grafana/           # Grafana provisioning (datasources & dashboards)
├── System-Reports/        # Documentation & Architecture guides
│   ├── System_Knowledge_Base.md
│   └── ... (Other technical guides)
├── templates/             # Jinja2 HTML templates
├── static/                # Static assets (CSS, images)
├── Dockerfile             # Web app containerization
├── docker-compose.yml     # Multi-container orchestration
└── requirements.txt       # Python dependencies
```

