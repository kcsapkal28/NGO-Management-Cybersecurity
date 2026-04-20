from urllib.parse import urlparse
from sqlalchemy.exc import IntegrityError
from flask import render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User

def init_auth_routes(app):
    @app.route('/auth', methods=['GET'])
    def auth():
        return render_template('login_signup.html')

    @app.route('/signup', methods=['POST'])
    def signup():
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        target = request.referrer
        if not target or urlparse(target).netloc and urlparse(target).netloc != request.host:
            target = url_for('index')
            
        if not username or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(target)
            
        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('Username or Email already registered.', 'danger')
            return redirect(target)
        
        is_first_user = User.query.count() == 0
        new_user = User(username=username, email=email, password=generate_password_hash(password), is_admin=is_first_user)
        db.session.add(new_user)
        try:
            db.session.commit()
            flash('Account created! Please log in.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Database error during registration.', 'danger')
            
        return redirect(target)

    @app.route('/login', methods=['POST'])
    def login():
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        target = request.referrer
        if not target or urlparse(target).netloc and urlparse(target).netloc != request.host:
            target = url_for('index')

        if not email or not password:
            flash('Email and password are required.', 'danger')
            return redirect(target)

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
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
