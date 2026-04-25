import os
import logging
from flask import Flask
from models import db
from pythonjsonlogger import jsonlogger

# Monitoring Imports
from prometheus_flask_exporter import PrometheusMetrics
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

app = Flask(__name__)

import sys

# --- Setup Structured Logging ---
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logHandler = logging.StreamHandler(sys.stdout)
formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(levelname)s %(name)s %(message)s'
)
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
# Ensure werkzeug logger also uses JSON if possible, or at least doesn't duplicate
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# --- Setup Tracing ---
resource = Resource(attributes={
    SERVICE_NAME: "ngo-management-app"
})
trace.set_tracer_provider(TracerProvider(resource=resource))
jaeger_host = os.environ.get('JAEGER_HOST', 'jaeger')
otlp_exporter = OTLPSpanExporter(
    endpoint=f"http://{jaeger_host}:4317",
    insecure=True
)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)

# Instrument Flask
FlaskInstrumentor().instrument_app(app)

# --- Setup Metrics ---
metrics = PrometheusMetrics(app)
metrics.info('app_info', 'Application info', version='1.0.0')

app.secret_key = os.environ.get('SECRET_KEY', 'default_static_secret_key_for_dev')

# --- Configuration ---
from dotenv import load_dotenv
load_dotenv()

base_dir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 
    'sqlite:///' + os.path.join(base_dir, 'ngo_database.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()
    SQLAlchemyInstrumentor().instrument(engine=db.engine)




# --- Register Routes ---
from routes import register_all_routes
register_all_routes(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)