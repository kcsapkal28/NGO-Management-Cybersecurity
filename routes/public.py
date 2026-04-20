import random
from flask import render_template
from faker import Faker
from models import Campaign

def init_public_routes(app):
    @app.route('/')
    def index():
        campaigns = Campaign.query.filter_by(is_active=True).order_by(Campaign.created_at.desc()).limit(3).all()
        return render_template('index.html', campaigns=campaigns)

    @app.route('/about')
    def about():
        fake = Faker()
        about_data = {
            'mission': "Our mission is to empower vulnerable communities through sustainable development, robust education, and uncompromising advocacy. We strive to break the cycle of poverty and inequality by providing immediate relief and long-term resources to those who need it most.",
            'vision': "We envision a world where every individual, regardless of their background, has access to basic human rights, clean water, and quality education. A world where communities are resilient and self-sufficient.",
            'history': [
                "Founded in 2010, our organization began as a small grassroots movement focused on local hunger relief. Over the years, thanks to the generosity of our donors, we have expanded our reach across multiple continents.",
                "In 2015, we launched our flagship Clean Water Initiative, which has since built over 500 wells in drought-stricken regions.",
                "Today, we operate in over 20 countries, tackling intersectional issues ranging from climate change impacts to women's education and emergency disaster relief."
            ],
            'team': [{'name': fake.name(), 'role': random.choice(["Executive Director", "Field Coordinator", "Volunteer Lead", "Program Manager", "Community Organizer", "Communications Director"]), 'image': f"https://i.pravatar.cc/150?u={fake.uuid4()}"} for _ in range(4)]
        }
        return render_template('about.html', data=about_data)

    @app.route('/blogs')
    def blogs():
        fake = Faker()
        blog_topics = [
            ("The Urgency of Clean Water Access", "Millions still lack basic access to safe drinking water. Here is how our latest project is changing lives in rural communities."),
            ("Empowering Women Through Education", "When you educate a woman, you empower an entire village. Read about the success stories from our recent scholarship program."),
            ("Emergency Relief: Rebuilding After the Storm", "Our disaster response team was on the ground within 24 hours. See how your donations provided immediate shelter and medical aid."),
            ("Sustainable Farming for a Better Future", "Teaching sustainable agriculture techniques is key to combating food insecurity and adapting to climate change."),
            ("A Volunteer's Journey: Notes from the Field", "One of our dedicated volunteers shares her heartwarming experience working at our youth center for the past six months."),
            ("How Tech is Transforming Charity", "From transparent donation tracking to advanced logistics, discover how we use technology to maximize our impact.")
        ]
        
        posts = []
        selected_topics = random.sample(blog_topics, 6)
        
        for topic in selected_topics:
            posts.append({
                'title': topic[0],
                'excerpt': topic[1],
                'author': fake.name(),
                'date': fake.date_this_year().strftime('%b %d, %Y'),
                'image': f"https://picsum.photos/seed/{fake.uuid4()}/400/250"
            })
        return render_template('blogs.html', blogs=posts)
