# Elasticsearch: Management & Operations Guide

This guide details the setup, working mechanism, and operational procedures for Elasticsearch within the Cybersecurity NGO Management platform.

---

## 1. Setup & Configuration

Elasticsearch is deployed as a single-node container for centralized log storage.

### Service Configuration (`docker-compose.yml`)
```yaml
elasticsearch:
  image: docker.elastic.co/elasticsearch/elasticsearch:8.10.2
  environment:
    - discovery.type=single-node
    - xpack.security.enabled=false # Disabled for development simplicity
  ports:
    - "9200:9200" # REST API port
```

### Key Parameters:
*   **Version**: 8.10.2 (Matches Fluentd plugin compatibility).
*   **Port 9200**: The primary endpoint for querying and management.
*   **Single-node**: Bypasses cluster bootstrapping requirements.

---

## 2. How it Works (The Logging Pipeline)

Elasticsearch acts as the "Storage" layer in our EFK (Elasticsearch, Fluentd, Kibana/Grafana) stack.

1.  **Generation**: The Flask app (`web`) writes logs to stdout/stderr.
2.  **Collection**: The Docker **Fluentd Log Driver** captures these logs and forwards them to the `fluentd` container on port `24224`.
3.  **Ingestion**: Fluentd processes the logs and sends them to Elasticsearch using the `fluent-plugin-elasticsearch`.
4.  **Indexing**: Elasticsearch stores logs in indices named `fluentd-YYYYMMDD` (e.g., `fluentd-20260422`).
5.  **Visualization**: Grafana queries the Elasticsearch REST API to display logs in dashboards.

---

## 3. Essential Commands

### Service Management
| Task | Command |
| :--- | :--- |
| **Start ES** | `docker-compose up -d elasticsearch` |
| **Stop ES** | `docker-compose stop elasticsearch` |
| **Check Health** | `curl -X GET "localhost:9200/_cluster/health?pretty"` |
| **View Logs** | `docker-compose logs -f elasticsearch` |

### Index Management
| Task | Command |
| :--- | :--- |
| **List all Indices** | `curl -X GET "localhost:9200/_cat/indices?v"` |
| **Check Index Size** | `curl -X GET "localhost:9200/_cat/indices/fluentd-*?v&s=store.size:desc"` |
| **Delete an Index** | `curl -X DELETE "localhost:9200/fluentd-20260420"` |

### Data Querying (Search)
| Task | Command |
| :--- | :--- |
| **Search All Logs** | `curl -X GET "localhost:9200/fluentd-*/_search?pretty"` |
| **Search for "Error"** | `curl -X GET "localhost:9200/fluentd-*/_search?q=log:error&pretty"` |
| **Get Document Count** | `curl -X GET "localhost:9200/fluentd-*/_count?pretty"` |

---

## 4. Runbook & Troubleshooting

### Issue: Elasticsearch fails to start (Exit Code 137)
*   **Cause**: Out of Memory (OOM). Elasticsearch is resource-intensive and requires at least 2GB of RAM.
*   **Fix**: 
    1. Increase Docker Desktop's memory limit to 4GB+.
    2. Add heap limits in `docker-compose.yml`:
       ```yaml
       environment:
         - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
       ```

### Issue: "Disk Watermark" Warnings (Read-Only Mode)
*   **Cause**: If your local disk is >90% full, ES will block writes to protect itself.
*   **Fix**: 
    1. Free up disk space.
    2. Manually unlock the indices:
       ```bash
       curl -X PUT "localhost:9200/_all/_settings" -H 'Content-Type: application/json' -d'{"index.blocks.read_only_allow_delete": null}'
       ```

### Issue: Logs not appearing in ES
*   **Check Fluentd**: Run `docker-compose logs fluentd`. If you see "connection refused," ES is either down or booting up.
*   **Check Docker Driver**: Ensure the `web` container shows `Logging: fluentd` when running `docker inspect <container_id>`.

---

## 5. Security Note
In this setup, `xpack.security.enabled` is set to `false`. This means **no password is required** to access port 9200. 
> [!CAUTION]
> Never expose port 9200 to the public internet without enabling security and setting up `ELASTIC_PASSWORD`.
