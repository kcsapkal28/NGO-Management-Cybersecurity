from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Initialize SQLAlchemy
db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    
    # New Feature: Phone number for users
    phone = db.Column(db.String(50), nullable=True) 
    
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    
    # New Features: Category and Image
    category = db.Column(db.String(50), default='General') 
    image_url = db.Column(db.String(255), default='https://via.placeholder.com/600x400?text=Campaign')
    
    description = db.Column(db.Text, nullable=False)
    goal_amount = db.Column(db.Float, nullable=False)
    raised_amount = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Optimization: Dynamic property to automatically calculate progress
    @property
    def progress_percentage(self):
        if self.goal_amount > 0:
            return min(round((self.raised_amount / self.goal_amount) * 100, 2), 100.0)
        return 0

class Donation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) 
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=True)
    
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    
    donation_type = db.Column(db.String(50), default='One-time') 
    payment_method = db.Column(db.String(50), nullable=False) 
    transaction_id = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(20), default='Completed') 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Optimization: Cascade deletes. If a user is deleted, their donations remain but user_id becomes Null.
    user = db.relationship('User', backref=db.backref('donations', lazy='dynamic'))
    campaign = db.relationship('Campaign', backref=db.backref('donations', lazy='dynamic'))