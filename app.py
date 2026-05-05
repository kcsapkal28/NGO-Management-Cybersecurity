import os
import logging
from flask import Flask
from extensions import csrf, limiter
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

# --- Configuration ---
from dotenv import load_dotenv
load_dotenv()

secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable is required. "
        "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
    )
app.secret_key = secret_key

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true',
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
    WTF_CSRF_TIME_LIMIT=None,
)

base_dir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'sqlite:///' + os.path.join(base_dir, 'ngo_database.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

csrf.init_app(app)
limiter.init_app(app)

db.init_app(app)

with app.app_context():
    db.create_all()
    SQLAlchemyInstrumentor().instrument(engine=db.engine)




# --- Register Routes ---
from routes import register_all_routes
register_all_routes(app)

# --- CLI: promote-admin ---
import click
from models import User

@app.cli.command("promote-admin")
@click.argument("email")
def promote_admin(email):
    """Grant admin to the user with the given email."""
    user = User.query.filter_by(email=email.lower().strip()).first()
    if not user:
        click.echo(f"No user found with email {email}")
        raise SystemExit(1)
    user.is_admin = True
    db.session.commit()
    click.echo(f"Promoted {user.email} to admin.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)