from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from flask_socketio import SocketIO, send, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ---------------- CONFIG ----------------
os.makedirs(app.instance_path, exist_ok=True)
db_path = os.path.join(app.instance_path, 'chat.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)
socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

# ---------------- MODELS ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    active = db.Column(db.Boolean, default=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(50), nullable=False)
    receiver = db.Column(db.String(50), nullable=True)
    text = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)

with app.app_context():
    db.create_all()

# ---------------- ROUTES ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        pwd = request.form["password"]

        u = User.query.filter_by(username=user).first()
        if u and check_password_hash(u.password, pwd):
            session["user"] = user
            u.active = True
            db.session.commit()
            return redirect("/chat")
        return "Invalid username or password"

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        user = request.form["username"]
        pwd = request.form["password"]

        if User.query.filter_by(username=user).first():
            return "Username already exists"

        db.session.add(User(
            username=user,
            password=generate_password_hash(pwd)
        ))
        db.session.commit()
        return redirect("/")

    return render_template("register.html")

@app.route("/chat")
def chat():
    if "user" not in session:
        return redirect("/")
    users = User.query.all()
    return render_template("chat.html", user=session["user"], users=users)

@app.route("/logout")
def logout():
    if "user" in session:
        u = User.query.filter_by(username=session["user"]).first()
        if u:
            u.active = False
            db.session.commit()
        session.clear()
    return redirect("/")

@app.route("/private_messages/<username>")
def private_messages(username):
    current = session.get("user")
    msgs = Message.query.filter(
        ((Message.sender == current) & (Message.receiver == username)) |
        ((Message.sender == username) & (Message.receiver == current))
    ).order_by(Message.timestamp).all()

    return jsonify([
        {
            "sender": m.sender,
            "message": m.text,
            "time": m.timestamp.strftime("%d %b %Y, %I:%M %p")
        } for m in msgs
    ])

# ---------------- SOCKET EVENTS ----------------
@socketio.on("connect")
def connect():
    if "user" in session:
        users = [u.username for u in User.query.filter_by(active=True)]
        emit("active_users", users, broadcast=True)

@socketio.on("disconnect")
def disconnect():
    if "user" in session:
        u = User.query.filter_by(username=session["user"]).first()
        if u:
            u.active = False
            db.session.commit()
        users = [u.username for u in User.query.filter_by(active=True)]
        emit("active_users", users, broadcast=True)

@socketio.on("join_private")
def join_private(data):
    sender = session.get("user")
    receiver = data.get("user")
    room = "-".join(sorted([sender, receiver]))
    join_room(room)

@socketio.on("message")
def public_message(msg):
    sender = session.get("user")
    m = Message(sender=sender, text=msg)
    db.session.add(m)
    db.session.commit()

    send({
        "sender": sender,
        "message": msg,
        "time": m.timestamp.strftime("%d %b %Y, %I:%M %p")
    }, broadcast=True)

@socketio.on("private_message")
def private_message(data):
    sender = session.get("user")
    receiver = data["receiver"]
    room = "-".join(sorted([sender, receiver]))

    m = Message(sender=sender, receiver=receiver, text=data["message"])
    db.session.add(m)
    db.session.commit()

    emit("private_message", {
        "sender": sender,
        "receiver": receiver,
        "message": data["message"],
        "time": m.timestamp.strftime("%d %b %Y, %I:%M %p")
    }, room=room)

@socketio.on("typing")
def typing(data):
    sender = session.get("user")
    receiver = data["receiver"]
    room = "-".join(sorted([sender, receiver]))
    emit("typing", {"sender": sender}, room=room)

# ---------------- RUN ----------------
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)
