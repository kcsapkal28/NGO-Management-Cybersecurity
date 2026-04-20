import os
import random
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from faker import Faker # For Dummy Data

from models import db, User, Campaign, Donation

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Configuration ---
base_dir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(base_dir, 'ngo_database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

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

@app.route('/about')
def about():
    fake = Faker()
    about_data = {
        'mission': fake.paragraph(nb_sentences=5),
        'vision': fake.paragraph(nb_sentences=4),
        'history': fake.paragraphs(nb=3),
        'team': [{'name': fake.name(), 'role': fake.job(), 'image': f"https://i.pravatar.cc/150?u={fake.uuid4()}"} for _ in range(4)]
    }
    return render_template('about.html', data=about_data)

@app.route('/blogs')
def blogs():
    fake = Faker()
    posts = []
    for _ in range(6):
        posts.append({
            'title': fake.catch_phrase(),
            'excerpt': fake.paragraph(nb_sentences=2),
            'author': fake.name(),
            'date': fake.date_this_year().strftime('%b %d, %Y'),
            'image': f"https://picsum.photos/seed/{fake.uuid4()}/400/250"
        })
    return render_template('blogs.html', blogs=posts)

@app.route('/auth', methods=['GET'])
def auth():
    return render_template('login_signup.html')

@app.route('/signup', methods=['POST'])
def signup():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    
    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash('Username or Email already registered.', 'danger')
        return redirect(url_for('auth'))
    
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
    all_campaigns = Campaign.query.filter_by(is_active=True).order_by(Campaign.created_at.desc()).all()
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
            user_id=session.get('user_id'),
            campaign_id=campaign_id,
            full_name=data.get('full_name'),
            email=data.get('email'),
            amount=amount,
            donation_type=data.get('donation_type'),
            payment_method=data.get('payment_method'),
            transaction_id="TXN" + os.urandom(8).hex().upper(),
            status='Completed' 
        )
        db.session.add(new_donation)
        
        if campaign_id:
            campaign = Campaign.query.get(campaign_id)
            if campaign: campaign.raised_amount += amount
                
        db.session.commit()
        return jsonify({'success': True, 'receipt': {'name': new_donation.full_name, 'amount': new_donation.amount, 'txid': new_donation.transaction_id, 'type': new_donation.donation_type}})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/dashboard')
@login_required
def donor_dashboard():
    user = User.query.get(session['user_id'])
    donations = user.donations.order_by(Donation.created_at.desc()).all()
    return render_template('donor_dashboard.html', user=user, donations=donations)

# --- Admin Routes ---
@app.route('/admin')
@admin_required
def admin_dashboard():
    total_raised = db.session.query(db.func.sum(Donation.amount)).filter_by(status='Completed').scalar() or 0.0
    active_donors = db.session.query(Donation.email).distinct().count()
    active_campaigns = Campaign.query.filter_by(is_active=True).count()
    recent_transactions = Donation.query.order_by(Donation.created_at.desc()).limit(5).all()
    
    # Optimization: Calculate Top Donors Leaderboard natively in SQL
    top_donors = db.session.query(
        Donation.full_name, 
        db.func.sum(Donation.amount).label('total_donated')
    ).group_by(Donation.email).order_by(db.desc('total_donated')).limit(5).all()

    return render_template('admin_dashboard.html', 
                           total_raised=total_raised, 
                           active_donors=active_donors, 
                           recent_transactions=recent_transactions, 
                           active_campaigns=active_campaigns,
                           top_donors=top_donors)

@app.route('/admin/campaigns', methods=['GET', 'POST'])
@admin_required
def admin_campaigns():
    if request.method == 'POST':
        new_campaign = Campaign(
            title=request.form.get('title'),
            category=request.form.get('category'),
            description=request.form.get('description'),
            goal_amount=float(request.form.get('goal_amount'))
        )
        db.session.add(new_campaign)
        db.session.commit()
        flash('Campaign created successfully!', 'success')
        return redirect(url_for('admin_campaigns'))
    
    # Pagination: Display 10 campaigns per page
    page = request.args.get('page', 1, type=int)
    campaigns = Campaign.query.order_by(Campaign.created_at.desc()).paginate(page=page, per_page=10)
    
    return render_template('admin_campaigns.html', campaigns=campaigns.items) # .items extracts the list to keep frontend working

@app.route('/admin/donors')
@admin_required
def admin_donors():
    page = request.args.get('page', 1, type=int)
    users = User.query.filter_by(is_admin=False).order_by(User.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('admin_donors.html', users=users.items)

@app.route('/admin/transactions')
@admin_required
def admin_transactions():
    page = request.args.get('page', 1, type=int)
    transactions = Donation.query.order_by(Donation.created_at.desc()).paginate(page=page, per_page=50)
    return render_template('admin_transactions.html', transactions=transactions.items)

# --- DUMMY DATA GENERATOR (New Feature) ---
@app.route('/admin/generate_dummy_data')
@admin_required
def generate_dummy_data():
    fake = Faker()
    
    # 1. Generate 10 Campaigns
    categories = ['Health', 'Education', 'Disaster Relief', 'Environment', 'Animal Welfare']
    campaigns = []
    for _ in range(10):
        c = Campaign(
            title=fake.catch_phrase(),
            category=random.choice(categories),
            description=fake.paragraph(nb_sentences=5),
            goal_amount=round(random.uniform(5000, 50000), 2),
            raised_amount=0.0,
            image_url=f"https://picsum.photos/seed/{random.randint(1,1000)}/600/400"
        )
        db.session.add(c)
        campaigns.append(c)
    db.session.commit() # Commit campaigns to get their IDs

    # 2. Generate 50 Users
    users = []
    for _ in range(50):
        u = User(
            username=fake.user_name() + str(random.randint(10,99)),
            email=fake.email(),
            password=generate_password_hash('password123'),
            phone=fake.phone_number(),
            created_at=fake.date_time_between(start_date='-1y', end_date='now')
        )
        db.session.add(u)
        users.append(u)
    db.session.commit()

    # 3. Generate 300 Donations
    methods = ['Credit Card', 'UPI', 'NetBanking', 'Wallet']
    types = ['One-time', 'Monthly', 'Yearly']
    
    for _ in range(300):
        donor = random.choice(users)
        campaign = random.choice(campaigns)
        amount = round(random.uniform(10, 1000), 2)
        
        d = Donation(
            user_id=donor.id,
            campaign_id=campaign.id,
            full_name=fake.name(),
            email=donor.email,
            amount=amount,
            donation_type=random.choice(types),
            payment_method=random.choice(methods),
            transaction_id="TXN" + fake.hexify(text='^^^^^^^^').upper(),
            status='Completed',
            created_at=fake.date_time_between(start_date=campaign.created_at, end_date='now')
        )
        db.session.add(d)
        campaign.raised_amount += amount # Update Campaign Total

    db.session.commit()
    flash('Successfully generated 10 campaigns, 50 users, and 300 donations!', 'success')
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)