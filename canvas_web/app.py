"""
Canvas Assistant — Flask web app with user auth, persistent conversations,
and server-side API calls to Canvas and OpenRouter (AI-agnostic).
"""
from datetime import datetime
import os

import stripe
import requests as req
from dateutil import parser as dtparser
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# ── Stripe & access config ────────────────────────────────────────────────────
stripe.api_key        = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_PUB_KEY        = os.getenv('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_PRICE_ID       = os.getenv('STRIPE_PRICE_ID', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
STRIPE_ENABLED        = bool(os.getenv('STRIPE_SECRET_KEY'))
PRICE_DISPLAY         = os.getenv('PRICE_DISPLAY', '$4.99/month')

# Comma-separated promo codes, e.g. PROMO_CODES=TYSON-VIP,FRIEND-001
PROMO_CODES  = {c.strip().upper() for c in os.getenv('PROMO_CODES', '').split(',') if c.strip()}
# Comma-separated emails that always get free access, e.g. ADMIN_EMAILS=you@example.com
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv('ADMIN_EMAILS', '').split(',') if e.strip()}

app = Flask(__name__)
app.config['SECRET_KEY']        = os.getenv('SECRET_KEY', os.urandom(32).hex())
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE']   = os.getenv('RENDER') is not None
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_SECURE']   = os.getenv('RENDER') is not None

_db_url = os.getenv(
    'DATABASE_URL',
    f'sqlite:///{os.path.join(os.path.dirname(__file__), "canvas_assistant.db")}',
)
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

db = SQLAlchemy(app)
login_mgr = LoginManager(app)
login_mgr.login_view = 'login'


# ── Models ────────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(100), nullable=False)
    email           = db.Column(db.String(150), unique=True, nullable=False)
    password_hash   = db.Column(db.String(256), nullable=False)
    canvas_url      = db.Column(db.String(256), default='')
    canvas_token    = db.Column(db.String(512), default='')
    openrouter_key         = db.Column('anthropic_key', db.String(512), default='')
    model_name             = db.Column(db.String(200), default='nvidia/nemotron-3-super-120b-a12b:free')
    is_paid                = db.Column(db.Boolean, default=False)
    stripe_customer_id     = db.Column(db.String(200), default='')
    stripe_subscription_id = db.Column(db.String(200), default='')
    onboarding_done        = db.Column(db.Boolean, default=False)
    created_at             = db.Column(db.DateTime, default=datetime.utcnow)
    conversations          = db.relationship('Conversation', backref='user', lazy=True,
                                             cascade='all, delete-orphan')


class Conversation(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title      = db.Column(db.String(200), default='New Chat')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages   = db.relationship('Message', backref='conversation', lazy=True,
                                 cascade='all, delete-orphan',
                                 order_by='Message.created_at')


class Message(db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False)
    role            = db.Column(db.String(20), nullable=False)
    content         = db.Column(db.Text, nullable=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)


class UsedPromoCode(db.Model):
    id      = db.Column(db.Integer, primary_key=True)
    code    = db.Column(db.String(100), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    used_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_mgr.user_loader
def load_user(uid):
    return User.query.get(int(uid))


with app.app_context():
    db.create_all()
    # Inline migrations — silently skipped if column already exists
    _new_cols = [
        "ALTER TABLE \"user\" ADD COLUMN model_name VARCHAR(200) DEFAULT 'nvidia/nemotron-3-super-120b-a12b:free'",
        "ALTER TABLE \"user\" ADD COLUMN is_paid BOOLEAN DEFAULT FALSE",
        "ALTER TABLE \"user\" ADD COLUMN stripe_customer_id VARCHAR(200) DEFAULT ''",
        "ALTER TABLE \"user\" ADD COLUMN stripe_subscription_id VARCHAR(200) DEFAULT ''",
    ]
    for _sql in _new_cols:
        try:
            with db.engine.connect() as _conn:
                _conn.execute(db.text(_sql))
                _conn.commit()
        except Exception:
            pass


# ── Canvas API ────────────────────────────────────────────────────────────────

def fetch_canvas_data(canvas_url, canvas_token):
    base    = canvas_url.rstrip('/')
    headers = {'Authorization': f'Bearer {canvas_token}'}

    r = req.get(f'{base}/api/v1/courses', headers=headers,
                params={'enrollment_state': 'active', 'per_page': 50}, timeout=15)
    r.raise_for_status()
    courses = r.json()

    all_assignments = []
    for course in courses:
        cid   = course['id']
        cname = course.get('name', f'Course {cid}')
        try:
            url    = f'{base}/api/v1/courses/{cid}/assignments'
            params = {'per_page': 50, 'bucket': 'upcoming',
                      'order_by': 'due_at', 'include[]': 'submission'}
            while url:
                res = req.get(url, headers=headers, params=params, timeout=15)
                if not res.ok:
                    break
                for a in res.json():
                    a['_course_name'] = cname
                    all_assignments.append(a)
                link = res.headers.get('Link', '')
                url  = next(
                    (p.strip().split(';')[0].strip('<>') for p in link.split(',')
                     if 'rel="next"' in p),
                    None,
                )
                params = None
        except Exception:
            pass

    return {'courses': courses, 'assignments': all_assignments}


# ── AI via OpenRouter ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Canvas Assistant, an AI-powered study helper for a high school student named {user_name}.

## Your role
Help the student stay on top of their Canvas LMS coursework. You have been given live data from their Canvas account including all upcoming assignments, due dates, course names, and submission statuses. Use this data to give accurate, specific answers — never make up assignment names, due dates, or course info.

## Today's date
{today}

## Canvas data
Enrolled courses: {courses}

Upcoming assignments (format: name | course | due date | flags):
{assignment_list}

## How to respond

### Accuracy
- Only reference assignments and due dates that appear in the Canvas data above.
- Always check the submission status before flagging something as urgent — never tell the student to complete an assignment they have already submitted (marked "submitted").
- If Canvas data is empty or missing, say so honestly and suggest the student check their Canvas URL and token in Settings.

### Urgency
- Due within 24 hours → flag with ⚠️, treat as top priority, mention it first.
- Due within 48 hours → note it is coming up soon.
- Never downplay a deadline that is close.

### Tone
- Warm, encouraging, and direct — like a knowledgeable tutor, not a corporate chatbot.
- Use the student's first name occasionally to keep it personal.
- Be honest if there is a heavy workload, but stay positive and solution-focused.

### Format
- Use markdown: **bold** for important items, bullet lists for multiple assignments, clear structure.
- Keep responses concise — the student is likely checking this on their phone between classes.
- End each response with something actionable or encouraging (e.g., a tip, a reminder, or a brief motivational note).

### Study tips
- When flagging a test, quiz, or large project, offer a short 1–2 sentence study tip relevant to the subject if you can infer one.
- Keep tips practical, not generic.

### Scope
- Focus primarily on Canvas assignments, due dates, courses, and study strategy.
- For off-topic questions, give a brief helpful answer, then gently steer back to academics.
- Never claim you can submit assignments, access grades, log into Canvas, or perform any action on the student's behalf.

### Edge cases
- If there are no upcoming assignments, briefly celebrate that and ask if the student wants help reviewing material or planning ahead.
- If asked about a specific assignment not in the Canvas data, say you don't see it in the current data and suggest checking Canvas directly.
- If the student seems stressed or overwhelmed, acknowledge it briefly and help them prioritize."""


def ask_ai(api_key, model, messages, canvas_data, user_name):
    today = datetime.now().strftime('%A, %B %d, %Y')

    lines = []
    for a in canvas_data['assignments']:
        due = a.get('due_at', 'No due date')
        if due and due != 'No due date':
            try:
                dt  = dtparser.parse(due).astimezone()
                due = dt.strftime('%a %b %d, %I:%M %p')
            except Exception:
                pass
        submitted = ' ✓ submitted' if (a.get('submission') or {}).get('submitted_at') else ''
        kind      = ' [QUIZ/TEST]' if 'online_quiz' in (a.get('submission_types') or []) else ''
        lines.append(f"- {a['name']}{kind} | {a['_course_name']} | due: {due}{submitted}")

    system = SYSTEM_PROMPT.format(
        user_name=user_name,
        today=today,
        courses=', '.join(c.get('name', '') for c in canvas_data['courses']) or 'None found',
        assignment_list='\n'.join(lines) if lines else 'No upcoming assignments found.',
    )

    resp = req.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'X-Title': 'Canvas Assistant',
        },
        json={
            'model': model,
            'max_tokens': 1024,
            'messages': [{'role': 'system', 'content': system}, *messages],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('onboarding') if not current_user.onboarding_done
                        else url_for('chat'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user     = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            return redirect(url_for('index'))
        error = 'Invalid email or password.'
    return render_template('login.html', error=error)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')
        if not all([name, email, password]):
            error = 'Please fill in all fields.'
        elif password != confirm:
            error = 'Passwords do not match.'
        elif len(password) < 8:
            error = 'Password must be at least 8 characters.'
        elif User.query.filter_by(email=email).first():
            error = 'An account with that email already exists.'
        else:
            user = User(name=name, email=email,
                        password_hash=generate_password_hash(password),
                        is_paid=email in ADMIN_EMAILS)
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            return redirect(url_for('onboarding'))
    return render_template('signup.html', error=error)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── Onboarding ────────────────────────────────────────────────────────────────

@app.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    error = None
    if request.method == 'POST':
        canvas_url    = request.form.get('canvas_url', '').strip().rstrip('/')
        canvas_token  = request.form.get('canvas_token', '').strip()
        openrouter_key = request.form.get('openrouter_key', '').strip()
        if not all([canvas_url, canvas_token, openrouter_key]):
            error = 'Please fill in all fields before continuing.'
        else:
            current_user.canvas_url      = canvas_url
            current_user.canvas_token    = canvas_token
            current_user.openrouter_key  = openrouter_key
            current_user.onboarding_done = True
            db.session.commit()
            return redirect(url_for('chat'))
    return render_template('onboarding.html', error=error, user=current_user)


# ── Chat ──────────────────────────────────────────────────────────────────────

@app.route('/chat')
@login_required
def chat():
    if not current_user.onboarding_done:
        return redirect(url_for('onboarding'))
    if not current_user.is_paid:
        return redirect(url_for('upgrade'))
    return render_template('index.html', user=current_user)


# ── Settings API ──────────────────────────────────────────────────────────────

@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def api_settings():
    if request.method == 'POST':
        data = request.get_json() or {}
        current_user.canvas_url     = data.get('canvas_url', '').strip().rstrip('/')
        current_user.canvas_token   = data.get('canvas_token', '').strip()
        current_user.openrouter_key = data.get('openrouter_key', '').strip()
        current_user.model_name     = data.get('model_name', '').strip() or 'nvidia/nemotron-3-super-120b-a12b:free'
        db.session.commit()
        return jsonify({'ok': True})
    return jsonify({
        'canvas_url':     current_user.canvas_url,
        'canvas_token':   current_user.canvas_token,
        'openrouter_key': current_user.openrouter_key,
        'model_name':     current_user.model_name or 'nvidia/nemotron-3-super-120b-a12b:free',
    })


# ── Conversations API ─────────────────────────────────────────────────────────

@app.route('/api/conversations', methods=['GET'])
@login_required
def list_conversations():
    convs = (Conversation.query
             .filter_by(user_id=current_user.id)
             .order_by(Conversation.updated_at.desc())
             .limit(50).all())
    return jsonify([{
        'id':         c.id,
        'title':      c.title,
        'updated_at': c.updated_at.isoformat(),
    } for c in convs])


@app.route('/api/conversations', methods=['POST'])
@login_required
def create_conversation():
    conv = Conversation(user_id=current_user.id)
    db.session.add(conv)
    db.session.commit()
    return jsonify({'id': conv.id, 'title': conv.title})


@app.route('/api/conversations/<int:conv_id>', methods=['GET'])
@login_required
def get_conversation(conv_id):
    conv = Conversation.query.filter_by(
        id=conv_id, user_id=current_user.id).first_or_404()
    return jsonify({
        'id':       conv.id,
        'title':    conv.title,
        'messages': [{'role': m.role, 'content': m.content} for m in conv.messages],
    })


@app.route('/api/conversations/<int:conv_id>', methods=['DELETE'])
@login_required
def delete_conversation(conv_id):
    conv = Conversation.query.filter_by(
        id=conv_id, user_id=current_user.id).first_or_404()
    db.session.delete(conv)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/conversations/<int:conv_id>/message', methods=['POST'])
@login_required
def send_message(conv_id):
    conv     = Conversation.query.filter_by(
        id=conv_id, user_id=current_user.id).first_or_404()
    data     = request.get_json() or {}
    question = data.get('question', '').strip()
    if not question:
        return jsonify({'error': 'Empty message.'}), 400

    if not current_user.is_paid:
        return jsonify({'error': 'upgrade_required'}), 402

    if not current_user.canvas_url or not current_user.canvas_token:
        return jsonify({'error': 'Canvas URL or token is missing — open Settings to add them.'}), 400
    if not current_user.openrouter_key:
        return jsonify({'error': 'OpenRouter API key is missing — open Settings to add it.'}), 400

    try:
        canvas_data = fetch_canvas_data(current_user.canvas_url,
                                        current_user.canvas_token)
    except req.HTTPError as e:
        return jsonify({'error': f'Canvas API error ({e.response.status_code}) — check your Canvas URL and token in Settings.'}), 502
    except Exception as e:
        return jsonify({'error': f'Could not reach Canvas: {e}'}), 502

    try:
        history = [{'role': m.role, 'content': m.content}
                   for m in conv.messages[-20:]]
        history.append({'role': 'user', 'content': question})

        model  = current_user.model_name or 'nvidia/nemotron-3-super-120b-a12b:free'
        answer = ask_ai(current_user.openrouter_key, model, history,
                        canvas_data, current_user.name)
    except req.HTTPError as e:
        code = e.response.status_code
        if code == 401:
            return jsonify({'error': 'OpenRouter key is invalid — open Settings and re-enter it.'}), 502
        if code == 402:
            return jsonify({'error': 'OpenRouter account has no credits — add credits at openrouter.ai.'}), 502
        return jsonify({'error': f'AI API error ({code}) — check your OpenRouter key and model name in Settings.'}), 502
    except Exception as e:
        return jsonify({'error': f'AI error: {e}'}), 500

    db.session.add_all([
        Message(conversation_id=conv.id, role='user',      content=question),
        Message(conversation_id=conv.id, role='assistant', content=answer),
    ])
    if conv.title == 'New Chat':
        conv.title = question[:60] + ('…' if len(question) > 60 else '')
    conv.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'answer': answer, 'title': conv.title})


# ── Upgrade / payments ────────────────────────────────────────────────────────

@app.route('/upgrade')
@login_required
def upgrade():
    return render_template('upgrade.html', user=current_user,
                           stripe_pub_key=STRIPE_PUB_KEY,
                           stripe_enabled=STRIPE_ENABLED,
                           price_display=PRICE_DISPLAY)


@app.route('/upgrade/promo', methods=['POST'])
@login_required
def apply_promo():
    code  = request.form.get('code', '').strip().upper()
    error = None
    if not code:
        error = 'Please enter a promo code.'
    elif code not in PROMO_CODES:
        error = 'That code is not valid.'
    elif UsedPromoCode.query.filter_by(code=code, user_id=current_user.id).first():
        error = 'That code has already been used.'
    else:
        current_user.is_paid = True
        db.session.add(UsedPromoCode(code=code, user_id=current_user.id))
        db.session.commit()
        return redirect(url_for('chat'))
    return render_template('upgrade.html', user=current_user,
                           stripe_pub_key=STRIPE_PUB_KEY,
                           stripe_enabled=STRIPE_ENABLED,
                           price_display=PRICE_DISPLAY,
                           promo_error=error)


@app.route('/subscribe', methods=['POST'])
@login_required
def subscribe():
    if not STRIPE_ENABLED or not STRIPE_PRICE_ID:
        return render_template('upgrade.html', user=current_user,
                               stripe_pub_key=STRIPE_PUB_KEY,
                               stripe_enabled=STRIPE_ENABLED,
                               price_display=PRICE_DISPLAY,
                               promo_error='Stripe is not configured. Please use a promo code or contact support.')
    try:
        session = stripe.checkout.Session.create(
            customer_email=current_user.email,
            mode='subscription',
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            success_url=request.host_url.rstrip('/') + '/subscribe/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url.rstrip('/') + '/upgrade',
            metadata={'user_id': current_user.id},
        )
        return redirect(session.url, code=303)
    except stripe.error.StripeError as e:
        return render_template('upgrade.html', user=current_user,
                               stripe_pub_key=STRIPE_PUB_KEY,
                               stripe_enabled=STRIPE_ENABLED,
                               price_display=PRICE_DISPLAY,
                               promo_error=f'Stripe error: {e.user_message or str(e)}')


@app.route('/subscribe/success')
@login_required
def subscribe_success():
    session_id = request.args.get('session_id', '')
    if session_id and STRIPE_ENABLED:
        try:
            sess = stripe.checkout.Session.retrieve(session_id)
            if sess.payment_status in ('paid', 'no_payment_required'):
                current_user.is_paid                = True
                current_user.stripe_customer_id     = sess.customer or ''
                current_user.stripe_subscription_id = sess.subscription or ''
                db.session.commit()
        except Exception:
            pass
    return redirect(url_for('chat'))


@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data()
    sig     = request.headers.get('Stripe-Signature', '')
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return '', 400
    if event['type'] == 'customer.subscription.deleted':
        sub_id = event['data']['object']['id']
        user   = User.query.filter_by(stripe_subscription_id=sub_id).first()
        if user:
            user.is_paid = False
            db.session.commit()
    return '', 200


if __name__ == '__main__':
    app.run(debug=True, port=5000)
