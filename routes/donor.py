import os
from flask import render_template, request, jsonify, session
from extensions import limiter
from models import db, User, Campaign, Donation
from utils import login_required
from observability import get_tracer, record_donation

_tracer = get_tracer()

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
        with _tracer.start_as_current_span("donation.create") as span:
            if 'user_id' not in session:
                span.set_attribute("donation.result", "unauthenticated")
                record_donation(None, "rejected")
                return jsonify({'success': False, 'message': 'Authentication required.'}), 401
            data = request.get_json(silent=True) or {}
            campaign_id = data.get('campaign_id')
            try:
                campaign_id = int(campaign_id) if campaign_id else None
            except (TypeError, ValueError):
                campaign_id = None
            try:
                amount = float(data.get('amount', 0))
                span.set_attribute("donation.amount", amount)
                if campaign_id:
                    span.set_attribute("donation.campaign_id", campaign_id)
                if amount <= 0:
                    span.set_attribute("donation.result", "invalid_amount")
                    record_donation(campaign_id, "rejected")
                    return jsonify({'success': False, 'message': 'Amount must be greater than zero.'}), 400
                if amount > MAX_DONATION_AMOUNT:
                    span.set_attribute("donation.result", "over_limit")
                    record_donation(campaign_id, "rejected")
                    return jsonify({'success': False, 'message': f'Amount exceeds the per-transaction limit of ${MAX_DONATION_AMOUNT:,.2f}.'}), 400

                campaign = None
                if campaign_id:
                    # SELECT ... FOR UPDATE so concurrent donations to the
                    # same campaign serialise on this row. Without it, two
                    # in-flight donations both read raised_amount=N, both
                    # compute N+amount, and one increment is lost on commit.
                    # SQLite ignores FOR UPDATE silently — fine for dev.
                    campaign = (
                        Campaign.query
                        .filter_by(id=campaign_id)
                        .with_for_update()
                        .one_or_none()
                    )
                    if not campaign:
                        span.set_attribute("donation.result", "invalid_campaign")
                        record_donation(campaign_id, "rejected")
                        return jsonify({'success': False, 'message': 'Invalid campaign.'}), 400
                    if not campaign.is_active:
                        span.set_attribute("donation.result", "campaign_closed")
                        record_donation(campaign_id, "rejected")
                        return jsonify({'success': False, 'message': 'Campaign is no longer active.'}), 400

                current_user = User.query.get(session['user_id'])
                if not current_user:
                    session.clear()
                    span.set_attribute("donation.result", "session_expired")
                    record_donation(campaign_id, "rejected")
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
                span.set_attribute("donation.result", "completed")
                span.set_attribute("donation.id", new_donation.id)
                record_donation(campaign_id, "completed", amount)
                return jsonify({'success': True, 'receipt': {'name': new_donation.full_name, 'amount': new_donation.amount, 'txid': new_donation.transaction_id, 'type': new_donation.donation_type}})
            except ValueError:
                span.set_attribute("donation.result", "invalid_format")
                record_donation(campaign_id, "rejected")
                return jsonify({'success': False, 'message': 'Invalid amount format.'}), 400
            except Exception as e:
                # Real server-side failure — DB error, transient infra, etc.
                # Roll back, mark the span as errored, and return 500. The
                # previous 400 was misleading: 4xx implies the client is at
                # fault, but here we don't know that.
                db.session.rollback()
                from opentelemetry.trace import Status, StatusCode
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)[:200]))
                span.set_attribute("donation.result", "error")
                record_donation(campaign_id, "failed")
                return jsonify({'success': False, 'message': 'An error occurred during payment processing.'}), 500

    @app.route('/dashboard')
    @login_required
    def donor_dashboard():
        user = User.query.get(session['user_id'])
        donations = user.donations.order_by(Donation.created_at.desc()).all()
        return render_template('donor_dashboard.html', user=user, donations=donations)
