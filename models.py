from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    score = db.Column(db.Integer, default=0, nullable=False)


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
