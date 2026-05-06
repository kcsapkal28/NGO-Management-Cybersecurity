import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

from extensions import csrf, limiter
from models import db
import observability

load_dotenv()

app = Flask(__name__)

# Trust X-Forwarded-* from one upstream hop (ngrok / kubernetes ingress /
# any reverse proxy). Without this:
#   - request.scheme is "http" while Referer is "https" → Flask-WTF rejects
#     POSTs with 400 BAD REQUEST due to WTF_CSRF_SSL_STRICT (the donation
#     form failure surfaces as "An unexpected error occurred" in the JS)
#   - url_for(..., _external=True) builds http:// URLs even when the user
#     came in via https://
# Increase x_for / x_host counts if you stack multiple proxies (e.g. CDN
# in front of an ingress).
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

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
    'sqlite:///' + os.path.join(base_dir, 'ngo_database.db'),
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# pool_pre_ping issues a cheap SELECT 1 before checking out a connection.
# Without it, a Postgres restart leaves dead sockets in the pool and the
# next ~10 requests fail with "server closed the connection unexpectedly"
# until those slots cycle out. pool_recycle caps connection age at 1h.
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 3600,
}

csrf.init_app(app)
limiter.init_app(app)
db.init_app(app)

with app.app_context():
    db.create_all()
    observability.setup(app, db_engine=db.engine)

# Routes are registered after observability so the request_id hook runs
# before any blueprint-level before_request handlers (e.g. system_test gate).
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
