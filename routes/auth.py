from sqlalchemy.exc import IntegrityError
from flask import render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import limiter
from models import db, User

MIN_PASSWORD_LEN = 8


def _safe_redirect_target():
    """Return a same-origin path to redirect to, or the index URL."""
    target = request.referrer or ''
    if target.startswith('/') and not target.startswith('//'):
        return target
    if target:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(target)
            if parsed.scheme in ('http', 'https') and parsed.netloc == request.host:
                return parsed.path or url_for('index')
        except ValueError:
            pass
    return url_for('index')


def init_auth_routes(app):
    @app.route('/auth', methods=['GET'])
    def auth():
        return render_template('login_signup.html')

    @app.route('/signup', methods=['POST'])
    @limiter.limit("5 per minute; 20 per hour")
    def signup():
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        target = _safe_redirect_target()

        if not username or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(target)
        if len(password) < MIN_PASSWORD_LEN:
            flash(f'Password must be at least {MIN_PASSWORD_LEN} characters.', 'danger')
            return redirect(target)

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('If that account is available you will receive a confirmation email.', 'info')
            return redirect(target)

        new_user = User(username=username, email=email, password=generate_password_hash(password), is_admin=False)
        db.session.add(new_user)
        try:
            db.session.commit()
            flash('Account created! Please log in.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Database error during registration.', 'danger')

        return redirect(target)

    @app.route('/login', methods=['POST'])
    @limiter.limit("10 per minute; 100 per hour")
    def login():
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        target = _safe_redirect_target()

        if not email or not password:
            flash('Email and password are required.', 'danger')
            return redirect(target)

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session.clear()
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('admin_dashboard' if user.is_admin else 'donor_dashboard'))

        flash('Invalid email or password.', 'danger')
        return redirect(target)

    @app.route('/logout')
    def logout():
        session.clear()
        flash('Logged out successfully.', 'info')
        return redirect(url_for('index'))
