import os
from flask import render_template, request, jsonify, session
from extensions import limiter
from models import db, User, Campaign, Donation
from utils import login_required

MAX_DONATION_AMOUNT = 100_000.0

def init_donor_routes(app):
    @app.route('/campaigns')
    def campaigns():
        all_campaigns = Campaign.query.filter_by(is_active=True).order_by(Campaign.created_at.desc()).all()
        return render_template('campaigns.html', campaigns=all_campaigns)

    @app.route('/donate', methods=['GET'])
    def donate():
        user_data = User.query.get(session['user_id']) if 'user_id' in session else None
        campaigns = Campaign.query.filter_by(is_active=True).limit(100).all()
        selected_cid = request.args.get('campaign_id')
        return render_template('donate.html', user=user_data, campaigns=campaigns, selected_campaign=selected_cid)

    @app.route('/api/process_payment', methods=['POST'])
    @limiter.limit("10 per minute; 50 per hour")
    def process_payment():
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Authentication required.'}), 401
        data = request.get_json(silent=True) or {}
        try:
            amount = float(data.get('amount', 0))
            if amount <= 0:
                return jsonify({'success': False, 'message': 'Amount must be greater than zero.'}), 400
            if amount > MAX_DONATION_AMOUNT:
                return jsonify({'success': False, 'message': f'Amount exceeds the per-transaction limit of ${MAX_DONATION_AMOUNT:,.2f}.'}), 400
                
            campaign_id = data.get('campaign_id')
            campaign_id = int(campaign_id) if campaign_id else None
            
            campaign = None
            if campaign_id:
                campaign = Campaign.query.get(campaign_id)
                if not campaign:
                    return jsonify({'success': False, 'message': 'Invalid campaign.'}), 400
                if not campaign.is_active:
                    return jsonify({'success': False, 'message': 'Campaign is no longer active.'}), 400

            current_user = User.query.get(session['user_id'])
            if not current_user:
                session.clear()
                return jsonify({'success': False, 'message': 'Session expired.'}), 401

            new_donation = Donation(
                user_id=current_user.id,
                campaign_id=campaign_id,
                full_name=current_user.username,
                email=current_user.email,
                amount=round(amount, 2),
                donation_type=data.get('donation_type', 'One-time'),
                payment_method=data.get('payment_method', 'Credit Card'),
                transaction_id="TXN" + os.urandom(8).hex().upper(),
                status='Completed'
            )
            db.session.add(new_donation)
            
            if campaign:
                campaign.raised_amount += round(amount, 2)
                if campaign.raised_amount >= campaign.goal_amount:
                    campaign.is_active = False
                    
            db.session.commit()
            return jsonify({'success': True, 'receipt': {'name': new_donation.full_name, 'amount': new_donation.amount, 'txid': new_donation.transaction_id, 'type': new_donation.donation_type}})
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid amount format.'}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': 'An error occurred during payment processing.'}), 400

    @app.route('/dashboard')
    @login_required
    def donor_dashboard():
        user = User.query.get(session['user_id'])
        donations = user.donations.order_by(Donation.created_at.desc()).all()
        return render_template('donor_dashboard.html', user=user, donations=donations)
