import os
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.urandom(24)
base_dir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(base_dir, 'ngo_database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    goal_amount = db.Column(db.Float, nullable=False)
    raised_amount = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Donation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Nullable for Guest Checkout
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    donation_type = db.Column(db.String(50), default='One-time') # One-time, Monthly, Yearly
    payment_method = db.Column(db.String(50), nullable=False) # Card, UPI, NetBanking
    transaction_id = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(20), default='Pending') # Pending, Completed, Failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships for easy access in templates
    user = db.relationship('User', backref='donations')
    campaign = db.relationship('Campaign', backref='donations')

with app.app_context():
    db.create_all()

# --- Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or not session.get('is_admin'):
            flash('Administrator access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- Public & Auth Routes ---
@app.route('/')
def index():
    campaigns = Campaign.query.filter_by(is_active=True).order_by(Campaign.created_at.desc()).limit(3).all()
    return render_template('index.html', campaigns=campaigns)

@app.route('/auth', methods=['GET'])
def auth():
    return render_template('login_signup.html')

@app.route('/signup', methods=['POST'])
def signup():
    username, email, password = request.form.get('username'), request.form.get('email'), request.form.get('password')
    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash('Username or Email already registered.', 'danger')
        return redirect(url_for('auth'))
    
    # First user to register automatically becomes an Admin
    is_first_user = User.query.count() == 0
    new_user = User(username=username, email=email, password=generate_password_hash(password), is_admin=is_first_user)
    db.session.add(new_user)
    db.session.commit()
    flash('Account created! Please log in.', 'success')
    return redirect(url_for('auth'))

@app.route('/login', methods=['POST'])
def login():
    user = User.query.filter_by(email=request.form.get('email')).first()
    if user and check_password_hash(user.password, request.form.get('password')):
        session['user_id'] = user.id
        session['username'] = user.username
        session['is_admin'] = user.is_admin
        flash(f'Welcome back, {user.username}!', 'success')
        return redirect(url_for('admin_dashboard' if user.is_admin else 'donor_dashboard'))
    flash('Invalid email or password.', 'danger')
    return redirect(url_for('auth'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('index'))

# --- Donor Routes ---
@app.route('/campaigns')
def campaigns():
    all_campaigns = Campaign.query.filter_by(is_active=True).all()
    return render_template('campaigns.html', campaigns=all_campaigns)

@app.route('/donate', methods=['GET'])
def donate():
    user_data = User.query.get(session['user_id']) if 'user_id' in session else None
    campaigns = Campaign.query.filter_by(is_active=True).all()
    selected_cid = request.args.get('campaign_id')
    return render_template('donate.html', user=user_data, campaigns=campaigns, selected_campaign=selected_cid)

@app.route('/api/process_payment', methods=['POST'])
def process_payment():
    data = request.get_json()
    try:
        amount = float(data.get('amount'))
        campaign_id = data.get('campaign_id')
        campaign_id = int(campaign_id) if campaign_id else None

        new_donation = Donation(
            user_id=session.get('user_id'), # Null if Guest checkout
            campaign_id=campaign_id,
            full_name=data.get('full_name'),
            email=data.get('email'),
            amount=amount,
            donation_type=data.get('donation_type'),
            payment_method=data.get('payment_method'),
            transaction_id="TXN" + os.urandom(6).hex().upper(),
            status='Completed' # Mock instant success
        )
        db.session.add(new_donation)
        
        # Update Campaign Progress
        if campaign_id:
            campaign = Campaign.query.get(campaign_id)
            if campaign: campaign.raised_amount += amount
                
        db.session.commit()
        return jsonify({
            'success': True,
            'receipt': {
                'name': new_donation.full_name,
                'amount': new_donation.amount,
                'txid': new_donation.transaction_id,
                'type': new_donation.donation_type
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/dashboard')
@login_required
def donor_dashboard():
    user = User.query.get(session['user_id'])
    donations = Donation.query.filter_by(user_id=user.id).order_by(Donation.created_at.desc()).all()
    return render_template('donor_dashboard.html', user=user, donations=donations)

# --- Admin Routes ---
@app.route('/admin')
@admin_required
def admin_dashboard():
    total_raised = db.session.query(db.func.sum(Donation.amount)).filter_by(status='Completed').scalar() or 0.0
    active_donors = db.session.query(Donation.email).distinct().count()
    recent_transactions = Donation.query.order_by(Donation.created_at.desc()).limit(5).all()
    active_campaigns = Campaign.query.filter_by(is_active=True).count()
    return render_template('admin_dashboard.html', total_raised=total_raised, active_donors=active_donors, 
                           recent_transactions=recent_transactions, active_campaigns=active_campaigns)

@app.route('/admin/campaigns', methods=['GET', 'POST'])
@admin_required
def admin_campaigns():
    if request.method == 'POST':
        new_campaign = Campaign(
            title=request.form.get('title'),
            description=request.form.get('description'),
            goal_amount=float(request.form.get('goal_amount'))
        )
        db.session.add(new_campaign)
        db.session.commit()
        flash('Campaign created!', 'success')
        return redirect(url_for('admin_campaigns'))
    campaigns = Campaign.query.all()
    return render_template('admin_campaigns.html', campaigns=campaigns)

@app.route('/admin/campaigns/<int:id>/close')
@admin_required
def close_campaign(id):
    campaign = Campaign.query.get_or_404(id)
    campaign.is_active = False
    db.session.commit()
    flash('Campaign closed.', 'info')
    return redirect(url_for('admin_campaigns'))

@app.route('/admin/donors')
@admin_required
def admin_donors():
    users = User.query.filter_by(is_admin=False).all()
    return render_template('admin_donors.html', users=users)

@app.route('/admin/transactions')
@admin_required
def admin_transactions():
    transactions = Donation.query.order_by(Donation.created_at.desc()).all()
    return render_template('admin_transactions.html', transactions=transactions)

if __name__ == '__main__':
    app.run(debug=True)