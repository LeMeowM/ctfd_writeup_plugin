from CTFd.models import db


class Writeup(db.Model):
    __tablename__ = "plugin_writeups"
    id = db.Column(db.Integer, primary_key=True)


class WriteupUncensored(db.Model):
    __bind_key__ = "uncensored"
    __tablename__ = "plugin_writeups_uncensored"
    id = db.Column(db.Integer, primary_key=True)
