import os
from flask import Flask
from models import db

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Configuration ---
base_dir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(base_dir, 'ngo_database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()

# --- Register Routes ---
from routes import register_all_routes
register_all_routes(app)

if __name__ == '__main__':
    app.run(debug=True)