

# # models.py
# class Marathon(db.Model):
#     __tablename__ = "marathons"
#     id = db.Column(db.Integer, primary_key=True)
#     name = db.Column(db.String, nullable=False)
#     join_code = db.Column(db.String, unique=True)
#     join_code_expires_at = db.Column(db.DateTime)
#     join_code_try_window_start = db.Column(db.DateTime)
#     join_code_try_count = db.Column(db.Integer, default=0)

# class Group(db.Model):
#     __tablename__ = "groups"
#     id = db.Column(db.Integer, primary_key=True)
#     marathon_id = db.Column(db.Integer, db.ForeignKey("marathons.id"), nullable=False)
#     name = db.Column(db.String, nullable=False)
#     group_code = db.Column(db.String, unique=True, nullable=False)
#     creator_user_id = db.Column(db.Integer)
#     created_at = db.Column(db.DateTime, default=datetime.utcnow)

# class UserGroup(db.Model):
#     __tablename__ = "user_groups"
#     user_id = db.Column(db.Integer, primary_key=True)
#     group_id = db.Column(db.Integer, primary_key=True)
#     role = db.Column(db.String, default="member")
#     joined_at = db.Column(db.DateTime, default=datetime.utcnow)