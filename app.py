import os
import sys
import uuid
import datetime
import requests
import json
import threading
import time
import shutil
import ipaddress
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, flash, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.types import TypeDecorator, DateTime as _DateTime
from datetime import timedelta

# ---------------- SafeDateTime ----------------
class SafeDateTime(TypeDecorator):
    """DateTime, das leere Strings als NULL interpretiert."""
    impl = _DateTime
    def process_bind_param(self, value, dialect):
        return value
    def process_result_value(self, value, dialect):
        # Wird nach dem Lesen aus der DB aufgerufen
        if value is None or value == '':
            return None
        return value

# ---------------- App-Setup ----------------
DATABASE_URI = os.environ.get('DATABASE_URI', 'sqlite:////data/licenses.db')
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'))
PORT = int(os.environ.get('PORT', 5200))
SECRET_KEY = os.environ.get('SECRET_KEY', '123456')
BASE_DOMAIN = os.environ.get('BASE_DOMAIN', 'https://localhost')
USERNAME = os.environ.get('USERNAME', 'admin')
PASSWORD = os.environ.get('PASSWORD', 'admin')

if not os.path.exists('/data'):
    os.makedirs('/data')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

BASE_DIR = os.path.abspath(".")
app = Flask(__name__, static_folder=BASE_DIR, template_folder=BASE_DIR)
app.config.update(
    SQLALCHEMY_DATABASE_URI=DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    SECRET_KEY=SECRET_KEY
)
# ProxyFix für X-Forwarded-For / X-Forwarded-Proto
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ---------------- Common HTML ----------------
HEADER_HTML = '''
<header style="display:flex;align-items:center;justify-content:center;background:#f8f9fa;padding:10px">
  <span style="font-size:24px;font-weight:bold;margin-right:5px">Lizens</span>
  <img src="https://raw.githubusercontent.com/mrder/lizenzmanager/refs/heads/main/icon.png" style="max-height:60px;margin:0 5px">
  <span style="font-size:24px;font-weight:bold;margin-left:5px">Manager</span>
</header>
'''
FOOTER_HTML = '''
<footer style="display:flex;justify-content:center;align-items:center;background:#f8f9fa;padding:10px;margin-top:20px">
  <img src="https://s20.directupload.net/images/240723/oejqar3j.png" style="max-height:40px;margin-right:5px">
  <p style="margin:0">&copy; sonnyathome.online Version 1.1</p>
</footer>
'''

# -------------------- Modelle --------------------
class License(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    owner            = db.Column(db.String(120))
    client_id        = db.Column(db.String(120), unique=True, nullable=False)
    license_key      = db.Column(db.String(120), unique=True, nullable=False)
    acquired_at      = db.Column(SafeDateTime, default=datetime.datetime.utcnow)
    contact          = db.Column(db.String(120))
    last_login_at    = db.Column(SafeDateTime)
    last_login_ip    = db.Column(db.String(120))
    error_counter    = db.Column(db.Integer, default=0)
    tool             = db.Column(db.String(120))
    expiry_date      = db.Column(SafeDateTime)
    client_version   = db.Column(db.String(20))
    error_logs       = db.relationship(
        'ErrorLog',
        backref='license',
        lazy=True,
        cascade='all, delete-orphan',
        passive_deletes=True
    )

class ErrorLog(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    license_id   = db.Column(db.Integer, db.ForeignKey('license.id', ondelete='CASCADE'), nullable=True)
    timestamp    = db.Column(SafeDateTime, default=datetime.datetime.utcnow)
    message      = db.Column(db.String(255))

class ToolUpdate(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    tool             = db.Column(db.String(120), nullable=False)
    version          = db.Column(db.String(20), nullable=False)
    download_count   = db.Column(db.Integer, default=0)
    last_download_at = db.Column(SafeDateTime)
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
    def wf(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return wf

def get_client_ip():
    # 1) JSON-Payload "ClientIP"
    if request.json and request.json.get('ClientIP'):
        return request.json['ClientIP']
    # 2) X-Forwarded-For / X-Real-IP – erste öffentliche
    header = request.headers.get('X-Forwarded-For') or request.headers.get('X-Real-IP')
    if header:
        for ip in [h.strip() for h in header.split(',')]:
            if is_public_ip(ip):
                return ip
        return header.split(',')[0].strip()
    # 3) Fallback
    return request.remote_addr

# -------------------- Lizenz-API --------------------
@app.route('/api/verify', methods=['POST'])
def verify_license():
    data        = request.get_json() or {}
    client_id   = data.get('ClientID')
    license_key = data.get('Lizenz')
    client_ver  = data.get('Version')
    client_ip   = get_client_ip()

    lic = License.query.filter_by(client_id=client_id, license_key=license_key).first()
    if not lic:
        # Invalid license
        by_client = License.query.filter_by(client_id=client_id).first()
        log = ErrorLog(
            license_id=by_client.id if by_client else None,
            message=f"Ungültige Lizenzdaten: ClientID {client_id}, Lizenz {license_key}"
        )
        db.session.add(log); db.session.commit()
        return jsonify(Lizenzstatus=False, Ablaufdatum=None, Nachricht='Ungültige Lizenzdaten')

    if client_ver:
        lic.client_version = client_ver

    now = datetime.datetime.utcnow()
    # 1) expired?
    if lic.expiry_date and lic.expiry_date < now:
        lic.error_counter += 1
        db.session.add(ErrorLog(license_id=lic.id, message="Lizenz abgelaufen"))
        db.session.commit()
        return jsonify(Lizenzstatus=False, Ablaufdatum=lic.expiry_date.strftime('%d.%m.%Y'), Nachricht='Lizenz abgelaufen')

    # 2) double IP? nur wenn beide IPs öffentlich sind
    old_ip = lic.last_login_ip
    if old_ip and old_ip != client_ip and is_public_ip(old_ip) and is_public_ip(client_ip):
        lic.error_counter += 1
        db.session.add(ErrorLog(license_id=lic.id, message="Double IP Login"))
        db.session.commit()
        msg_date = lic.expiry_date.strftime('%d.%m.%Y') if lic.expiry_date else None
        return jsonify(Lizenzstatus=False, Ablaufdatum=msg_date, Nachricht='Double IP Login')

    # OK – Login updaten
    lic.last_login_at  = now
    lic.last_login_ip  = client_ip

    # Update-Check
    ui = dict(UpdateAvailable=False, LatestVersion=None, UpdateURL=None)
    if lic.tool and lic.client_version:
        tu = ToolUpdate.query.filter_by(tool=lic.tool).order_by(ToolUpdate.id.desc()).first()
        if tu and is_newer_version(lic.client_version, tu.version):
            ui = dict(UpdateAvailable=True, LatestVersion=tu.version, UpdateURL=tu.update_url)

    db.session.commit()
    return jsonify(Lizenzstatus=True,
                   Ablaufdatum=lic.expiry_date.strftime('%d.%m.%Y') if lic.expiry_date else None,
                   Nachricht=None,
                   **ui)

# -------------------- Fehler quittieren --------------------
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

# -------------------- Backup-Routen --------------------
@app.route('/backup/download')
@login_required
def backup_download():
    if DATABASE_URI.startswith("sqlite:///"):
        db_path = DATABASE_URI.replace("sqlite:///", "", 1)
    else:
        db_path = os.path.join(BASE_DIR, "licenses.db")
    return send_from_directory(os.path.dirname(db_path),
                               os.path.basename(db_path),
                               as_attachment=True,
                               download_name="licenses.db")

@app.route('/backup/upload', methods=['GET','POST'])
@login_required
def backup_upload():
    if request.method == 'POST':
        if 'backup_file' not in request.files:
            flash("Keine Datei ausgewählt")
            return redirect(request.url)
        f = request.files['backup_file']
        if not f.filename.lower().endswith('.db'):
            flash("Nur .db-Dateien erlaubt"); return redirect(request.url)
        tmp = os.path.join(UPLOAD_FOLDER, "temp.db")
        f.save(tmp)
        target = DATABASE_URI.replace("sqlite:////","/data/") if DATABASE_URI.startswith("sqlite:///") else os.path.join(BASE_DIR,"licenses.db")
        db.session.remove()
        try:
            shutil.copy(tmp, target)
            flash("Backup erfolgreich wiederhergestellt. Bitte App neu starten.")
        except Exception as e:
            flash(f"Fehler beim Wiederherstellen: {e}")
        finally:
            os.remove(tmp)
        return redirect(url_for('dashboard'))

    upload_form = '''
    <!doctype html><html lang="de"><head><meta charset="utf-8"><title>Backup hochladen</title>
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>''' + HEADER_HTML + '''
      <div class="container">
        <h1 class="mt-4">Backup hochladen</h1>
        <form method="post" enctype="multipart/form-data">
          <div class="form-group">
            <label>Backup (.db):</label>
            <input type="file" name="backup_file" class="form-control-file" required>
          </div>
          <button class="btn btn-primary">Wiederherstellen</button>
        </form>
        <br><a href="{{ url_for('dashboard') }}" class="btn btn-secondary">Dashboard</a>
      </div>''' + FOOTER_HTML + '''
    </body></html>
    '''
    return render_template_string(upload_form)

# -------------------- Login/Logout --------------------
login_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Login</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>''' + HEADER_HTML + '''
  <div class="container">
    <h1 class="mt-4">Login</h1>
    {% with msgs = get_flashed_messages() %}{% for m in msgs %}<div class="alert alert-danger">{{ m }}</div>{% endfor %}{% endwith %}
    <form method="post">
      <div class="form-group"><label>Nutzername:</label><input name="username" class="form-control"></div>
      <div class="form-group"><label>Passwort:</label><input name="password" type="password" class="form-control"></div>
      <button class="btn btn-primary">Anmelden</button>
    </form>
  </div>''' + FOOTER_HTML + '''
</body></html>
'''

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST' and request.form.get('username')==USERNAME and request.form.get('password')==PASSWORD:
        session['logged_in']=True
        return redirect(url_for('dashboard'))
    if request.method=='POST':
        flash("Ungültige Anmeldedaten")
    return render_template_string(login_template)

@app.route('/logout')
def logout():
    session.pop('logged_in',None)
    return redirect(url_for('login'))

# -------------------- Dashboard & Lizenzverwaltung --------------------
dashboard_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Lizenz Dashboard</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>''' + HEADER_HTML + '''
  <div class="container">
    <div class="d-flex justify-content-between align-items-center mt-4">
      <h1>Lizenz Dashboard</h1>
      <a href="{{ url_for('logout') }}" class="btn btn-secondary">Logout</a>
    </div>
    <div class="mb-3">
      <a href="{{ url_for('generate_license') }}" class="btn btn-primary">Generieren</a>
      <a href="{{ url_for('add_license') }}" class="btn btn-success">Hinzufügen</a>
      <a href="{{ url_for('updates') }}" class="btn btn-info">Updates</a>
      <a href="{{ url_for('backup_download') }}" class="btn btn-warning">Backup ↓</a>
      <a href="{{ url_for('backup_upload') }}" class="btn btn-warning">Backup ↑</a>
    </div>
    <table class="table table-striped table-bordered">
      <thead><tr>
        <th>ID</th><th>Inhaber</th><th>ClientID</th><th>Lizenz</th><th>Erw.</th>
        <th>Kontakt</th><th>Letzter Login</th><th>Login IP</th><th>Fehler</th>
        <th>Tool</th><th>Ablauf</th><th>Version</th><th>Aktionen</th>
      </tr></thead><tbody>
    {% for lic in licenses %}
      <tr>
        <td>{{ lic.id }}</td>
        <td>{{ lic.owner or '' }}</td>
        <td>{{ lic.client_id }}</td>
        <td>{{ lic.license_key }}</td>
        <td>{{ lic.acquired_at.strftime('%d.%m.%Y %H:%M:%S') if lic.acquired_at else '' }}</td>
        <td>{{ lic.contact or '' }}</td>
        <td>{{ lic.last_login_at.strftime('%d.%m.%Y %H:%M:%S') if lic.last_login_at else '' }}</td>
        <td>{{ lic.last_login_ip or '' }}</td>
        <td><a href="{{ url_for('error_log', license_id=lic.id) }}">{{ lic.error_counter }}</a></td>
        <td>{{ lic.tool or '' }}</td>
        <td>{{ lic.expiry_date.strftime('%d.%m.%Y') if lic.expiry_date else '' }}</td>
        <td>{{ lic.client_version or '' }}</td>
        <td>
          <a href="{{ url_for('edit_license',license_id=lic.id) }}" class="btn btn-warning btn-sm">Edit</a>
          <a href="{{ url_for('delete_license',license_id=lic.id) }}" class="btn btn-danger btn-sm" onclick="return confirm('Wirklich löschen?');">Del</a>
        </td>
      </tr>
    {% endfor %}
      </tbody>
    </table>
  </div>''' + FOOTER_HTML + '''
</body></html>
'''

add_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Neue Lizenz</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>''' + HEADER_HTML + '''
  <div class="container">
    <h1 class="mt-4">Neue Lizenz</h1>
    <form method="post">
      <div class="form-group"><label>Inhaber:</label><input name="owner" class="form-control"></div>
      <div class="form-group"><label>Kontakt:</label><input name="contact" class="form-control"></div>
      <div class="form-group"><label>Tool:</label><input name="tool" class="form-control"></div>
      <div class="form-group"><label>Ablauf (TT.MM.JJJJ):</label><input name="expiry_date" class="form-control"></div>
      <button class="btn btn-success">Hinzufügen</button>
    </form><br>
    <a href="{{ url_for('dashboard') }}" class="btn btn-secondary">Zurück</a>
  </div>''' + FOOTER_HTML + '''
</body></html>
'''

edit_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Edit Lizenz</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>''' + HEADER_HTML + '''
  <div class="container">
    <h1 class="mt-4">Edit Lizenz</h1>
    <form method="post">
      <div class="form-group"><label>Inhaber:</label><input name="owner" class="form-control" value="{{ license.owner }}"></div>
      <div class="form-group"><label>Kontakt:</label><input name="contact" class="form-control" value="{{ license.contact }}"></div>
      <div class="form-group"><label>Tool:</label><input name="tool" class="form-control" value="{{ license.tool }}"></div>
      <div class="form-group"><label>Ablauf:</label><input name="expiry_date" class="form-control" value="{{ license.expiry_date.strftime('%d.%m.%Y') if license.expiry_date else '' }}"></div>
      <button class="btn btn-success">Speichern</button>
    </form><br>
    <a href="{{ url_for('dashboard') }}" class="btn btn-secondary">Zurück</a>
  </div>''' + FOOTER_HTML + '''
</body></html>
'''

error_log_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Fehlerlog {{ license.client_id }}</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>''' + HEADER_HTML + '''
  <div class="container">
    <h1 class="mt-4">Fehlerlog {{ license.client_id }}</h1>
    <div class="mb-3">
      <a href="{{ url_for('dashboard') }}" class="btn btn-secondary">Zurück</a>
      <a href="{{ url_for('ack_error', license_id=license.id) }}" class="btn btn-success">Fehler quittieren</a>
    </div>
    <table class="table table-bordered">
      <thead><tr><th>ID</th><th>Time</th><th>Nachricht</th></tr></thead>
      <tbody>{% for log in error_logs %}
        <tr><td>{{ log.id }}</td><td>{{ log.timestamp.strftime('%d.%m.%Y %H:%M:%S') }}</td><td>{{ log.message }}</td></tr>
      {% endfor %}</tbody>
    </table>
  </div>''' + FOOTER_HTML + '''
</body></html>
'''

# -------------------- Update Manager --------------------
update_dashboard_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Update Manager</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>''' + HEADER_HTML + '''
  <div class="container">
    <a href="{{ url_for('dashboard') }}" class="btn btn-secondary mb-3">← Dashboard</a>
    <a href="{{ url_for('upload_update') }}" class="btn btn-success mb-3">Neues Update</a>
    {% for tool, ups in grouped_updates.items() %}
      <h3 class="mt-4">{{ tool }}</h3>
      <table class="table table-striped table-bordered">
        <thead><tr><th>ID</th><th>Version</th><th>Count</th><th>Letzter DL</th><th>URL</th><th>Aktion</th></tr></thead><tbody>
        {% for u in ups %}
          <tr>
            <td>{{ u.id }}</td><td>{{ u.version }}</td><td>{{ u.download_count }}</td>
            <td>{{ u.last_download_at.strftime('%d.%m.%Y %H:%M:%S') if u.last_download_at else '' }}</td>
            <td><a href="{{ u.update_url }}" target="_blank">Link</a></td>
            <td>
              <a href="{{ url_for('download_update', update_id=u.id) }}" class="btn btn-primary btn-sm">DL</a>
              <a href="{{ url_for('delete_update', update_id=u.id) }}" class="btn btn-danger btn-sm" onclick="return confirm('Löschen?');">Del</a>
            </td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    {% endfor %}
  </div>''' + FOOTER_HTML + '''
</body></html>
'''

upload_update_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Update hochladen</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>''' + HEADER_HTML + '''
  <div class="container">
    <h1 class="mt-4">Neues Update</h1>
    <form method="post" enctype="multipart/form-data">
      <div class="form-group"><label>Tool:</label><input name="tool" class="form-control" required></div>
      <div class="form-group"><label>Version:</label><input name="version" class="form-control" required></div>
      <div class="form-group"><label>Link (opt):</label><input name="external_link" class="form-control" placeholder="https://..."></div>
      <div class="form-group"><label>Datei (zip):</label><input type="file" name="update_file" class="form-control-file"></div>
      <button class="btn btn-primary">Hochladen</button>
    </form><br>
    <a href="{{ url_for('updates') }}" class="btn btn-secondary">← Updates</a>
  </div>''' + FOOTER_HTML + '''
</body></html>
'''

@app.route('/updates')
@login_required
def updates():
    ups = ToolUpdate.query.order_by(ToolUpdate.tool, ToolUpdate.id.desc()).all()
    grouped = {}
    for u in ups:
        grouped.setdefault(u.tool, []).append(u)
    return render_template_string(update_dashboard_template, grouped_updates=grouped)

@app.route('/upload_update', methods=['GET','POST'])
@login_required
def upload_update():
    if request.method=='POST':
        tool = request.form.get('tool')
        version = request.form.get('version')
        link = request.form.get('external_link')
        file = request.files.get('update_file')
        if not file and not link:
            flash("Datei oder Link angeben"); return redirect(url_for('upload_update'))
        if file:
            fn = secure_filename(file.filename)
            uf = f"{uuid.uuid4().hex}_{fn}"
            path = os.path.join(app.config['UPLOAD_FOLDER'], uf)
            file.save(path)
            url = f"{BASE_DOMAIN}/uploads/{uf}"
        else:
            url = link
        tu = ToolUpdate(tool=tool,version=version,update_url=url)
        db.session.add(tu); db.session.commit()
        flash("Update geladen"); return redirect(url_for('updates'))
    return render_template_string(upload_update_template)

@app.route('/download_update/<int:update_id>')
@login_required
def download_update(update_id):
    tu = ToolUpdate.query.get_or_404(update_id)
    tu.download_count += 1
    tu.last_download_at = datetime.datetime.utcnow()
    db.session.commit()
    return redirect(tu.update_url)

@app.route('/delete_update/<int:update_id>')
@login_required
def delete_update(update_id):
    tu = ToolUpdate.query.get_or_404(update_id)
    if tu.update_url.startswith(BASE_DOMAIN):
        fn = tu.update_url.rsplit('/',1)[-1]
        p = os.path.join(app.config['UPLOAD_FOLDER'], fn)
        if os.path.exists(p): os.remove(p)
    db.session.delete(tu); db.session.commit()
    flash("Update gelöscht"); return redirect(url_for('updates'))

# -------------------- Lizenz CRUD --------------------
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    licenses = License.query.all()
    return render_template_string(dashboard_template, licenses=licenses)

@app.route('/add', methods=['GET','POST'])
@login_required
def add_license():
    if request.method=='POST':
        owner = request.form.get('owner')
        contact = request.form.get('contact')
        tool    = request.form.get('tool')
        eds     = request.form.get('expiry_date')
        try:
            ed = datetime.datetime.strptime(eds, '%d.%m.%Y') if eds else None
        except:
            ed = None
        cid = uuid.uuid4().hex
        key = uuid.uuid4().hex
        nl = License(owner=owner,contact=contact,tool=tool,
                     expiry_date=ed,client_id=cid,license_key=key)
        db.session.add(nl); db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template_string(add_template)

@app.route('/edit/<int:license_id>', methods=['GET','POST'])
@login_required
def edit_license(license_id):
    lic = License.query.get_or_404(license_id)
    if request.method=='POST':
        lic.owner = request.form.get('owner')
        lic.contact = request.form.get('contact')
        lic.tool = request.form.get('tool')
        eds = request.form.get('expiry_date')
        try:
            lic.expiry_date = datetime.datetime.strptime(eds, '%d.%m.%Y') if eds else None
        except:
            lic.expiry_date = None
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template_string(edit_template, license=lic)

@app.route('/delete/<int:license_id>')
@login_required
def delete_license(license_id):
    lic = License.query.get_or_404(license_id)
    db.session.delete(lic); db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/generate_license')
@login_required
def generate_license():
    cid = uuid.uuid4().hex
    key = uuid.uuid4().hex
    exp = datetime.datetime.utcnow()+timedelta(days=365)
    nl = License(client_id=cid,license_key=key,expiry_date=exp)
    db.session.add(nl); db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/error_log/<int:license_id>')
@login_required
def error_log(license_id):
    lic = License.query.get_or_404(license_id)
    logs = ErrorLog.query.filter_by(license_id=license_id).order_by(ErrorLog.timestamp.desc()).all()
    return render_template_string(error_log_template, license=lic, error_logs=logs)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=PORT, debug=True)
