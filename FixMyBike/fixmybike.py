import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import random
from twilio.rest import Client
from geopy.distance import geodesic
from flask_socketio import SocketIO, emit, join_room
from flask_cors import CORS
from datetime import datetime
from dotenv import load_dotenv
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
load_dotenv()
app.secret_key = os.getenv("SECRET_KEY")
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True, async_mode='eventlet')

# ✅ Configure OracleDB
app.config['SQLALCHEMY_DATABASE_URI'] = 'oracle+oracledb://system:velu@127.0.0.1:1521/?service_name=XE'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
# ✅ Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

active_requests = {}
accepted_requests = {}
connected_users = {}  # ✅ Define connected_users to store user connections

class User(db.Model):
    __tablename__ = "bike_users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(30), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    bike_model = db.Column(db.String(255), nullable=False)
    bike_brand = db.Column(db.String(255), nullable=False)
    bike_registration = db.Column(db.String(30), nullable=False)
# ✅ Mechanic Model
class Mechanic(db.Model):
    __tablename__ = "mechanics"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(30), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(13), unique=True, nullable=False)
    shop_name = db.Column(db.String(100), nullable=False)
    shop_location = db.Column(db.String(255), nullable=False)
    shop_license = db.Column(db.String(50))
    gstin = db.Column(db.String(50))

class Admin(db.Model):
    __tablename__ = 'admin_credentials'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class ServiceHistory(db.Model):
    __tablename__ = 'service_history'
    user_id = db.Column(db.Integer, db.ForeignKey('bike_users.id'))
    user_name = db.Column(db.String(100))
    user_phone = db.Column(db.String(20))
    mechanic_id = db.Column(db.Integer, db.ForeignKey('mechanics.id'))
    mechanic_name = db.Column(db.String(100))
    mechanic_phone = db.Column(db.String(20))
    issue = db.Column(db.String(200))
    location = db.Column(db.Text)
    date_time = db.Column(db.DateTime, default=datetime.utcnow, primary_key=True)

# ✅ Create tables
with app.app_context():
    db.create_all()

otp_storage = {}  # ✅ Store OTPs temporarily

@app.route('/mechanic-login', methods=['GET'])
def mechanic_login_page():
    return render_template('mechanic_auth.html') 

@app.route('/mechanic-signup', methods=['POST'])
def mechanic_signup():
    data = request.get_json()
    if Mechanic.query.filter((Mechanic.email == data['email']) | (Mechanic.phone == data['phone'])).first():
        return jsonify({'success': False, 'message': 'Email or phone already registered'})
    new_mechanic = Mechanic(
        full_name=data['full_name'],
        email=data['email'],
        password=generate_password_hash(data['password']),
        phone=data['phone'],
        shop_name=data['shop_name'],
        shop_location=data['shop_location'],
        latitude=data['latitude'],
        longitude=data['longitude'],
        shop_license=data['shop_license'] or None,
        gstin=data['gstin'] or None
    )
    db.session.add(new_mechanic)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Signup successful!', 'redirect': '/mechanic-dashboard'})

@app.route('/mechanic-login', methods=['POST'])
def mechanic_login():
    data = request.get_json()
    mechanic = Mechanic.query.filter_by(email=data['email']).first()
    if mechanic and check_password_hash(mechanic.password, data['password']):
        session['mechanic_id'] = mechanic.id
        return jsonify({'success': True, 'message': 'Login successful!', 'redirect': '/mechanic-dashboard'})
    return jsonify({'success': False, 'message': 'Invalid credentials'})

@app.route('/mechanic-dashboard')
def mechanic_dashboard():
    mechanic_id = session.get('mechanic_id', 'UnknownMechanic')  # Get mechanic ID from session
    mechanic = Mechanic.query.get(mechanic_id)  # Assuming you have a Mechanic model
    if mechanic:
        mechanic_name = mechanic.full_name
        mechanic_phone = mechanic.phone
        mechanic_shop_name = mechanic.shop_name
    else:
        mechanic_name = "Unknown Mechanic"
        mechanic_phone = "Unknown Phone"
        mechanic_phone = "Unknown shop name"
    return render_template('mechanic_dashoboard.html',mechanic_id=mechanic_id,mechanic_name=mechanic_name,mechanic_phone=mechanic_phone,mechanic_shop_name=mechanic_shop_name)

# ======================= **USER ROUTES** ============================
@app.route('/')
def home():
    return render_template("selection_role_page.html")

@app.route('/user-login')
def user_login():
    return render_template("user_auth.html")

# Flask Backend
@app.route('/user_dashboard')
def user_dashboard():
    user_id = session.get('user_id', 'UnknownUser')
    user = User.query.get(user_id)
    if user:
        user_name = user.full_name
        user_phone = user.phone
    else:
        user_name = "Unknown Name"
        user_phone = "Unknown Phone"
    return render_template('dashboard.html', user_id=user_id,user_name=user_name,user_phone=user_phone)

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    # If user disconnects, remove from active_requests
    active_requests.pop(request.sid, None)
    accepted_requests.pop(request.sid, None)

@socketio.on('user_request')
def handle_user_request(data):
    print(f"User sent request: {data}")
    # Save user request
    user_id = session.get("user_id")
    active_requests[request.sid] = data
    # Broadcast to all mechanics
    emit('new_user_request', {
    'user_sid': request.sid,
    'user_id': user_id, 
    'name': data['name'],
    'phone': data['phone'],
    'lat': data['lat'],
    'lng': data['lng'],
    'issue': data['issue'],
    'address': data['address']  # Important! You forgot this.
   }, broadcast=True)

@socketio.on('mechanic_response')
def handle_mechanic_response(data):
    print(f"Mechanic response: {data}")
    if data.get('accepted'):
        user_sid = data.get('user_sid')
        if user_sid and user_sid in active_requests:
            accepted_requests[user_sid] = request.sid  # mechanic's sid
            mechanic_info = {
                'mechanic_id': data['mechanic_id'],
                'mechanic_name': data['mechanic_name'],
                'shop_name': data['shop_name'],
                'phone': data['phone'],
                'lat': data['latitude'],    # add live latitude
                'lng': data['longitude']   # add live longitude
            }
            # Send mechanic details to user
            emit('mechanic_accepted', mechanic_info, to=user_sid)
            user_request = active_requests.get(user_sid)
            if user_request:
                user_lat = user_request['lat']
                user_lng = user_request['lng']
                mechanic_sid = request.sid  # mechanic socket ID
                emit('start_navigation', {
                    'user_lat': user_lat,
                    'user_lng': user_lng
                }, to=mechanic_sid)
    else:
        user_sid = data.get('user_sid')
        if user_sid:
            emit('mechanic_declined', {}, to=user_sid)

@socketio.on("mechanic_location_update")
def handle_mechanic_location_update(data):
    emit("mechanic_location_changed", {
        "lat": data["lat"],
        "lng": data["lng"]
    }, room=data["user_id"])

@socketio.on("register-user")
def register_user(data):
    user_id = data.get("user_id")
    if user_id:
        connected_users[user_id] = request.sid
        print(f"[SocketIO] User {user_id} registered with sid {request.sid}")

@socketio.on("job-completed")
def handle_job_completed(data):
    user_id = data.get("user_id")
    mechanic_id = data.get("mechanic_id")
    issue = data.get("issue")
    location = data.get("location")
    print(f"📦 Incoming data: {data}")
    print(f"🔍 user_id: {user_id}, mechanic_id: {mechanic_id}")
    # Normalize and fetch user socket
    user_id_str = str(int(user_id)) if user_id else None
    user_sid = connected_users.get(user_id_str)
    print(f"📦 connected_users: {connected_users}")
    print(f"🔍 user_sid: {user_sid} for user_id: {user_id_str}")
    if user_sid:
        emit("stop-routing", {}, room=user_sid)
        emit("job-finished", {}, room=user_sid)
        print(f"✅ Emitted stop-routing & job-finished to {user_sid}")
    else:
        print(f"❌ No socket found for user_id: {user_id}")

    # ✅ SQLAlchemy 2.0 compatible fetch
    user = db.session.get(User, user_id)
    mechanic = db.session.get(Mechanic, mechanic_id)
    if user and mechanic:
        history = ServiceHistory(
            user_id=user.id,
            user_name=user.full_name,
            user_phone=user.phone,
            mechanic_id=mechanic.id,
            mechanic_name=mechanic.full_name,
            mechanic_phone=mechanic.phone,
            issue=issue,
            location=location
        )
        db.session.add(history)
        db.session.commit()
        print("✅ Service history saved.")
    else:
        print("❌ Invalid user or mechanic: user =", user, ", mechanic =", mechanic)

# ======================= **USER SIGNUP & LOGIN** ============================
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    user = User.query.filter_by(email=email).first()
    if user and check_password_hash(user.password, password):
        session['user_id'] = user.id
        return jsonify({'success': True, 'message': 'Login successful!', 'redirect': url_for('user_dashboard')})
    print(f"Entered Email: {email}, Entered Password: {password}")
    print(f"Stored Password: {user.password if user else 'No User Found'}")

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    full_name = data.get('full_name')
    email = data.get('email')
    phone = data.get('phone')
    password = data.get('password')
    bike_model = data.get('bike_model')
    bike_brand = data.get('bike_brand')
    bike_registration = data.get('bike_registration')
    if User.query.filter((User.email == email) | (User.phone == phone)).first():
        return jsonify({'success': False, 'message': 'Email or phone already registered'})
    otp = random.randint(100000, 999999)
    otp_storage[phone] = otp
    print(f"🔹 OTP for {phone}: {otp}")
    try:
        client.messages.create(
            body=f"Your OTP code is {otp}",
            from_=TWILIO_PHONE_NUMBER,
            to=phone
        )
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error sending OTP: {e}'})
    session['pending_user'] = {
        'full_name': full_name,
        'email': email,
        'phone': phone,
        'password': password,
        'bike_model': bike_model,
        'bike_brand': bike_brand,
        'bike_registration': bike_registration
    }
    session['pending_phone'] = phone
    return jsonify({'success': True, 'message': 'OTP sent successfully!', 'redirect': '/verify-otp'})

@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    data = request.get_json()
    entered_otp = data.get('otp')
    phone = session.get('pending_phone')
    if not phone or phone not in otp_storage:
        return jsonify({'success': False, 'message': 'Session expired. Please sign up again.'})
    if str(otp_storage[phone]) == entered_otp:
        pending_user = session.pop('pending_user', None)
        if pending_user:
            new_user = User(**pending_user)
            db.session.add(new_user)
            db.session.commit()
            otp_storage.pop(phone, None)

            return jsonify({'success': True, 'message': 'Signup complete!', 'redirect': url_for('user-dashboard')})
    return jsonify({'success': False, 'message': 'Invalid OTP'})

# ======================= **FIND NEARBY MECHANICS** ============================
@app.route('/find_mechanics', methods=['POST'])
def find_mechanics():
    data = request.json
    user_location = (data['latitude'], data['longitude'])
    max_distance_km = 20

    mechanics = Mechanic.query.all()
    nearby_mechanics = [
        {
            'id': m.id,
            'name': m.full_name,
            'latitude': m.latitude,
            'longitude': m.longitude,
            'distance': round(geodesic(user_location, (m.latitude, m.longitude)).km, 2)
        }
        for m in mechanics if geodesic(user_location, (m.latitude, m.longitude)).km <= max_distance_km
    ]
    sorted_mechanics = sorted(nearby_mechanics, key=lambda x: x['distance'])
    return jsonify({'mechanics': sorted_mechanics})

# ✅ WebSocket Handlers for Real-Time Chat
@socketio.on("send_message")
def handle_message(data):
    """Handle text messages"""
    print(f"📩 Message Received: {data}")
    emit("receive_message", data, broadcast=True, include_self=False)
@socketio.on('image')
def handle_image(data):
    """Receive base64 image data and broadcast"""
    print("📷 Image received")
    emit('receive_message', {'type': 'image', 'data': data}, broadcast=True)
@socketio.on('audio')
def handle_audio(data):
    """Receive base64 audio data and broadcast"""
    print("🎤 Audio received")
    emit('receive_message', {'type': 'audio', 'data': data}, broadcast=True)
@app.route('/chat')
def chat_page():
    return render_template('chat.html') 

@app.route("/admin-auth", methods=["GET"])
def admin_login_page():
    return render_template("admin_auth.html")

@app.route("/admin-login", methods=["POST"])
def admin_login():
    email = request.form["email"]
    password = request.form["password"]

    admin = Admin.query.filter_by(email=email, password=password).first()
    if admin:
        flash("✅ Login successful", "success")
        return redirect("/admin-dashboard")
    else:
        flash("❌ Invalid email or password", "error")
        return redirect("/admin-auth")

@app.route("/admin-dashboard")
def admin_dashboard():
    users = User.query.all()
    mechanics = Mechanic.query.all()
    history = ServiceHistory.query.order_by(ServiceHistory.date_time.desc()).all()
    return render_template("admin_dashboard.html", users=users, mechanics=mechanics, history=history)

if __name__ == '__main__':
    socketio.run(app, host="127.0.0.1", port=5000, debug=True) # ✅ Ensure WebSockets work
