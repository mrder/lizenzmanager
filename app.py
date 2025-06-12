# app.py
import os
import uuid
import datetime
import shutil
import sqlite3
import ipaddress

from flask import (
    Flask, request, jsonify,
    render_template, redirect, url_for,
    session, flash, send_from_directory
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from functools import wraps
from datetime import timedelta

# -------------------- Konfiguration --------------------
DATABASE_URI = os.environ.get('DATABASE_URI', 'sqlite:////data/licenses.db')
UPLOAD_FOLDER = os.environ.get(
    'UPLOAD_FOLDER',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
)
PORT                 = int(os.environ.get('PORT', 5200))
SECRET_KEY           = os.environ.get('SECRET_KEY', '123456')
BASE_DOMAIN          = os.environ.get('BASE_DOMAIN', 'https://localhost')
USERNAME             = os.environ.get('USERNAME', 'admin')
PASSWORD             = os.environ.get('PASSWORD', 'admin')
IP_MISMATCH_THRESHOLD = 2  # Anzahl erlaubter IP-Wechsel ohne Block

# ---------------- Variablen ----------------------------
APP_VERSION = '1.1'

# Ordner anlegen
for d in ['/data', UPLOAD_FOLDER]:
    if not os.path.exists(d):
        os.makedirs(d)

# Flask / DB Setup
app = Flask(__name__, static_folder='static')
app.config.update(
    SQLALCHEMY_DATABASE_URI=DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    SECRET_KEY=SECRET_KEY
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# -------------------- Modelle --------------------
class License(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    owner            = db.Column(db.String(120))
    client_id        = db.Column(db.String(120), unique=True, nullable=False)
    license_key      = db.Column(db.String(120), unique=True, nullable=False)
    acquired_at      = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    contact          = db.Column(db.String(120))
    last_login_at    = db.Column(db.DateTime)
    last_login_ip    = db.Column(db.String(120))
    last_login_mac   = db.Column(db.String(120))
    error_counter    = db.Column(db.Integer, default=0)
    tool             = db.Column(db.String(120))
    expiry_date      = db.Column(db.DateTime)
    client_version   = db.Column(db.String(20))
    error_logs       = db.relationship(
        'ErrorLog', backref='license',
        lazy=True, cascade='all, delete-orphan'
    )

class ErrorLog(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    license_id = db.Column(
        db.Integer,
        db.ForeignKey('license.id', ondelete='CASCADE'),
        nullable=True
    )
    timestamp  = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    message    = db.Column(db.String(255))

class ToolUpdate(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    tool             = db.Column(db.String(120), nullable=False)
    version          = db.Column(db.String(20), nullable=False)
    download_count   = db.Column(db.Integer, default=0)
    last_download_at = db.Column(db.DateTime)
    update_url       = db.Column(db.String(255))

# -------------------- Hilfsfunktionen --------------------
def is_newer_version(client_ver, latest_ver):
    try:
        return tuple(map(int, latest_ver.split('.'))) > tuple(map(int, client_ver.split('.')))
    except:
        return False

def is_public_ip(ip):
    try:
        addr = ipaddress.ip_address(ip)
        return not addr.is_private and not addr.is_loopback
    except:
        return False

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return wrapper

def get_client_ip():
    if request.json and request.json.get('ClientIP'):
        return request.json['ClientIP']
    hdr = request.headers.get('X-Forwarded-For') or request.headers.get('X-Real-IP')
    if hdr:
        for ip in hdr.split(','):
            ip = ip.strip()
            if is_public_ip(ip):
                return ip
        return hdr.split(',')[0].strip()
    return request.remote_addr

# -------------------- API: Lizenz-Verifizierung --------------------
@app.route('/api/verify', methods=['POST'])
def verify_license():
    data           = request.get_json() or {}
    client_id      = data.get('ClientID')
    license_key    = data.get('Lizenz')
    client_version = data.get('Version')
    client_ip      = get_client_ip()
    client_mac     = data.get('ClientMAC')

    lic = License.query.filter_by(
        client_id=client_id, license_key=license_key
    ).first()
    if not lic:
        alt = License.query.filter_by(client_id=client_id).first()
        db.session.add(ErrorLog(
            license_id=alt.id if alt else None,
            message=f"Ungültige Lizenzdaten: {client_id}/{license_key}"
        ))
        db.session.commit()
        return jsonify(Lizenzstatus=False, Ablaufdatum=None, Nachricht='Ungültige Lizenzdaten')

    # Version updaten
    if client_version:
        lic.client_version = client_version

    now = datetime.datetime.utcnow()
    # Ablaufdatum prüfen
    if lic.expiry_date and lic.expiry_date < now:
        lic.error_counter += 1
        db.session.add(ErrorLog(license_id=lic.id, message="Lizenz abgelaufen"))
        db.session.commit()
        return jsonify(
            Lizenzstatus=False,
            Ablaufdatum=lic.expiry_date.strftime('%d.%m.%Y'),
            Nachricht='Lizenz abgelaufen'
        )

    # Double-Login-Check mit Threshold
    prev_ip  = lic.last_login_ip
    prev_mac = lic.last_login_mac
    if prev_ip and prev_ip != client_ip \
       and is_public_ip(prev_ip) and is_public_ip(client_ip):
        if not client_mac or not prev_mac or client_mac != prev_mac:
            lic.error_counter += 1
            db.session.add(ErrorLog(license_id=lic.id, message="Double IP+MAC Login"))
            db.session.commit()
            if lic.error_counter >= IP_MISMATCH_THRESHOLD:
                return jsonify(
                    Lizenzstatus=False,
                    Ablaufdatum=lic.expiry_date.strftime('%d.%m.%Y') if lic.expiry_date else None,
                    Nachricht='Double IP Login'
                )
            else:
                remaining = IP_MISMATCH_THRESHOLD - lic.error_counter
                return jsonify(
                    Lizenzstatus=True,
                    Ablaufdatum=lic.expiry_date.strftime('%d.%m.%Y') if lic.expiry_date else None,
                    Nachricht=f"Warnung: IP-Wechsel – noch {remaining} bis Block."
                )

    # Login-Daten speichern
    lic.last_login_at  = now
    lic.last_login_ip  = client_ip
    if client_mac:
        lic.last_login_mac = client_mac

    # Update-Info
    upd = ToolUpdate.query.filter_by(tool=lic.tool) \
            .order_by(ToolUpdate.id.desc()).first()
    update_info = {"UpdateAvailable": False, "LatestVersion": None, "UpdateURL": None}
    if upd and lic.client_version and is_newer_version(lic.client_version, upd.version):
        update_info = {
            "UpdateAvailable": True,
            "LatestVersion": upd.version,
            "UpdateURL": upd.update_url
        }

    db.session.commit()
    resp = {
        'Lizenzstatus': True,
        'Ablaufdatum': lic.expiry_date.strftime('%d.%m.%Y') if lic.expiry_date else None,
        'Nachricht': None
    }
    resp.update(update_info)
    return jsonify(resp)

# -------------------- Auth & Dashboard --------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == USERNAME and request.form.get('password') == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        flash("Ungültiger Nutzername oder Passwort")
    return render_template(
        'login.html',
        active_page='login',
        current_year=datetime.datetime.utcnow().year,
        app_version=APP_VERSION
    )

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    licenses = License.query.all()
    return render_template(
        'dashboard.html',
        licenses=licenses,
        active_page='dashboard',
        current_year=datetime.datetime.utcnow().year,
        app_version=APP_VERSION
    )

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_license():
    if request.method == 'POST':
        expiry_str = request.form.get('expiry_date')
        try:
            expiry = datetime.datetime.strptime(expiry_str, '%d.%m.%Y')
        except:
            expiry = None
        new = License(
            owner=request.form.get('owner'),
            contact=request.form.get('contact'),
            tool=request.form.get('tool'),
            expiry_date=expiry,
            client_id=uuid.uuid4().hex,
            license_key=uuid.uuid4().hex
        )
        db.session.add(new)
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template(
        'add_license.html',
        active_page='add',
        current_year=datetime.datetime.utcnow().year,
        app_version=APP_VERSION
    )

@app.route('/edit/<int:license_id>', methods=['GET', 'POST'])
@login_required
def edit_license(license_id):
    lic = License.query.get_or_404(license_id)
    if request.method == 'POST':
        lic.owner = request.form.get('owner')
        lic.contact = request.form.get('contact')
        lic.tool    = request.form.get('tool')
        try:
            lic.expiry_date = datetime.datetime.strptime(request.form.get('expiry_date'), '%d.%m.%Y')
        except:
            lic.expiry_date = None
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template(
        'edit_license.html',
        license=lic,
        active_page='edit',
        current_year=datetime.datetime.utcnow().year,
        app_version=APP_VERSION
    )

@app.route('/delete/<int:license_id>')
@login_required
def delete_license(license_id):
    db.session.delete(License.query.get_or_404(license_id))
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/generate_license')
@login_required
def generate_license():
    lic = License(
        client_id   = uuid.uuid4().hex,
        license_key = uuid.uuid4().hex,
        expiry_date = datetime.datetime.utcnow() + timedelta(days=365)
    )
    db.session.add(lic)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/error_log/<int:license_id>')
@login_required
def error_log(license_id):
    lic = License.query.get_or_404(license_id)
    logs = ErrorLog.query.filter_by(license_id=license_id) \
            .order_by(ErrorLog.timestamp.desc()).all()
    return render_template(
        'error_log.html',
        license=lic,
        error_logs=logs,
        active_page='error_log',
        current_year=datetime.datetime.utcnow().year,
        app_version=APP_VERSION
    )

@app.route('/error_log/ack/<int:license_id>')
@login_required
def ack_error(license_id):
    lic = License.query.get_or_404(license_id)
    lic.last_login_ip = None
    lic.error_counter = 0
    ErrorLog.query.filter_by(license_id=license_id).delete()
    db.session.commit()
    flash("Fehlerlogs und IP-Block zurückgesetzt.")
    return redirect(url_for('error_log', license_id=license_id))

# -------------------- Backup --------------------
@app.route('/backup/download')
@login_required
def backup_download():
    if DATABASE_URI.startswith("sqlite:///"):
        path = DATABASE_URI.replace("sqlite:///", "", 1)
    else:
        path = os.path.join(os.path.abspath('.'), 'licenses.db')
    return send_from_directory(
        os.path.dirname(path),
        os.path.basename(path),
        as_attachment=True,
        download_name="licenses.db"
    )

@app.route('/backup/upload', methods=['GET', 'POST'])
@login_required
def backup_upload():
    if request.method == 'POST':
        file = request.files.get('backup_file')
        if not file or not file.filename.lower().endswith('.db'):
            flash("Bitte eine .db-Datei auswählen.")
            return redirect(request.url)

        tmp_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp.db')
        file.save(tmp_path)
        db_path = DATABASE_URI.replace("sqlite:///", "", 1)
        db.session.remove()

        try:
            # 1) Backup in die Live-DB kopieren
            shutil.copy(tmp_path, db_path)

            # 2) Schema anpassen, falls Spalte fehlt
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cols = [row[1] for row in cur.execute("PRAGMA table_info(license)").fetchall()]
            if 'last_login_mac' not in cols:
                cur.execute("ALTER TABLE license ADD COLUMN last_login_mac VARCHAR(120)")
            # 3) Deine bisherigen Cleanup-Updates
            cur.execute("UPDATE license SET last_login_at = NULL WHERE last_login_at = ''")
            cur.execute("UPDATE license SET expiry_date    = NULL WHERE expiry_date    = ''")
            conn.commit()
            conn.close()

            flash("Backup erfolgreich wiederhergestellt. Bitte starten Sie die Anwendung neu.")
        except Exception as e:
            flash(f"Fehler beim Wiederherstellen des Backups: {e}")
        finally:
            os.remove(tmp_path)

        return redirect(url_for('dashboard'))

    return render_template(
        'backup_upload.html',
        active_page='backup_upload',
        current_year=datetime.datetime.utcnow().year,
        app_version=APP_VERSION
    )


# -------------------- Update Manager --------------------
@app.route('/updates')
@login_required
def updates():
    all_upd = ToolUpdate.query.order_by(ToolUpdate.tool, ToolUpdate.id.desc()).all()
    grouped = {}
    for u in all_upd:
        grouped.setdefault(u.tool, []).append(u)
    return render_template(
        'update_manager.html',
        grouped_updates=grouped,
        active_page='updates',
        current_year=datetime.datetime.utcnow().year,
        app_version=APP_VERSION
    )

@app.route('/upload_update', methods=['GET', 'POST'])
@login_required
def upload_update():
    if request.method == 'POST':
        tool    = request.form.get('tool')
        version = request.form.get('version')
        link    = request.form.get('external_link')
        file    = request.files.get('update_file')
        if not link and not file:
            flash("Datei oder Link erforderlich.")
            return redirect(request.url)
        if file:
            fn = secure_filename(file.filename)
            uid = f"{uuid.uuid4().hex}_{fn}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], uid))
            url = f"{BASE_DOMAIN}/uploads/{uid}"
        else:
            url = link
        db.session.add(ToolUpdate(tool=tool, version=version, update_url=url))
        db.session.commit()
        flash("Update hochgeladen.")
        return redirect(url_for('updates'))
    return render_template(
        'upload_update.html',
        active_page='upload_update',
        current_year=datetime.datetime.utcnow().year,
        app_version=APP_VERSION
    )

@app.route('/download_update/<int:update_id>')
@login_required
def download_update(update_id):
    u = ToolUpdate.query.get_or_404(update_id)
    u.download_count += 1
    u.last_download_at = datetime.datetime.utcnow()
    db.session.commit()
    return redirect(u.update_url)

@app.route('/delete_update/<int:update_id>')
@login_required
def delete_update(update_id):
    u = ToolUpdate.query.get_or_404(update_id)
    if u.update_url.startswith(BASE_DOMAIN):
        fn = u.update_url.rsplit('/', 1)[-1]
        path = os.path.join(app.config['UPLOAD_FOLDER'], fn)
        if os.path.exists(path):
            os.remove(path)
    db.session.delete(u)
    db.session.commit()
    flash("Update gelöscht.")
    return redirect(url_for('updates'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
