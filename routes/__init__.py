from .public import init_public_routes
from .auth import init_auth_routes
from .donor import init_donor_routes
from .admin import init_admin_routes

def register_all_routes(app):
    init_public_routes(app)
    init_auth_routes(app)
    init_donor_routes(app)
    init_admin_routes(app)
