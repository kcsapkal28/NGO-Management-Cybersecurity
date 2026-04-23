import random
from faker import Faker
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
from flask import render_template, request, redirect, url_for, flash
from models import db, User, Campaign, Donation
from utils import admin_required

def init_admin_routes(app):
    @app.route('/admin')
    @admin_required
    def admin_dashboard():
        total_raised = db.session.query(db.func.sum(Donation.amount)).filter_by(status='Completed').scalar() or 0.0
        active_donors = db.session.query(Donation.email).distinct().count()
        active_campaigns = Campaign.query.filter_by(is_active=True).count()
        recent_transactions = Donation.query.order_by(Donation.created_at.desc()).limit(5).all()
        
        top_donors = db.session.query(
            Donation.full_name, 
            db.func.sum(Donation.amount).label('total_donated')
        ).group_by(Donation.email, Donation.full_name).order_by(db.desc('total_donated')).limit(5).all()

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
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            
            if not title or not description:
                flash('Title and description are required.', 'danger')
                return redirect(url_for('admin_campaigns'))
                
            try:
                goal_amount = float(request.form.get('goal_amount', 0))
                if goal_amount <= 0:
                    raise ValueError("Goal amount must be positive.")
            except ValueError:
                flash('Invalid goal amount. Must be a positive number.', 'danger')
                return redirect(url_for('admin_campaigns'))

            new_campaign = Campaign(
                title=title,
                category=request.form.get('category', 'General'),
                description=description,
                goal_amount=round(goal_amount, 2)
            )
            db.session.add(new_campaign)
            db.session.commit()
            flash('Campaign created successfully!', 'success')
            return redirect(url_for('admin_campaigns'))
        
        page = request.args.get('page', 1, type=int)
        campaigns = Campaign.query.order_by(Campaign.created_at.desc()).paginate(page=page, per_page=10)
        return render_template('admin_campaigns.html', campaigns=campaigns.items, pagination=campaigns)

    @app.route('/admin/campaigns/<int:id>/close')
    @admin_required
    def close_campaign(id):
        campaign = Campaign.query.get(id)
        if campaign:
            campaign.is_active = False
            db.session.commit()
            flash('Campaign closed successfully!', 'success')
        else:
            flash('Campaign not found.', 'danger')
        return redirect(url_for('admin_campaigns'))

    @app.route('/admin/donors')
    @admin_required
    def admin_donors():
        page = request.args.get('page', 1, type=int)
        donors = db.session.query(
            Donation.full_name,
            Donation.email,
            db.func.count(Donation.id).label('donation_count'),
            db.func.sum(Donation.amount).label('total_donated'),
            db.func.min(Donation.created_at).label('first_donation')
        ).group_by(Donation.email, Donation.full_name).order_by(db.desc('total_donated')).paginate(page=page, per_page=20)
        return render_template('admin_donors.html', donors=donors.items, pagination=donors)

    @app.route('/admin/transactions')
    @admin_required
    def admin_transactions():
        page = request.args.get('page', 1, type=int)
        transactions = Donation.query.order_by(Donation.created_at.desc()).paginate(page=page, per_page=50)
        return render_template('admin_transactions.html', transactions=transactions.items, pagination=transactions)

    @app.route('/admin/generate_dummy_data')
    @admin_required
    def generate_dummy_data():
        fake = Faker()
        categories = ['Health', 'Education', 'Disaster Relief', 'Environment', 'Animal Welfare']
        campaign_ideas = [
            ("Provide Clean Water to Rural Villages", "Help us build sustainable wells and water purification systems to provide safe drinking water to communities suffering from severe droughts."),
            ("Emergency Medical Relief Fund", "Support our mobile health clinics that deliver life-saving medical supplies, vaccinations, and critical care to disaster-stricken areas."),
            ("Sponsor a Child's Education", "Your donation provides school supplies, uniforms, and tuition fees, giving underprivileged children the chance to break the cycle of poverty."),
            ("Reforestation and Climate Action", "Join our initiative to plant 100,000 trees this year. We work with local farmers to restore degraded lands and combat climate change."),
            ("Food Security and Nutrition Program", "Combat malnutrition by funding our community gardens and emergency food banks, ensuring no child goes to bed hungry."),
            ("Women's Empowerment and Microloans", "Empower female entrepreneurs in developing regions with micro-grants and business training to support their families independently."),
            ("Disaster Relief: Earthquake Survivors", "Provide immediate shelter, warm blankets, and hot meals to families who have lost everything in the recent devastating earthquake."),
            ("Youth Mentorship and Skills Training", "Fund our vocational training centers that equip at-risk youth with the digital and practical skills needed to secure stable employment."),
            ("Wildlife Conservation and Anti-Poaching", "Protect endangered species by funding community-led conservation efforts and providing equipment for anti-poaching patrols."),
            ("Refugee Support and Integration", "Help displaced families find hope and stability through language classes, trauma counseling, and housing assistance in their new communities.")
        ]
        
        campaigns = []
        for title, desc in campaign_ideas:
            c = Campaign(
                title=title,
                category=random.choice(categories),
                description=desc,
                goal_amount=round(random.uniform(5000, 50000), 2),
                raised_amount=0.0,
                image_url=f"https://picsum.photos/seed/{random.randint(1,1000)}/600/400"
            )
            db.session.add(c)
            campaigns.append(c)
        db.session.commit()
        
        users = []
        for _ in range(50):
            u = User(
                username=fake.user_name() + str(random.randint(1000,9999)),
                email=f"{random.randint(1000,9999)}_{fake.email()}",
                password=generate_password_hash('password123'),
                phone=fake.phone_number(),
                created_at=fake.date_time_between(start_date='-1y', end_date='now')
            )
            db.session.add(u)
            try:
                db.session.commit()
                users.append(u)
            except IntegrityError:
                db.session.rollback()

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
            campaign.raised_amount += amount

        db.session.commit()
        flash('Successfully generated 10 campaigns, 50 users, and 300 donations!', 'success')
        return redirect(url_for('admin_dashboard'))
