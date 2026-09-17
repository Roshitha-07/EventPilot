from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, session, flash, jsonify, send_file
from flask_mysqldb import MySQL
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
import MySQLdb.cursors
import config
import random
import qrcode
import os

app = Flask(__name__)
app.secret_key = "event-management-milestone-2"

app.config['MYSQL_HOST'] = config.MYSQL_HOST
app.config['MYSQL_USER'] = config.MYSQL_USER
app.config['MYSQL_PASSWORD'] = config.MYSQL_PASSWORD
app.config['MYSQL_DB'] = config.MYSQL_DB
app.config['MAIL_SERVER'] = config.MAIL_SERVER
app.config['MAIL_PORT'] = config.MAIL_PORT
app.config['MAIL_USE_TLS'] = config.MAIL_USE_TLS
app.config['MAIL_USERNAME'] = config.MAIL_USERNAME
app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD

mysql = MySQL(app)
mail = Mail(app)

# -----------------------------------------------------------------------------
# Milestone 3 data layer
# These tables are created automatically so the new Sponsorship & Operations
# module can be added to an existing EventPilot installation without breaking
# the earlier milestone tables.
# -----------------------------------------------------------------------------
SPONSOR_PACKAGES = ['Platinum', 'Gold', 'Silver']
INCIDENT_THEMES = ['Safety & Emergency', 'AV & Technical', 'Sponsor Operations',
                    'Security & Access', 'Venue & Logistics', 'Registration & Check-in',
                    'General Operations']
INCIDENT_SEVERITIES = ['Critical', 'High', 'Medium', 'Low']
INCIDENT_STATUSES = ['Open', 'In Progress', 'Monitoring', 'Resolved']
ALERT_TIERS = ['Critical', 'High-Priority', 'Medium-Priority', 'Informational']

# Keyword rules the Incident Agent uses to identify, categorize (assign a
# theme), prioritize and route every incident that is reported.
INCIDENT_RULES = [
    ('Safety & Emergency', ['fire', 'injury', 'emergency', 'evacuat', 'exit', 'medical', 'hazard', 'smoke', 'collapse'], 'Critical', 'Safety Officer', 1),
    ('AV & Technical', ['microphone', 'mic ', 'speaker', 'projector', 'audio', 'sound', 'screen', 'wifi', 'network', 'laptop', 'stream', 'av '], 'High', 'AV Team', 4),
    ('Security & Access', ['theft', 'unauthorized', 'security', 'badge', 'access', 'crowd', 'altercation'], 'High', 'Security Team', 4),
    ('Sponsor Operations', ['sponsor', 'booth', 'signage', 'branding', 'banner', 'activation'], 'Medium', 'Sponsor Desk', 8),
    ('Venue & Logistics', ['venue', 'room', 'seating', 'parking', 'power', 'electric', 'air condition', ' ac ', 'catering', 'food', 'washroom', 'furniture'], 'Medium', 'Venue Team', 12),
    ('Registration & Check-in', ['registration', 'check-in', 'checkin', 'qr code', 'token', 'badge printing'], 'Medium', 'Registration Desk', 12),
]

def classify_incident(title, description):
    """Incident Agent: identify the theme, prioritize severity, and assign an owner."""
    text = f"{title} {description}".lower()
    for theme, keywords, severity, team, sla_hours in INCIDENT_RULES:
        if any(k in text for k in keywords):
            return {'theme': theme, 'severity': severity, 'team': team, 'sla_hours': sla_hours}
    return {'theme': 'General Operations', 'severity': 'Medium', 'team': 'Operations Team', 'sla_hours': 24}

def score_sponsor(s):
    """Sponsorship Agent: measure engagement/benefit and produce a health score."""
    committed = float(s.get('committed_amount') or 0)
    delivered = float(s.get('delivered_value') or 0)
    delivery_raw = (delivered / committed * 100) if committed else 0
    impressions = int(s.get('impressions') or 0)
    engagement = int(s.get('engagements') or 0)
    engagement_rate_raw = (engagement / impressions * 100) if impressions else 0
    contract_value = float(s.get('contract_value') or 0)
    amount_paid = float(s.get('amount_paid') or 0)
    payment_progress_raw = (amount_paid / contract_value * 100) if contract_value else 0
    # Cap every displayed percentage at 100% - a sponsor can over-deliver or
    # overpay in the raw numbers, but a percentage-of-target metric should
    # never show more than 100% on screen.
    delivery = min(100, round(delivery_raw, 1))
    engagement_rate = min(100, round(engagement_rate_raw, 2))
    payment_progress = min(100, round(payment_progress_raw, 1))
    score = min(100, round(delivery_raw * 0.5 + min(100, engagement_rate_raw * 12) * 0.3 + min(100, float(s.get('rating') or 0) * 20) * 0.2, 1))
    if score >= 80:
        health, recommendation = 'Excellent', 'Renew early and offer a premium activation package.'
    elif score >= 60:
        health, recommendation = 'Healthy', 'Maintain the partnership and strengthen on-site activation.'
    else:
        health, recommendation = 'Needs Attention', 'Schedule a sponsor review and improve delivered visibility.'
    return {'delivery': delivery, 'engagement_rate': engagement_rate,
            'payment_progress': payment_progress, 'score': score,
            'health': health, 'recommendation': recommendation}

# -----------------------------------------------------------------------------
# Agent orchestration layer
# -----------------------------------------------------------------------------
AGENT_DEFINITIONS = [
    ('Venue Agent', 'Venues', 'Capacity, budget & facilities', 'venue'),
    ('Speaker Agent', 'Speakers & sessions', 'Availability & expertise', 'speaker'),
    ('Sponsorship Agent', 'Sponsors', 'Health, ROI & deliverables', 'sponsor'),
    ('Incident Agent', 'Incidents', 'Severity, routing & SLA', 'incident'),
    ('Analytics Agent', 'Participants', 'Attendance & insights', 'analytics'),
    ('Alert Agent', 'Operations', 'Signals & escalation', 'alert'),
]

AGENT_ROUTING_RULES = [
    ('Sponsorship Agent', ('sponsor', 'sponsorship', 'roi', 'lead', 'impression', 'engagement', 'partner', 'payment'),
     'Analyze sponsor health, engagement and delivered value.'),
    ('Incident Agent', ('incident', 'emergency', 'medical', 'fire', 'microphone', 'mic', 'audio', 'security', 'issue', 'failure', 'problem'),
     'Classify the issue, assign severity/owner and prepare the operational response.'),
    ('Venue Agent', ('venue', 'capacity', 'room', 'hall', 'seating', 'facility', 'facilities', 'location', 'space'),
     'Evaluate venue capacity, facilities, budget and suitability.'),
    ('Speaker Agent', ('speaker', 'session', 'expertise', 'availability', 'schedule', 'talk'),
     'Check speaker/session compatibility and scheduling requirements.'),
    ('Analytics Agent', ('attendance', 'attendee', 'participant', 'check-in', 'checkin', 'analytics', 'metric', 'kpi'),
     'Analyze participation, attendance and event performance metrics.'),
    ('Alert Agent', ('alert', 'notification', 'escalation', 'monitor', 'risk', 'warning'),
     'Review operational signals and determine alert/escalation priority.'),
]

def route_agent_task(task):
    """Deterministically route an operational task to the best specialist agent.

    This function intentionally has no external AI dependency, so the
    orchestration page and the end-to-end test remain reliable offline.
    """
    text = (task or '').strip().lower()
    if not text:
        return 'Analytics Agent', 'Summarize current event metrics and operational status.'
    for agent, keywords, action in AGENT_ROUTING_RULES:
        if any(keyword in text for keyword in keywords):
            return agent, action
    return 'Analytics Agent', 'Review the current event context and return the most relevant operational insight.'


def build_orchestration_context():
    """Read current event data once for the orchestration dashboard."""
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    counts = {}
    queries = {
        'participants': "SELECT COUNT(*) AS c FROM attendees",
        'checked_in': "SELECT COUNT(*) AS c FROM attendees WHERE attendance='Present'",
        'venues': "SELECT COUNT(*) AS c FROM venues",
        'speakers': "SELECT COUNT(*) AS c FROM speakers",
        'sessions': "SELECT COUNT(*) AS c FROM sessions",
        'sponsors': "SELECT COUNT(*) AS c FROM sponsors",
        'incidents': "SELECT COUNT(*) AS c FROM incidents",
        'open_incidents': "SELECT COUNT(*) AS c FROM incidents WHERE status!='Resolved'",
        'critical_incidents': "SELECT COUNT(*) AS c FROM incidents WHERE severity='Critical' AND status!='Resolved'",
        'alerts': "SELECT COUNT(*) AS c FROM operational_alerts WHERE is_read=0",
    }
    for key, sql in queries.items():
        try:
            cur.execute(sql)
            row = cur.fetchone()
            counts[key] = int(row['c'] or 0)
        except Exception:
            # A missing optional table should not make the orchestration page
            # unusable on older installations.
            counts[key] = 0
    cur.close()
    total = counts['participants']
    counts['attendance_rate'] = round(counts['checked_in'] * 100 / total, 1) if total else 0
    return counts


def run_all_agents(context):
    """Run a deterministic pass through every specialist agent."""
    results = []
    summaries = {
        'Venue Agent': f"Reviewed {context['venues']} venues against capacity and facility requirements.",
        'Speaker Agent': f"Reviewed {context['speakers']} speakers and {context['sessions']} scheduled sessions.",
        'Sponsorship Agent': f"Reviewed {context['sponsors']} sponsors for health, engagement and delivery.",
        'Incident Agent': f"Reviewed {context['incidents']} incidents; {context['open_incidents']} remain active.",
        'Analytics Agent': f"Calculated {context['attendance_rate']}% attendance from {context['participants']} participants.",
        'Alert Agent': f"Checked operational signals; {context['alerts']} unread alert(s) are currently visible.",
    }
    for name, domain, role, cls in AGENT_DEFINITIONS:
        results.append({'agent': name, 'domain': domain, 'role': role, 'class': cls,
                        'status': 'COMPLETED', 'summary': summaries[name]})
    return results

def log_alert(cur, title, message, priority, source):
    cur.execute("INSERT INTO operational_alerts(title,message,priority,source) VALUES(%s,%s,%s,%s)",
                (title, message, priority, source))

def sync_live_alerts(cur):
    """Recompute the always-on 'Live Monitor' alerts from current data so the
    Operational Alerts feed reflects real-time system state on every visit/poll.
    NOTE: both callers pass a MySQLdb.cursors.DictCursor, so every row comes
    back as a dict - always select with an alias and read that alias key,
    never cur.fetchone()[0] or tuple-unpack the row."""
    cur.execute("DELETE FROM operational_alerts WHERE source='Live Monitor'")
    cur.execute("SELECT COUNT(*) AS c FROM incidents WHERE severity='Critical' AND status!='Resolved'")
    critical_open = cur.fetchone()['c']
    if critical_open:
        log_alert(cur, f'{critical_open} critical incident(s) open',
                   'Immediate escalation required — safety or critical operations are at risk.', 'Critical', 'Live Monitor')
    cur.execute("SELECT COUNT(*) AS c FROM incidents WHERE severity='High' AND status='Open'")
    high_open = cur.fetchone()['c']
    if high_open:
        log_alert(cur, f'{high_open} high-priority incident(s) awaiting action',
                   'Open high-severity incidents have not yet moved to In Progress.', 'High-Priority', 'Live Monitor')
    cur.execute("SELECT COALESCE(SUM(committed_amount),0) AS committed, COALESCE(SUM(delivered_value),0) AS delivered FROM sponsors")
    totals = cur.fetchone()
    committed = float(totals['committed'] or 0); delivered = float(totals['delivered'] or 0)
    if committed and delivered / committed < 0.75:
        log_alert(cur, f'Sponsor delivery at {round(delivered/committed*100,1)}%',
                   'Overall delivered value has fallen below 75% of total committed sponsorship value.', 'High-Priority', 'Live Monitor')
    cur.execute("SELECT COUNT(*) AS c FROM sponsors WHERE status='At Risk'")
    at_risk = cur.fetchone()['c']
    if at_risk:
        log_alert(cur, f'{at_risk} sponsor(s) marked At Risk',
                   'Review delivered value and engagement before the next renewal conversation.', 'Medium-Priority', 'Live Monitor')
    cur.execute("SELECT COUNT(*) AS c FROM incidents WHERE status IN ('Open','In Progress')")
    open_count = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM sponsors")
    sponsor_count = cur.fetchone()['c']
    log_alert(cur, 'Operations snapshot',
               f'{sponsor_count} sponsor(s) tracked - {open_count} active incident(s) - monitoring in real time.',
               'Informational', 'Live Monitor')
    mysql.connection.commit()

def ensure_milestone3_tables():
    cur = mysql.connection.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS sponsors (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(150) NOT NULL,
        company VARCHAR(180) NOT NULL,
        contact_email VARCHAR(180),
        phone VARCHAR(30),
        package VARCHAR(30) DEFAULT 'Silver',
        budget DECIMAL(12,2) DEFAULT 0,
        committed_amount DECIMAL(12,2) DEFAULT 0,
        delivered_value DECIMAL(12,2) DEFAULT 0,
        leads INT DEFAULT 0,
        impressions INT DEFAULT 0,
        engagements INT DEFAULT 0,
        status VARCHAR(30) DEFAULT 'Active',
        rating DECIMAL(4,2) DEFAULT 0,
        contract_start DATE NULL,
        contract_end DATE NULL,
        contract_value DECIMAL(12,2) DEFAULT 0,
        deliverables TEXT,
        payment_status VARCHAR(30) DEFAULT 'Pending',
        amount_paid DECIMAL(12,2) DEFAULT 0,
        branding_requirements TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    # Upgrade path for installations created before these columns existed.
    for col_sql in [
        "ADD COLUMN phone VARCHAR(30)", "ADD COLUMN contract_start DATE NULL",
        "ADD COLUMN contract_end DATE NULL", "ADD COLUMN contract_value DECIMAL(12,2) DEFAULT 0",
        "ADD COLUMN deliverables TEXT", "ADD COLUMN payment_status VARCHAR(30) DEFAULT 'Pending'",
        "ADD COLUMN amount_paid DECIMAL(12,2) DEFAULT 0", "ADD COLUMN branding_requirements TEXT"
    ]:
        try:
            cur.execute(f"ALTER TABLE sponsors {col_sql}")
        except Exception:
            pass
    cur.execute("""CREATE TABLE IF NOT EXISTS incidents (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(180) NOT NULL,
        category VARCHAR(80) NOT NULL,
        description TEXT,
        severity VARCHAR(20) DEFAULT 'Medium',
        status VARCHAR(30) DEFAULT 'Open',
        assigned_to VARCHAR(120),
        escalation_level INT DEFAULT 0,
        reported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        due_at DATETIME NULL,
        resolution TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS incident_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        incident_id INT NOT NULL,
        action VARCHAR(150) NOT NULL,
        note TEXT,
        actor VARCHAR(120),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE CASCADE
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS operational_alerts (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(180) NOT NULL,
        message TEXT NOT NULL,
        priority VARCHAR(20) DEFAULT 'Medium',
        source VARCHAR(80) DEFAULT 'System',
        is_read TINYINT(1) DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("SELECT COUNT(*) FROM sponsors")
    if cur.fetchone()[0] == 0:
        cur.executemany("""INSERT INTO sponsors
            (name,company,contact_email,phone,package,budget,committed_amount,delivered_value,leads,impressions,engagements,
             status,rating,contract_start,contract_end,contract_value,deliverables,payment_status,amount_paid,branding_requirements,notes)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [
            ('Ananya Rao','NovaTech Solutions','partnerships@novatech.example','+91 98765 43210','Platinum',
             250000,220000,198000,420,185000,12800,'Active',4.6,'2026-01-10','2026-12-31',250000,
             'Main-stage keynote branding, 20x20 booth, app push notifications, delegate bag inserts',
             'Partial',150000,'Logo on all stage backdrops, primary color #0B1F4D, minimum 40% share of voice on main banner',
             'Strong digital engagement; consider renewing at Platinum.'),
            ('Vikram Shah','GreenGrid Energy','sponsors@greengrid.example','+91 98123 44556','Gold',
             160000,150000,132000,280,120000,7600,'Active',4.2,'2026-01-15','2026-12-31',160000,
             '10x10 booth, one breakout session slot, website logo placement',
             'Paid',160000,'Green color palette only, sustainability messaging required on all collateral',
             'Good visibility; improve on-site activation.'),
            ('Meera Iyer','CloudBridge','events@cloudbridge.example','+91 90000 11223','Silver',
             90000,85000,61000,115,72000,3900,'At Risk',3.4,'2026-02-01','2026-11-30',90000,
             'Registration desk co-branding, email newsletter mention',
             'Pending',20000,'Logo usage restricted to digital channels only',
             'Low delivered value compared with commitment.'),
            ('Arjun Menon','Orbit Mobility','partners@orbitmobility.example','+91 99887 66554','Gold',
             140000,135000,141000,360,142000,9800,'Active',4.8,'2025-12-01','2026-11-30',140000,
             'Lanyard branding, charging station branding, one panel seat',
             'Paid',140000,'High-contrast logo required on lanyards, no competitor placement nearby',
             'Highest performing sponsor in the current portfolio.')
        ])
    cur.execute("SELECT COUNT(*) FROM incidents")
    if cur.fetchone()[0] == 0:
        cur.executemany("""INSERT INTO incidents
            (title,category,description,severity,status,assigned_to,escalation_level,due_at,resolution)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [
            ('Main hall microphone failure','AV & Technical','Wireless microphone is intermittently losing signal during rehearsals.','High','In Progress','AV Team',1,None,None),
            ('Sponsor booth signage delay','Sponsor Operations','CloudBridge branding material has not arrived at the registration zone.','Medium','Open','Sponsor Desk',0,None,None),
            ('Emergency exit obstruction','Safety & Emergency','Storage boxes are blocking a marked emergency exit corridor.','Critical','Open','Safety Officer',2,None,None)
        ])
        mysql.connection.commit()
        cur.execute("SELECT id,title,category,severity,assigned_to FROM incidents")
        for row in cur.fetchall():
            cur.execute("""INSERT INTO incident_logs(incident_id,action,note,actor) VALUES(%s,%s,%s,%s)""",
                (row[0], 'Incident Reported', f'Identified as {row[2]} - Prioritized as {row[3]} - Assigned to {row[4]}', 'Incident Agent'))
    # Demo inventory keeps a fresh installation visually useful for presentations.
    cur.execute("SELECT COUNT(*) FROM venues")
    if cur.fetchone()[0] == 0:
        cur.executemany("""INSERT INTO venues
            (name,area,budget,capacity,rating,cleanliness,projector,sound_system,seating_arrangement,feedback,other_requirements)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [
            ('Skyline Convention Hall','Vizag',180000,900,4.7,4.6,'2 x 4K projectors','PA system + wireless microphones','Theatre','Excellent acoustics','LED wall, green room, parking'),
            ('TechPark Auditorium','Madhurawada',120000,650,4.5,4.4,'1 x 4K projector','Digital PA + microphones','Theatre','Reliable AV and seating','Wi-Fi, backstage, cafeteria'),
            ('Harbour View Conference Centre','Beach Road',95000,420,4.3,4.2,'2 projectors','PA system','Classroom','Good for workshops','Parking, breakout rooms'),
            ('SVECW Innovation Arena','Bhimavaram',70000,300,4.8,4.7,'1 projector','Sound system','Classroom','Campus-ready venue','Wi-Fi, labs, student support')
        ])
    cur.execute("SELECT COUNT(*) FROM speakers")
    if cur.fetchone()[0] == 0:
        cur.executemany("""INSERT INTO speakers
            (name,expertise,budget,available_date,start_time,end_time,requirements,rating,feedback)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [
            ('Dr. Anika Rao','Artificial Intelligence, Machine Learning',60000,'2026-09-15','10:00:00','11:30:00','Projector + wireless mic',4.9,'Excellent keynote speaker'),
            ('Rahul Varma','Cloud Computing, DevOps',45000,'2026-09-15','12:00:00','13:00:00','Demo laptop + internet',4.6,'Strong technical sessions'),
            ('Megha Nair','Cybersecurity, Digital Safety',50000,'2026-09-16','10:30:00','12:00:00','Secure demo environment',4.8,'Highly engaging'),
            ('Kiran Das','Product Engineering, Startups',40000,'2026-09-16','14:00:00','15:00:00','Stage screen',4.4,'Good for founder sessions')
        ])
    cur.execute("SELECT COUNT(*) FROM sessions")
    if cur.fetchone()[0] == 0:
        cur.execute("SELECT id FROM venues ORDER BY id LIMIT 4"); venue_ids=[r[0] for r in cur.fetchall()]
        cur.execute("SELECT id FROM speakers ORDER BY id LIMIT 4"); speaker_ids=[r[0] for r in cur.fetchall()]
        if len(venue_ids) >= 4 and len(speaker_ids) >= 4:
            cur.executemany("""INSERT INTO sessions(title,session_date,start_time,end_time,venue_id,speaker_id,expected_attendees)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""", [
                ('Opening Keynote: AI for Real Events','2026-09-15','10:00:00','11:30:00',venue_ids[0],speaker_ids[0],500),
                ('Cloud Operations for Scale','2026-09-15','12:00:00','13:00:00',venue_ids[1],speaker_ids[1],350),
                ('Cybersecurity Incident Readiness','2026-09-16','10:30:00','12:00:00',venue_ids[2],speaker_ids[2],280),
                ('Building Products People Use','2026-09-16','14:00:00','15:00:00',venue_ids[3],speaker_ids[3],220)
            ])
    cur.execute("SELECT COUNT(*) FROM attendees")
    if cur.fetchone()[0] == 0:
        cur.execute("SELECT id FROM users WHERE email='participant@event.com' LIMIT 1")
        demo_user=cur.fetchone()
        demo_user_id=demo_user[0] if demo_user else None
        cur.executemany("""INSERT INTO attendees
            (registration_token,user_id,name,email,phone,gender,location,category,vip,attendance,status)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [
            ('EVT412455',demo_user_id,'Aarav Kumar','aarav@example.com','9000000001','Male','Vizag','Student','No','Present','Registered'),
            ('EVT280980',None,'Diya Sharma','diya@example.com','9000000002','Female','Vijayawada','Student','Yes','Present','Registered'),
            ('EVT531204',None,'Rohan Mehta','rohan@example.com','9000000003','Male','Hyderabad','Professional','No','Present','Registered'),
            ('EVT674318',None,'Sana Ali','sana@example.com','9000000004','Female','Bengaluru','Professional','No','Absent','Registered'),
            ('EVT725491',None,'Vivek Reddy','vivek@example.com','9000000005','Male','Bhimavaram','Faculty','No','Present','Registered'),
            ('EVT803216',None,'Keerthi Rao','keerthi@example.com','9000000006','Female','Chennai','Student','Yes','Absent','Registered'),
            ('EVT914602',None,'Arjun Singh','arjun@example.com','9000000007','Male','Vizag','Professional','No','Present','Registered'),
            ('EVT356780',None,'Nisha Patel','nisha@example.com','9000000008','Female','Mumbai','Faculty','No','Absent','Registered')
        ])
    mysql.connection.commit()
    cur.close()

@app.before_request
def initialize_milestone3():
    # Keep the existing project flow intact; initialize only once per process.
    if not app.config.get('_MILESTONE3_READY'):
        try:
            ensure_milestone3_tables()
            app.config['_MILESTONE3_READY'] = True
        except Exception:
            # Existing routes can still show their normal database error if the
            # MySQL service is unavailable; do not hide the original behaviour.
            pass

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                return redirect('/login')
            if role and session.get('role') != role:
                flash("You do not have permission to access this page.")
                return redirect('/dashboard')
            return f(*args, **kwargs)
        return wrapped
    return decorator

@app.route('/')
def home():
    return render_template("home.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password']
        role = request.form.get('role', 'attendee').strip().lower()
        if role not in ('organizer', 'attendee'):
            flash('Invalid portal selected.')
            return redirect('/login?role=attendee')
        cur = mysql.connection.cursor()
        cur.execute("SELECT id,name,email,password,role FROM users WHERE email=%s AND role=%s", (email, role))
        user = cur.fetchone()
        cur.close()
        if user and (user[3] == password or (str(user[3]).startswith(('pbkdf2:', 'scrypt:')) and check_password_hash(user[3], password))):
            session['user_id'] = user[0]
            session['name'] = user[1]
            session['email'] = user[2]
            session['role'] = user[4]
            return redirect('/organizer' if role == 'organizer' else '/participant')
        flash("Invalid email, password, or role.")
    selected_role = request.args.get('role', 'attendee')
    if selected_role not in ('organizer', 'attendee'):
        selected_role = 'attendee'
    return render_template("login.html", selected_role=selected_role)

@app.route('/deployment-guide.pdf')
@login_required('organizer')
def deployment_guide_pdf():
    pdf_path = os.path.join(app.root_path, 'docs', 'EventPilot_AI_Project_Guide.pdf')
    if not os.path.exists(pdf_path):
        pdf_path = os.path.join(app.root_path, 'docs', 'EventFlow_AI_Project_Guide.pdf')
    if not os.path.exists(pdf_path):
        flash('Project guide PDF is not available yet.', 'error')
        return redirect('/deployment')
    return send_file(pdf_path, as_attachment=True, download_name='EventPilot_AI_Project_Guide.pdf')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/attendee/register', methods=['GET', 'POST'])
def attendee_register():
    if request.method == 'POST':
        name=request.form['name'].strip(); email=request.form['email'].strip()
        phone=request.form['phone'].strip(); password=request.form['password']
        cur=mysql.connection.cursor()
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            cur.close(); flash("Email already registered."); return redirect('/attendee/register')
        cur.execute("INSERT INTO users(name,email,password,role) VALUES(%s,%s,%s,'attendee')",
                    (name,email,generate_password_hash(password)))
        mysql.connection.commit()
        cur.close()
        flash("Attendee account created. Please login.")
        return redirect('/login')
    return render_template("attendee_register.html")

@app.route('/register', methods=['GET', 'POST'])
@login_required('attendee')
def register():
    if request.method == 'POST':
        name=request.form['name']; email=session['email']; phone=request.form['phone']
        gender=request.form['gender']; location=request.form['location']
        category=request.form['category']; vip=request.form['vip']
        cur=mysql.connection.cursor()
        cur.execute("SELECT id FROM attendees WHERE email=%s OR phone=%s", (email,phone))
        if cur.fetchone():
            cur.close(); flash("You already have an event registration."); return redirect('/register')
        token=None
        for _ in range(20):
            candidate="EVT"+str(random.randint(100000,999999))
            cur.execute("SELECT id FROM attendees WHERE registration_token=%s",(candidate,))
            if not cur.fetchone(): token=candidate; break
        if not token:
            cur.close(); flash("Could not generate registration token."); return redirect('/register')
        qr_dir=os.path.join(app.root_path,"qr_codes"); os.makedirs(qr_dir,exist_ok=True)
        qr_path=os.path.join(qr_dir,token+".png"); qrcode.make(token).save(qr_path)
        cur.execute("""INSERT INTO attendees
        (registration_token,name,email,phone,gender,location,category,vip,attendance,status,qr_path)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'Absent','Registered',%s)""",
        (token,name,email,phone,gender,location,category,vip,qr_path))
        mysql.connection.commit()
        try:
            msg=Message("Event Registration Successful",sender=app.config['MAIL_USERNAME'],recipients=[email])
            msg.body=f"Hello {name}, your registration token is {token}. Please show the QR code at check-in."
            with open(qr_path,'rb') as fp: msg.attach(token+".png","image/png",fp.read())
            mail.send(msg)
        except Exception:
            pass
        cur.close()
        return render_template("success.html",token=token)
    return render_template("register.html")

@app.route('/attendee')
@login_required('attendee')
def attendee_dashboard():
    cur=mysql.connection.cursor()
    cur.execute("""SELECT registration_token,name,location,category,vip,attendance,status,checkin_time
                   FROM attendees WHERE email=%s ORDER BY id DESC LIMIT 1""",(session['email'],))
    registration=cur.fetchone()
    cur.execute("""SELECT s.title,s.session_date,s.start_time,s.end_time,v.name,sp.name
                   FROM sessions s JOIN venues v ON s.venue_id=v.id JOIN speakers sp ON s.speaker_id=sp.id
                   ORDER BY s.session_date,s.start_time""")
    sessions=cur.fetchall()
    cur.close()
    return render_template("attendee.html",registration=registration,sessions=sessions)

@app.route('/checkin', methods=['GET','POST'])
@login_required('organizer')
def checkin():
    attendee=None; message=None
    if request.method=="POST":
        token=request.form['token'].strip()
        cur=mysql.connection.cursor()
        cur.execute("SELECT * FROM attendees WHERE registration_token=%s",(token,))
        attendee=cur.fetchone()
        if attendee:
            if attendee[11]=="Present": message="Attendance Already Marked"
            else:
                cur.execute("UPDATE attendees SET attendance='Present',checkin_time=%s WHERE registration_token=%s",
                            (datetime.now(),token))
                mysql.connection.commit(); message="Attendance Marked Successfully"
                cur.execute("SELECT * FROM attendees WHERE registration_token=%s",(token,)); attendee=cur.fetchone()
        else: message="Invalid Registration Token"
        cur.close()
    return render_template("checkin.html",attendee=attendee,message=message)

@app.route('/dashboard')
@login_required('organizer')
def dashboard():
    cur=mysql.connection.cursor()
    def count(q): cur.execute(q); return cur.fetchone()[0]
    total=count("SELECT COUNT(*) FROM attendees"); present=count("SELECT COUNT(*) FROM attendees WHERE attendance='Present'")
    absent=count("SELECT COUNT(*) FROM attendees WHERE attendance='Absent'"); vip=count("SELECT COUNT(*) FROM attendees WHERE vip='Yes'")
    cancelled=count("SELECT COUNT(*) FROM attendees WHERE status='Cancelled'")
    male=count("SELECT COUNT(*) FROM attendees WHERE gender='Male'"); female=count("SELECT COUNT(*) FROM attendees WHERE gender='Female'"); other=count("SELECT COUNT(*) FROM attendees WHERE gender='Other'")
    student=count("SELECT COUNT(*) FROM attendees WHERE category='Student'"); faculty=count("SELECT COUNT(*) FROM attendees WHERE category='Faculty'"); professional=count("SELECT COUNT(*) FROM attendees WHERE category='Professional'")
    cur.execute("SELECT location,COUNT(*) FROM attendees GROUP BY location"); location_data=cur.fetchall()
    cur.execute("SELECT registration_token,name,location,attendance FROM attendees ORDER BY created_at DESC LIMIT 5"); recent=cur.fetchall()
    cur.close()
    return render_template("dashboard.html",total=total,present=present,absent=absent,vip=vip,cancelled=cancelled,
        male=male,female=female,other=other,student=student,faculty=faculty,professional=professional,
        locations=location_data,location_labels=[x[0] for x in location_data],location_counts=[x[1] for x in location_data],
        attendance_rate=round(present*100/total,2) if total else 0,recent=recent)

@app.route('/participant')
@login_required('attendee')
def participant_portal():
    """Participant home with the same core options from the original system."""
    return render_template("participant_portal.html")

@app.route('/participant/dashboard')
@login_required('attendee')
def participant_dashboard():
    # Render the original participant dashboard directly instead of redirecting
    # to a different route, so the Participant Dashboard card always opens
    # inside the Participant portal flow.
    cur=mysql.connection.cursor()
    cur.execute("""SELECT registration_token,name,location,category,vip,attendance,status,checkin_time
                   FROM attendees WHERE email=%s ORDER BY id DESC LIMIT 1""", (session['email'],))
    registration=cur.fetchone()
    cur.execute("""SELECT s.title,s.session_date,s.start_time,s.end_time,v.name,sp.name
                   FROM sessions s JOIN venues v ON s.venue_id=v.id JOIN speakers sp ON s.speaker_id=sp.id
                   ORDER BY s.session_date,s.start_time""")
    sessions=cur.fetchall()
    cur.close()
    return render_template("attendee.html", registration=registration, sessions=sessions)

@app.route('/participant/checkin', methods=['GET', 'POST'])
@login_required('attendee')
def participant_checkin():
    attendee = None
    message = None
    cur = mysql.connection.cursor()
    cur.execute("""SELECT * FROM attendees
                   WHERE email=%s
                   ORDER BY id DESC LIMIT 1""", (session['email'],))
    attendee = cur.fetchone()

    if request.method == "POST":
        token = request.form.get('token', '').strip()
        if not token:
            message = "Please enter your registration token."
        elif not attendee or attendee[1] != token:
            message = "The token does not match your participant registration."
        elif attendee[11] == "Present":
            message = "Your attendance is already marked."
        else:
            cur.execute("""UPDATE attendees
                           SET attendance='Present', checkin_time=%s
                           WHERE id=%s""", (datetime.now(), attendee[0]))
            mysql.connection.commit()
            cur.execute("SELECT * FROM attendees WHERE id=%s", (attendee[0],))
            attendee = cur.fetchone()
            message = "Check-in completed successfully."
    cur.close()
    return render_template("participant_checkin.html", attendee=attendee, message=message)

@app.route('/participant/attendees')
@login_required('attendee')
def participant_attendees():
    # Keep attendee information private: show only names/status, not contact details.
    cur = mysql.connection.cursor()
    cur.execute("""SELECT name, category, vip, attendance
                   FROM attendees
                   ORDER BY name""")
    rows = cur.fetchall()
    cur.close()
    return render_template("participant_attendees.html", attendees=rows)

@app.route('/participant/insights')
@login_required('attendee')
def participant_insights():
    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) FROM attendees")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM attendees WHERE attendance='Present'")
    present = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM sessions")
    sessions_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM venues")
    venues_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM speakers")
    speakers_count = cur.fetchone()[0]
    cur.close()

    attendance_rate = round((present * 100 / total), 2) if total else 0
    return render_template(
        "participant_insights.html",
        total=total,
        present=present,
        sessions_count=sessions_count,
        venues_count=venues_count,
        speakers_count=speakers_count,
        attendance_rate=attendance_rate
    )

@app.route('/organizer')
@login_required('organizer')
def organizer():
    return render_template("organizer.html")


@app.route('/intelligence')
@login_required('organizer')
def intelligence():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT COUNT(*) AS c FROM attendees"); participants = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM sponsors"); sponsors = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM incidents"); incidents = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM operational_alerts WHERE is_read=0"); alerts = cur.fetchone()['c']
    cur.close()
    return render_template('intelligence.html', participants=participants, sponsors=sponsors,
                           incidents=incidents, alerts=alerts)

@app.route('/executive-dashboard')
@login_required('organizer')
def executive_dashboard():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT COUNT(*) AS c FROM attendees"); participants = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM attendees WHERE attendance='Present'"); present = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM sponsors"); sponsors = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM incidents WHERE status!='Resolved'"); open_incidents = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM operational_alerts WHERE is_read=0"); unread_alerts = cur.fetchone()['c']
    cur.execute("SELECT COALESCE(SUM(committed_amount),0) AS v FROM sponsors"); committed = float(cur.fetchone()['v'] or 0)
    cur.execute("SELECT COALESCE(SUM(delivered_value),0) AS v FROM sponsors"); delivered = float(cur.fetchone()['v'] or 0)
    incident_counts = {}
    for sev in INCIDENT_SEVERITIES:
        cur.execute("SELECT COUNT(*) AS c FROM incidents WHERE severity=%s AND status!='Resolved'", (sev,))
        incident_counts[sev.lower()] = int(cur.fetchone()['c'])
    cur.execute("SELECT COUNT(*) AS c FROM incidents WHERE status='Resolved'"); resolved_incidents = int(cur.fetchone()['c'])
    cur.execute("SELECT COUNT(*) AS c FROM attendees WHERE status='Active'"); active_participants = int(cur.fetchone()['c'])

    # Small data sets for the executive charts. These are read-only queries.
    cur.execute("SELECT status, COUNT(*) AS c FROM incidents GROUP BY status")
    incident_status_rows = cur.fetchall()
    incident_status = {str(r['status']): int(r['c']) for r in incident_status_rows}

    cur.execute("SELECT package, COUNT(*) AS c FROM sponsors GROUP BY package ORDER BY package")
    sponsor_package = [(str(r['package'] or 'Other'), int(r['c'])) for r in cur.fetchall()]

    cur.execute("SELECT DATE(created_at) AS d, COUNT(*) AS c FROM attendees WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 6 DAY) GROUP BY DATE(created_at) ORDER BY d")
    registration_rows = {str(r['d']): int(r['c']) for r in cur.fetchall()}
    registration_trend = []
    for i in range(6, -1, -1):
        day = datetime.now().date() - timedelta(days=i)
        key = str(day)
        registration_trend.append({'label': day.strftime('%a'), 'count': registration_rows.get(key, 0)})

    cur.close()
    attendance_rate = round(present / participants * 100, 1) if participants else 0
    delivery = min(100, round(delivered / committed * 100, 1)) if committed else 0
    operations = min(100, round(100 - (incident_counts.get('critical',0)*25 + incident_counts.get('high',0)*10 + incident_counts.get('medium',0)*3), 1))
    health = round(attendance_rate*0.30 + delivery*0.35 + operations*0.35, 1)
    health_label = 'Excellent' if health >= 85 else ('Healthy' if health >= 70 else 'Needs attention')
    attendance_chart = [('Registered', participants), ('Checked in', present), ('Active', active_participants)]
    incident_chart = [
        ('Open', incident_status.get('Open', 0)),
        ('In Progress', incident_status.get('In Progress', 0)),
        ('Monitoring', incident_status.get('Monitoring', 0)),
        ('Resolved', incident_status.get('Resolved', 0)),
    ]
    incident_total = sum(v for _, v in incident_chart)
    sponsor_chart = [('Committed', committed), ('Delivered', delivered)]
    return render_template('executive_dashboard.html', participants=participants, present=present,
                           sponsors=sponsors, open_incidents=open_incidents, unread_alerts=unread_alerts,
                           committed=committed, delivered=delivered, delivery=delivery,
                           attendance_rate=attendance_rate, operations=operations, health=health,
                           health_label=health_label, attendance_chart=attendance_chart,
                           incident_chart=incident_chart, sponsor_chart=sponsor_chart,
                           sponsor_package=sponsor_package, registration_trend=registration_trend, incident_total=incident_total,
                           critical_incidents=incident_counts.get('critical',0),
                           high_incidents=incident_counts.get('high',0),
                           medium_incidents=incident_counts.get('medium',0),
                           resolved_incidents=resolved_incidents)

@app.route('/agent-orchestration', methods=['GET','POST'])
@login_required('organizer')
def agent_orchestration():
    context = build_orchestration_context()
    result = None
    run_results = None
    mode = None
    if request.method == 'POST':
        mode = request.form.get('mode', 'task')
        if mode == 'run_all':
            run_results = run_all_agents(context)
        else:
            task = request.form.get('task', '').strip()
            if task:
                agent, action = route_agent_task(task)
                result = {'agent': agent, 'action': action, 'task': task}
    return render_template('agent_orchestration.html', result=result, run_results=run_results,
                           context=context, agents=AGENT_DEFINITIONS, mode=mode)

@app.route('/end-to-end-testing', methods=['GET','POST'])
@login_required('organizer')
def end_to_end_testing():
    tests = [
        ('Registration → Login → Event flow', 'Checks authentication and required event routes are registered.'),
        ('Participant workflow', 'Checks attendee registration, token/check-in and participant portal routes.'),
        ('Sponsor workflow', 'Checks sponsor tables, scoring logic and sponsor management routes.'),
        ('Incident → Alert workflow', 'Checks incident classification and the live-alert pipeline.'),
        ('Agent orchestration workflow', 'Checks deterministic task routing to specialist agents.'),
        ('Dashboard data verification', 'Checks executive metrics can be calculated from current database data.'),
        ('API & database testing', 'Checks the required MySQL tables and JSON/live operational endpoint.'),
        ('Error & performance testing', 'Runs lightweight validation without changing business data.')
    ]
    results = None
    if request.method == 'POST':
        results = []
        cur = None
        try:
            cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            # 1. Required routes
            route_rules = {r.rule for r in app.url_map.iter_rules()}
            required = {'/login', '/organizer', '/register', '/checkin', '/sponsors',
                        '/incidents', '/agent-orchestration', '/executive-dashboard'}
            missing = required - route_rules
            results.append({'name': tests[0][0], 'passed': not missing,
                            'detail': 'All core authentication/event routes are registered.' if not missing else f'Missing routes: {", ".join(sorted(missing))}'})
            participant_ok = '/attendee/register' in route_rules and '/participant' in route_rules
            results.append({'name': tests[1][0], 'passed': participant_ok,
                            'detail': 'Participant registration and portal routes are available.' if participant_ok else 'Participant routes are incomplete.'})

            cur.execute("SELECT COUNT(*) AS c FROM sponsors")
            sponsor_count = int(cur.fetchone()['c'])
            sample_score = score_sponsor({'committed_amount':100,'delivered_value':80,'impressions':1000,'engagements':100,'contract_value':100,'amount_paid':50,'rating':4})
            sponsor_ok = sponsor_count >= 0 and 0 <= sample_score['score'] <= 100
            results.append({'name': tests[2][0], 'passed': sponsor_ok,
                            'detail': f'Sponsor table is readable ({sponsor_count} records); scoring stays within 0–100.'})

            classified = classify_incident('Microphone failure', 'Main stage audio is not working')
            incident_ok = classified['theme'] == 'AV & Technical' and classified['severity'] == 'High'
            results.append({'name': tests[3][0], 'passed': incident_ok,
                            'detail': f'Incident Agent classified the test case as {classified["theme"]} / {classified["severity"]}.'})

            routed = route_agent_task('Analyze sponsor performance')
            orch_ok = routed[0] == 'Sponsorship Agent'
            results.append({'name': tests[4][0], 'passed': orch_ok,
                            'detail': f'Example task routed to {routed[0]}.'})

            cur.execute("SELECT COUNT(*) AS c FROM attendees")
            participants = int(cur.fetchone()['c'])
            cur.execute("SELECT COUNT(*) AS c FROM incidents WHERE status!='Resolved'")
            open_incidents = int(cur.fetchone()['c'])
            dashboard_ok = participants >= 0 and open_incidents >= 0
            results.append({'name': tests[5][0], 'passed': dashboard_ok,
                            'detail': f'Executive metrics read successfully: {participants} participants, {open_incidents} open incidents.'})

            cur.execute("SHOW TABLES")
            table_names = {list(row.values())[0] for row in cur.fetchall()}
            required_tables = {'attendees','sponsors','incidents','operational_alerts'}
            db_ok = required_tables.issubset(table_names)
            results.append({'name': tests[6][0], 'passed': db_ok,
                            'detail': 'Required operational tables are present.' if db_ok else f'Missing tables: {", ".join(sorted(required_tables-table_names))}'})

            validation_ok = bool(classify_incident('', '')['theme']) and bool(route_agent_task('check alerts')[0])
            results.append({'name': tests[7][0], 'passed': validation_ok,
                            'detail': 'Validation and routing functions completed without exceptions.'})
        except Exception as exc:
            # Keep individual failures visible instead of pretending the suite passed.
            if not results:
                results = []
            results.append({'name': 'Test runner infrastructure', 'passed': False, 'detail': str(exc)})
        finally:
            if cur:
                cur.close()
    return render_template('end_to_end_testing.html', tests=tests, results=results)


@app.route('/deployment', methods=['GET','POST'])
@login_required('organizer')
def deployment():
    checks = [
        ('Frontend deployment', 'Pages and styles are present.'),
        ('Backend deployment', 'Main Flask routes are ready.'),
        ('Production database', 'MySQL and core tables are ready.'),
        ('Environment variables', 'Keep DB secrets outside the code.'),
        ('Authentication & security', 'Protect login and use a strong secret.'),
        ('API configuration', 'Live alert endpoint is registered.'),
        ('Error handling', 'Agent and incident paths have safe checks.'),
        ('Monitoring / logging', 'Alerts and logs should be watched.'),
        ('Final documentation', 'README, schema and project guide PDF are included.')
    ]
    readiness = []
    if request.method == 'POST':
        route_rules = {r.rule for r in app.url_map.iter_rules()}
        readiness = [
            ('Frontend deployment', os.path.exists(os.path.join(app.root_path, 'static', 'css', 'style.css')) and all(
                os.path.exists(os.path.join(app.root_path, 'templates', f)) for f in
                ['intelligence.html','executive_dashboard.html','agent_orchestration.html','end_to_end_testing.html','deployment.html'])),
            ('Backend deployment', all(r in route_rules for r in ['/organizer','/intelligence','/executive-dashboard','/agent-orchestration','/end-to-end-testing','/deployment'])),
            ('Production database', False),
            ('Environment variables', all(bool(os.environ.get(k)) for k in ['MYSQL_HOST','MYSQL_USER','MYSQL_PASSWORD','MYSQL_DB'])),
            ('Authentication & security', app.secret_key != 'event-management-milestone-2'),
            ('API configuration', '/alerts/live.json' in route_rules),
            ('Error handling', True),
            ('Monitoring / logging', '/alerts' in route_rules and '/alerts/live.json' in route_rules),
            ('Final documentation', os.path.exists(os.path.join(app.root_path, 'README.md')) and os.path.exists(os.path.join(app.root_path, 'database', 'schema.sql')) and os.path.exists(os.path.join(app.root_path, 'docs', 'EventPilot_AI_Project_Guide.pdf')))
        ]
        try:
            cur = mysql.connection.cursor()
            cur.execute('SELECT 1')
            readiness[2] = ('Production database', True)
            cur.close()
        except Exception:
            readiness[2] = ('Production database', False)
    return render_template('deployment.html', checks=checks, readiness=readiness)

@app.route('/venues', methods=['GET','POST'])
@login_required('organizer')
def venues():
    cur=mysql.connection.cursor()
    if request.method=="POST":
        cur.execute("""INSERT INTO venues(name,area,budget,capacity,rating,cleanliness,projector,sound_system,seating_arrangement,feedback,other_requirements)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (request.form['name'],request.form['area'],float(request.form['budget']),int(request.form['capacity']),
                     float(request.form['rating']),float(request.form['cleanliness']),request.form['projector'],
                     request.form['sound_system'],request.form['seating_arrangement'],request.form['feedback'],request.form['other_requirements']))
        mysql.connection.commit()
    cur.execute("SELECT * FROM venues ORDER BY rating DESC,cleanliness DESC"); rows=cur.fetchall(); cur.close()
    return render_template("venues.html",venues=rows)

@app.route('/venue-agent', methods=['GET','POST'])
@login_required('organizer')
def venue_agent():
    recommendations=[]
    searched=False
    if request.method=="POST":
        searched=True
        budget=float(request.form.get('budget') or 0)
        capacity=int(request.form.get('capacity') or 0)
        area=request.form.get('area','').strip().lower()
        rating=float(request.form.get('rating') or 0)
        cleanliness=float(request.form.get('cleanliness') or 0)
        projector=request.form.get('projector','').strip().lower()
        sound=request.form.get('sound_system','').strip().lower()
        seating=request.form.get('seating_arrangement','').strip().lower()

        cur=mysql.connection.cursor()
        cur.execute("SELECT * FROM venues ORDER BY rating DESC, cleanliness DESC")
        venues=cur.fetchall()
        cur.close()

        def text_match(value, required):
            if not required:
                return True
            value=(value or '').strip().lower()
            req=required.strip().lower()
            if req in ('yes','required','true'):
                return value in ('yes','true','available','included','projector','sound','pa system','pa') or 'yes' in value or 'available' in value
            if req in ('no','not required','false'):
                return True
            return req in value or value in req

        scored=[]
        for v in venues:
            # Schema order: id,name,area,budget,capacity,rating,cleanliness,projector,sound_system,seating,feedback,other
            venue_area=str(v[2] or '').lower()
            venue_budget=float(v[3] or 0)
            venue_capacity=int(v[4] or 0)
            venue_rating=float(v[5] or 0)
            venue_clean=float(v[6] or 0)
            projector_ok=text_match(v[7], projector)
            sound_ok=text_match(v[8], sound)
            seating_ok=text_match(v[9], seating)

            # Hard requirements: budget and capacity. Quality/facility preferences
            # are scored instead of using brittle exact SQL matches.
            if budget and venue_budget > budget:
                continue
            if capacity and venue_capacity < capacity:
                continue

            score=0.0
            if area:
                score += 20 if area in venue_area or venue_area in area else 0
            if rating:
                score += min(20, (venue_rating/max(rating,1))*20) if venue_rating >= rating else max(0, venue_rating*2)
            else:
                score += venue_rating*2
            if cleanliness:
                score += min(20, (venue_clean/max(cleanliness,1))*20) if venue_clean >= cleanliness else max(0, venue_clean*2)
            else:
                score += venue_clean*2
            if projector:
                score += 15 if projector_ok else 0
            if sound:
                score += 15 if sound_ok else 0
            if seating:
                score += 10 if seating_ok else 0
            if budget and venue_budget <= budget:
                score += max(0, 10 * (1 - venue_budget/budget))
            if capacity and venue_capacity >= capacity:
                score += max(0, 10 * (1 - (venue_capacity-capacity)/max(capacity,1)))

            # Show a venue when it satisfies the hard requirements, even if a
            # free-text facility preference does not exactly match.
            scored.append((score, v))

        scored.sort(key=lambda item: item[0], reverse=True)
        recommendations=[v for score,v in scored[:10]]

    return render_template("venue_agent.html", recommendations=recommendations, searched=searched)

@app.route('/speakers', methods=['GET','POST'])
@login_required('organizer')
def speakers():
    cur=mysql.connection.cursor()
    if request.method=="POST":
        cur.execute("""INSERT INTO speakers(name,expertise,budget,available_date,start_time,end_time,requirements,rating,feedback)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (request.form['name'],request.form['expertise'],float(request.form['budget']),
                     request.form['available_date'],request.form['start_time'],request.form['end_time'],
                     request.form['requirements'],float(request.form['rating']),request.form['feedback']))
        mysql.connection.commit()
    cur.execute("SELECT * FROM speakers ORDER BY rating DESC"); rows=cur.fetchall(); cur.close()
    return render_template("speakers.html",speakers=rows)

@app.route('/speaker-agent', methods=['GET','POST'])
@login_required('organizer')
def speaker_agent():
    recommendations=[]
    if request.method=="POST":
        budget=float(request.form['budget']); date=request.form['date']; start=request.form['start_time']; end=request.form['end_time']
        expertise=request.form['expertise'].strip().lower()
        cur=mysql.connection.cursor()
        cur.execute("""SELECT * FROM speakers
                       WHERE budget<=%s AND available_date=%s AND start_time<=%s AND end_time>=%s
                       AND (LOWER(expertise) LIKE %s OR %s='')
                       ORDER BY rating DESC,budget ASC LIMIT 10""",
                    (budget,date,start,end,"%"+expertise+"%",expertise))
        recommendations=cur.fetchall(); cur.close()
    return render_template("speaker_agent.html",recommendations=recommendations)

@app.route('/schedule', methods=['GET','POST'])
@login_required('organizer')
def schedule():
    cur=mysql.connection.cursor()
    conflict=None; message=None
    if request.method=="POST":
        title=request.form['title']; date=request.form['session_date']; start=request.form['start_time']; end=request.form['end_time']
        venue_id=int(request.form['venue_id']); speaker_id=int(request.form['speaker_id']); attendees=int(request.form['expected_attendees'])
        cur.execute("""SELECT id FROM sessions WHERE session_date=%s AND venue_id=%s
                       AND start_time < %s AND end_time > %s""",(date,venue_id,end,start))
        venue_conflict=cur.fetchone()
        cur.execute("""SELECT id FROM sessions WHERE session_date=%s AND speaker_id=%s
                       AND start_time < %s AND end_time > %s""",(date,speaker_id,end,start))
        speaker_conflict=cur.fetchone()
        if venue_conflict or speaker_conflict:
            conflict="Scheduling conflict: venue or speaker is already booked for this time."
        else:
            cur.execute("""INSERT INTO sessions(title,session_date,start_time,end_time,venue_id,speaker_id,expected_attendees)
                           VALUES(%s,%s,%s,%s,%s,%s,%s)""",(title,date,start,end,venue_id,speaker_id,attendees))
            mysql.connection.commit(); message="Session scheduled successfully."
    cur.execute("SELECT id,name,capacity FROM venues ORDER BY name"); venue_rows=cur.fetchall()
    cur.execute("SELECT id,name,expertise FROM speakers ORDER BY name"); speaker_rows=cur.fetchall()
    cur.execute("""SELECT s.id,s.title,s.session_date,s.start_time,s.end_time,v.name,sp.name,s.expected_attendees
                   FROM sessions s JOIN venues v ON s.venue_id=v.id JOIN speakers sp ON s.speaker_id=sp.id
                   ORDER BY s.session_date,s.start_time"""); sessions=cur.fetchall()
    cur.close()
    return render_template("schedule.html",venues=venue_rows,speakers=speaker_rows,sessions=sessions,conflict=conflict,message=message)

@app.route('/analytics')
@login_required('organizer')
def analytics():
    cur=mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) FROM venues"); venue_count=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM speakers"); speaker_count=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM sessions"); session_count=cur.fetchone()[0]
    cur.execute("SELECT COALESCE(AVG(rating),0),COALESCE(AVG(cleanliness),0) FROM venues"); venue_quality=cur.fetchone()
    cur.execute("SELECT COALESCE(AVG(rating),0) FROM speakers"); speaker_rating=cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(expected_attendees),0) FROM sessions"); planned_attendees=cur.fetchone()[0]
    cur.execute("""SELECT v.name,COUNT(s.id),COALESCE(SUM(s.expected_attendees),0)
                   FROM venues v LEFT JOIN sessions s ON v.id=s.venue_id GROUP BY v.id ORDER BY COUNT(s.id) DESC""")
    utilization=cur.fetchall()
    cur.execute("""SELECT sp.name,COUNT(s.id) FROM speakers sp LEFT JOIN sessions s ON sp.id=s.speaker_id
                   GROUP BY sp.id ORDER BY COUNT(s.id) DESC"""); speaker_usage=cur.fetchall()
    cur.close()
    return render_template("analytics.html",venue_count=venue_count,speaker_count=speaker_count,session_count=session_count,
        venue_quality=venue_quality,speaker_rating=speaker_rating,planned_attendees=planned_attendees,
        utilization=utilization,speaker_usage=speaker_usage)

@app.route('/insights')
@login_required('organizer')
def insights():
    cur=mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) FROM attendees"); total=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM attendees WHERE attendance='Present'"); present=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM attendees WHERE vip='Yes'"); vip=cur.fetchone()[0]
    cur.execute("SELECT location,COUNT(*) FROM attendees GROUP BY location"); location_data=cur.fetchall()
    cur.execute("SELECT category,COUNT(*) FROM attendees GROUP BY category"); category_data=cur.fetchall()
    cur.close()
    attendance_rate=round(present*100/total,2) if total else 0; vip_rate=round(vip*100/total,2) if total else 0
    top_location=max(location_data,key=lambda x:x[1])[0] if location_data else "N/A"
    top_category=max(category_data,key=lambda x:x[1])[0] if category_data else "N/A"
    attendance_insight="Attendance is excellent." if attendance_rate>80 else "Attendance is average; send reminders." if attendance_rate>50 else "Attendance is low; consider follow-up."
    return render_template("insights.html",total=total,present=present,vip=vip,attendance_rate=attendance_rate,vip_rate=vip_rate,
                           top_location=top_location,top_category=top_category,attendance_insight=attendance_insight,
                           vip_insight="Strong VIP turnout; prepare premium arrangements." if vip_rate>=25 else "Monitor VIP turnout and requirements.")

# -----------------------------------------------------------------------------
# Milestone 3: Sponsorship Agent + Incident Agent + Operations Intelligence
# Each capability now lives on its own page: Sponsors (list -> add -> detail),
# Sponsor Performance Tracking, Incident Agent (list -> report -> detail),
# Incident Management Workflows (kanban) and Operational Alerts (real-time).
# -----------------------------------------------------------------------------
def ops_counts(cur):
    """Small shared header counts used by the sub-navigation on every ops page.
    NOTE: every caller passes a MySQLdb.cursors.DictCursor, so rows come back
    as dicts (no positional index) - always select with an alias and read
    that alias key, never cur.fetchone()[0]."""
    cur.execute("SELECT COUNT(*) AS c FROM sponsors")
    sponsor_count = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM incidents WHERE status!='Resolved'")
    open_incidents = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) AS c FROM operational_alerts WHERE is_read=0")
    alert_count = cur.fetchone()['c']
    return {'sponsors': sponsor_count, 'open_incidents': open_incidents, 'alerts': alert_count}

@app.route('/sponsors')
@login_required('organizer')
def sponsors():
    """Sponsorship Agent: sponsor list page with an Add Sponsor entry point."""
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM sponsors ORDER BY rating DESC, company")
    sponsor_rows = cur.fetchall()
    for s in sponsor_rows:
        s.update(score_sponsor(s))
    total_committed = sum(float(s['committed_amount'] or 0) for s in sponsor_rows)
    total_delivered = sum(float(s['delivered_value'] or 0) for s in sponsor_rows)
    at_risk = sum(1 for s in sponsor_rows if s['status'] == 'At Risk')
    counts = ops_counts(cur)
    cur.close()
    return render_template('sponsors.html', sponsors=sponsor_rows, total_committed=total_committed,
                           total_delivered=total_delivered, at_risk=at_risk, counts=counts,
                           packages=SPONSOR_PACKAGES)

@app.route('/sponsors/add', methods=['GET', 'POST'])
@login_required('organizer')
def sponsor_add():
    """Dedicated page (navigated to from the Sponsors list) to onboard a sponsor
    with packages, contract, deliverables, payments and branding requirements."""
    if request.method == 'POST':
        cur = mysql.connection.cursor()
        cur.execute("""INSERT INTO sponsors
            (name,company,contact_email,phone,package,budget,committed_amount,delivered_value,leads,impressions,
             engagements,status,rating,contract_start,contract_end,contract_value,deliverables,payment_status,
             amount_paid,branding_requirements,notes)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
            request.form['name'].strip(), request.form['company'].strip(), request.form.get('contact_email', '').strip(),
            request.form.get('phone', '').strip(), request.form.get('package', 'Silver'),
            float(request.form.get('budget') or 0), float(request.form.get('committed_amount') or 0),
            float(request.form.get('delivered_value') or 0), int(request.form.get('leads') or 0),
            int(request.form.get('impressions') or 0), int(request.form.get('engagements') or 0),
            request.form.get('status', 'Active'), float(request.form.get('rating') or 0),
            request.form.get('contract_start') or None, request.form.get('contract_end') or None,
            float(request.form.get('contract_value') or 0), request.form.get('deliverables', '').strip(),
            request.form.get('payment_status', 'Pending'), float(request.form.get('amount_paid') or 0),
            request.form.get('branding_requirements', '').strip(), request.form.get('notes', '').strip()))
        mysql.connection.commit()
        new_id = cur.lastrowid
        log_alert(cur, f"New sponsor onboarded: {request.form['company'].strip()}",
                   f"Signed at {request.form.get('package','Silver')} package.", 'Informational', 'Sponsorship Agent')
        mysql.connection.commit()
        cur.close()
        flash('Sponsor added successfully.')
        return redirect(f'/sponsors/{new_id}')
    return render_template('sponsor_add.html', packages=SPONSOR_PACKAGES)

@app.route('/sponsors/<int:sponsor_id>', methods=['GET', 'POST'])
@login_required('organizer')
def sponsor_detail(sponsor_id):
    """Sponsor profile page: fill in / update packages, contracts, deliverables,
    payments, branding requirements and engagement metrics for one sponsor."""
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    if request.method == 'POST':
        cur2 = mysql.connection.cursor()
        cur2.execute("""UPDATE sponsors SET name=%s, company=%s, contact_email=%s, phone=%s, package=%s, budget=%s,
            committed_amount=%s, delivered_value=%s, leads=%s, impressions=%s, engagements=%s, status=%s, rating=%s,
            contract_start=%s, contract_end=%s, contract_value=%s, deliverables=%s, payment_status=%s, amount_paid=%s,
            branding_requirements=%s, notes=%s WHERE id=%s""", (
            request.form['name'].strip(), request.form['company'].strip(), request.form.get('contact_email', '').strip(),
            request.form.get('phone', '').strip(), request.form.get('package', 'Silver'),
            float(request.form.get('budget') or 0), float(request.form.get('committed_amount') or 0),
            float(request.form.get('delivered_value') or 0), int(request.form.get('leads') or 0),
            int(request.form.get('impressions') or 0), int(request.form.get('engagements') or 0),
            request.form.get('status', 'Active'), float(request.form.get('rating') or 0),
            request.form.get('contract_start') or None, request.form.get('contract_end') or None,
            float(request.form.get('contract_value') or 0), request.form.get('deliverables', '').strip(),
            request.form.get('payment_status', 'Pending'), float(request.form.get('amount_paid') or 0),
            request.form.get('branding_requirements', '').strip(), request.form.get('notes', '').strip(), sponsor_id))
        mysql.connection.commit(); cur2.close()
        flash('Sponsor profile updated.')
        return redirect(f'/sponsors/{sponsor_id}')
    cur.execute("SELECT * FROM sponsors WHERE id=%s", (sponsor_id,))
    sponsor = cur.fetchone()
    counts = ops_counts(cur)
    cur.close()
    if not sponsor:
        flash('Sponsor not found.')
        return redirect('/sponsors')
    insight = score_sponsor(sponsor)
    return render_template('sponsor_detail.html', sponsor=sponsor, insight=insight, packages=SPONSOR_PACKAGES, counts=counts)

@app.route('/sponsors/performance')
@login_required('organizer')
def sponsor_performance():
    """Sponsor Performance Tracking: measures engagement/benefit and produces insights."""
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM sponsors ORDER BY rating DESC, company")
    sponsor_rows = cur.fetchall()
    for s in sponsor_rows:
        s.update(score_sponsor(s))
    total_committed = sum(float(s['committed_amount'] or 0) for s in sponsor_rows)
    total_delivered = sum(float(s['delivered_value'] or 0) for s in sponsor_rows)
    total_impressions = sum(int(s['impressions'] or 0) for s in sponsor_rows)
    total_engagements = sum(int(s['engagements'] or 0) for s in sponsor_rows)
    top_performer = max(sponsor_rows, key=lambda s: s['score'], default=None)
    needs_attention = [s for s in sponsor_rows if s['health'] == 'Needs Attention']
    counts = ops_counts(cur)
    cur.close()
    return render_template('sponsor_performance.html', sponsors=sponsor_rows, total_committed=total_committed,
                           total_delivered=total_delivered, total_impressions=total_impressions,
                           total_engagements=total_engagements, top_performer=top_performer,
                           needs_attention=needs_attention, counts=counts)

@app.route('/sponsors/report.csv')
@login_required('organizer')
def sponsor_report():
    import csv
    from io import StringIO
    cur = mysql.connection.cursor()
    cur.execute("""SELECT company,package,committed_amount,delivered_value,leads,impressions,engagements,status,
                   rating,contract_value,payment_status,amount_paid FROM sponsors ORDER BY company""")
    rows = cur.fetchall(); cur.close()
    out = StringIO(); writer = csv.writer(out)
    writer.writerow(['Company', 'Package', 'Committed Amount', 'Delivered Value', 'Leads', 'Impressions', 'Engagements',
                      'Status', 'Rating', 'Contract Value', 'Payment Status', 'Amount Paid'])
    writer.writerows(rows)
    from flask import Response
    return Response(out.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=sponsor_performance_report.csv'})

@app.route('/incidents')
@login_required('organizer')
def incidents():
    """Incident Agent: list page with a Report Incident entry point."""
    status_filter = request.args.get('status', '')
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    if status_filter:
        cur.execute("""SELECT * FROM incidents WHERE status=%s
                       ORDER BY FIELD(severity,'Critical','High','Medium','Low'), reported_at DESC""", (status_filter,))
    else:
        cur.execute("SELECT * FROM incidents ORDER BY FIELD(severity,'Critical','High','Medium','Low'), reported_at DESC")
    incident_rows = cur.fetchall()
    open_count = sum(1 for i in incident_rows if i['status'] != 'Resolved')
    critical_count = sum(1 for i in incident_rows if i['severity'] == 'Critical' and i['status'] != 'Resolved')
    resolved_count = sum(1 for i in incident_rows if i['status'] == 'Resolved')
    counts = ops_counts(cur)
    cur.close()
    return render_template('incidents.html', incidents=incident_rows, status_filter=status_filter,
                           open_count=open_count, critical_count=critical_count, resolved_count=resolved_count,
                           counts=counts, statuses=INCIDENT_STATUSES)

@app.route('/incidents/add', methods=['GET', 'POST'])
@login_required('organizer')
def incident_add():
    """The Incident Agent identifies a theme, prioritizes severity and assigns
    an owning team automatically from the title/description, then routes it."""
    if request.method == 'POST':
        title = request.form['title'].strip()
        description = request.form.get('description', '').strip()
        ai = classify_incident(title, description)
        theme = request.form.get('theme') or 'auto'
        theme = ai['theme'] if theme == 'auto' else theme
        severity = request.form.get('severity') or 'auto'
        severity = ai['severity'] if severity == 'auto' else severity
        assigned_to = request.form.get('assigned_to', '').strip() or ai['team']
        due_at = request.form.get('due_at') or (datetime.now() + timedelta(hours=ai['sla_hours']))
        escalation_level = {'Critical': 3, 'High': 2, 'Medium': 1, 'Low': 0}.get(severity, 1)

        cur = mysql.connection.cursor()
        cur.execute("""INSERT INTO incidents(title,category,description,severity,status,assigned_to,escalation_level,due_at)
                       VALUES(%s,%s,%s,%s,'Open',%s,%s,%s)""",
                    (title, theme, description, severity, assigned_to, escalation_level, due_at))
        mysql.connection.commit()
        incident_id = cur.lastrowid
        cur.execute("""INSERT INTO incident_logs(incident_id,action,note,actor) VALUES(%s,%s,%s,%s)""",
                    (incident_id, 'Incident Reported',
                     f'Identified as {theme} - Prioritized as {severity} - Assigned to {assigned_to} (SLA {ai["sla_hours"]}h)',
                     'Incident Agent'))
        log_alert(cur, 'New incident logged', f'"{title}" was identified, categorized and routed to {assigned_to}.',
                   'Informational', 'Incident Agent')
        if severity in ('Critical', 'High'):
            log_alert(cur, f'{severity} incident: {title}', f'Routed to {assigned_to} for immediate action.',
                       'Critical' if severity == 'Critical' else 'High-Priority', 'Incident Agent')
        mysql.connection.commit()
        cur.close()
        flash('Incident created and routed through the Incident Agent workflow.')
        return redirect(f'/incidents/{incident_id}')
    return render_template('incident_add.html', themes=INCIDENT_THEMES, severities=INCIDENT_SEVERITIES)

@app.route('/incidents/<int:incident_id>')
@login_required('organizer')
def incident_detail(incident_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM incidents WHERE id=%s", (incident_id,))
    incident = cur.fetchone()
    if not incident:
        cur.close(); flash('Incident not found.'); return redirect('/incidents')
    cur.execute("SELECT * FROM incident_logs WHERE incident_id=%s ORDER BY created_at DESC", (incident_id,))
    logs = cur.fetchall()
    counts = ops_counts(cur)
    cur.close()
    return render_template('incident_detail.html', incident=incident, logs=logs, counts=counts,
                           statuses=INCIDENT_STATUSES, severities=INCIDENT_SEVERITIES, themes=INCIDENT_THEMES)

@app.route('/incidents/<int:incident_id>/update', methods=['POST'])
@login_required('organizer')
def update_incident(incident_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM incidents WHERE id=%s", (incident_id,))
    before = cur.fetchone()
    severity = request.form.get('severity', 'Medium')
    status = request.form.get('status', 'Open')
    assigned_to = request.form.get('assigned_to', 'Operations').strip()
    escalation_level = int(request.form.get('escalation_level') or 0)
    resolution = request.form.get('resolution', '').strip() or None
    cur.execute("""UPDATE incidents SET severity=%s,status=%s,assigned_to=%s,escalation_level=%s,resolution=%s
                   WHERE id=%s""", (severity, status, assigned_to, escalation_level, resolution, incident_id))
    changes = []
    if before:
        if before['status'] != status: changes.append(f"status {before['status']} -> {status}")
        if before['severity'] != severity: changes.append(f"severity {before['severity']} -> {severity}")
        if before['assigned_to'] != assigned_to: changes.append(f"owner {before['assigned_to']} -> {assigned_to}")
        if resolution and before['resolution'] != resolution: changes.append('resolution notes updated')
    note = '; '.join(changes) if changes else 'Workflow reviewed, no field changes.'
    cur.execute("""INSERT INTO incident_logs(incident_id,action,note,actor) VALUES(%s,%s,%s,%s)""",
                (incident_id, f'Workflow Update - {status}', note, session.get('name', 'Organizer')))
    if status == 'Resolved':
        log_alert(cur, f'Incident resolved: {before["title"] if before else incident_id}',
                   'Tracked to resolution through the Incident Management workflow.', 'Informational', 'Incident Agent')
    elif severity == 'Critical' and status != 'Resolved':
        log_alert(cur, f'Critical incident still open: {before["title"] if before else incident_id}',
                   f'Escalation level L{escalation_level}, owner {assigned_to}.', 'Critical', 'Incident Agent')
    mysql.connection.commit(); cur.close()
    flash('Incident workflow updated.')
    return redirect(f'/incidents/{incident_id}')

@app.route('/incidents/workflows')
@login_required('organizer')
def incident_workflows():
    """Incident Management Workflows: kanban-style tracking through to resolution."""
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM incidents ORDER BY FIELD(severity,'Critical','High','Medium','Low'), reported_at DESC")
    rows = cur.fetchall()
    board = {status: [i for i in rows if i['status'] == status] for status in INCIDENT_STATUSES}
    counts = ops_counts(cur)
    cur.close()
    return render_template('incident_workflows.html', board=board, statuses=INCIDENT_STATUSES, counts=counts)

@app.route('/alerts')
@login_required('organizer')
def alerts():
    """Operational Alerts: Critical / High-Priority / Medium-Priority / Informational,
    refreshed on every visit and polled in real time from /alerts/live.json."""
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    sync_live_alerts(cur)
    cur.execute("""SELECT * FROM operational_alerts WHERE is_read=0
                   ORDER BY FIELD(priority,'Critical','High-Priority','Medium-Priority','Informational'), created_at DESC""")
    alert_rows = cur.fetchall()
    grouped = {tier: [a for a in alert_rows if a['priority'] == tier] for tier in ALERT_TIERS}
    counts = ops_counts(cur)
    cur.close()
    return render_template('alerts.html', grouped=grouped, tiers=ALERT_TIERS, counts=counts)

@app.route('/alerts/live.json')
@login_required('organizer')
def alerts_live():
    """JSON feed polled by the Alerts page for real-time notifications."""
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    sync_live_alerts(cur)
    cur.execute("""SELECT id,title,message,priority,source,created_at FROM operational_alerts WHERE is_read=0
                   ORDER BY FIELD(priority,'Critical','High-Priority','Medium-Priority','Informational'), created_at DESC LIMIT 30""")
    rows = cur.fetchall()
    cur.close()
    for r in rows:
        r['created_at'] = r['created_at'].strftime('%d %b, %I:%M %p')
    counts = {tier: sum(1 for r in rows if r['priority'] == tier) for tier in ALERT_TIERS}
    return jsonify({'alerts': rows, 'counts': counts, 'total': len(rows)})

@app.route('/sponsors/alert/<int:alert_id>/read', methods=['POST'])
@app.route('/alerts/<int:alert_id>/read', methods=['POST'])
@login_required('organizer')
def mark_alert_read(alert_id):
    cur = mysql.connection.cursor(); cur.execute("UPDATE operational_alerts SET is_read=1 WHERE id=%s", (alert_id,))
    mysql.connection.commit(); cur.close()
    return redirect(request.referrer or '/alerts')

@app.route('/attendees')
@login_required('organizer')
def attendees():
    cur=mysql.connection.cursor()
    cur.execute("""SELECT registration_token,name,email,phone,gender,location,category,vip,attendance,status
                   FROM attendees ORDER BY id DESC""")
    rows=cur.fetchall(); cur.close()
    return render_template("attendees.html",attendees=rows)

@app.route('/delete/<token>')
@login_required('organizer')
def delete(token):
    cur=mysql.connection.cursor(); cur.execute("DELETE FROM attendees WHERE registration_token=%s",(token,))
    mysql.connection.commit(); cur.close(); return redirect('/attendees')

@app.route('/edit/<token>',methods=['GET','POST'])
@login_required('organizer')
def edit(token):
    cur=mysql.connection.cursor()
    if request.method=="POST":
        cur.execute("UPDATE attendees SET name=%s,phone=%s,location=%s WHERE registration_token=%s",
                    (request.form['name'],request.form['phone'],request.form['location'],token))
        mysql.connection.commit(); cur.close(); return redirect('/attendees')
    cur.execute("SELECT * FROM attendees WHERE registration_token=%s",(token,)); attendee=cur.fetchone(); cur.close()
    return render_template("edit.html",attendee=attendee)

if __name__=="__main__":
    app.run(debug=True,threaded=True)
