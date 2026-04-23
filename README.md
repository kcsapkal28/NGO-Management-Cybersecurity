# NGO Management Platform

A robust, modular Non-Governmental Organization (NGO) management platform built with Python and Flask. This platform enables organizations to manage fundraising campaigns, track donors natively, and process simulated donations.

## ✨ Features

- **Role-Based Access**: Distinct capabilities for Public Users, Authenticated Donors, and Administrators.
- **Campaign Management**: Admins can create and close fundraising campaigns. Campaigns automatically close upon reaching 100% of their funding goal.
- **Donor Tracking**: Aggregates all donors, including guest checkouts, displaying lifetime contribution metrics.
- **API Simulation**: Built-in JSON API to process frontend payments asynchronously.
- **Data Population**: One-click dummy data generator for development and testing.

## 🚀 Getting Started

### Prerequisites
- Docker and Docker Compose installed.

### Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd Cybersecurity-NGO-Management
   ```

2. **Run with Docker (Recommended):**
   The entire stack (App, Postgres, Prometheus, Grafana, Jaeger, ELK) is containerized.
   ```bash
   docker-compose up -d --build
   ```
   *The application will be accessible at `http://localhost:5001/`*

3. **Initialize Data:**
   Visit `http://localhost:5001/admin/generate_dummy_data` to populate the database with test data.

**Admin Setup Note**: The very first user to sign up on the platform is automatically granted Administrator privileges.

---

## 🛠 Observability Stack

The platform includes a pre-configured observability stack accessible at the following ports:
- **Grafana**: `http://localhost:3000` (User: `admin`, Pass: `admin`)
- **Prometheus**: `http://localhost:9090`
- **Jaeger (Tracing)**: `http://localhost:16686`
- **Elasticsearch**: `http://localhost:9200`

For a detailed breakdown of the system design, port mapping, and troubleshooting, refer to the [Architecture & Operations Guide](System-Reports/Architecture-Guide.md).

---

## 📚 Documentation

The application relies on three core Database Models defined in `models.py`:

1. **User**: Represents registered accounts. Contains `username`, `email`, password hashes, and a boolean `is_admin` flag.
2. **Campaign**: Represents a fundraising initiative. Contains a `goal_amount`, `raised_amount`, and an `is_active` boolean state.
3. **Donation**: Represents a financial transaction. Links to a `User` (nullable for guests) and a `Campaign`. It tracks the `amount`, `payment_method`, and generates a unique `transaction_id`.

**Modularity**: The application logic is decoupled into specific Blueprints/route files located in the `routes/` directory, making it highly maintainable and scalable.

---

## 🛣 Route Definitions

Below is a comprehensive list of all application routes and their purposes:

### Public Routes (`routes/public.py`)
- `GET /` : Home page displaying active campaigns.
- `GET /about` : Information about the NGO (Mission, Vision, History, Team).
- `GET /blogs` : Displays dynamically generated articles related to the NGO's mission.

### Authentication Routes (`routes/auth.py`)
- `GET /auth` : Renders the login and registration modal/page.
- `POST /signup` : Creates a new `User` account. Safely handles duplicates.
- `POST /login` : Authenticates a user and establishes a session.
- `GET /logout` : Clears the current session.

### Donor Routes (`routes/donor.py`)
- `GET /campaigns` : Displays all currently active fundraising campaigns.
- `GET /donate` : Checkout page. Users select a campaign and input payment details.
- `POST /api/process_payment` : JSON API endpoint. Processes the donation, updates the campaign's raised amount, auto-closes the campaign if the goal is met, and creates a `Donation` record.
- `GET /dashboard` : *(Login Required)* Personal dashboard for registered donors to view their past donations.

### Admin Routes (`routes/admin.py`)
*(All routes below require Administrator privileges)*
- `GET /admin` : The central dashboard showing financial analytics and recent transactions.
- `GET/POST /admin/campaigns` : View all paginated campaigns or submit a form to create a new one.
- `GET /admin/campaigns/<id>/close` : Manually marks a campaign's `is_active` status as false.
- `GET /admin/donors` : Views all unique donors (aggregated by email, including guests) and their lifetime totals.
- `GET /admin/transactions` : Views a paginated list of all individual `Donation` records.
- `GET /admin/generate_dummy_data` : Development tool that bulk inserts users, campaigns, and transactions using the `Faker` library.
