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
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, flash, send_from_directory, render_template
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import timedelta

# Persistente Datenbank-URI: Falls nicht gesetzt, wird die DB unter /data/licenses.db abgelegt.
DATABASE_URI = os.environ.get('DATABASE_URI', 'sqlite:////data/licenses.db')

# Weitere Umgebungsvariablen mit Defaults
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'))
PORT = int(os.environ.get('PORT', 5200))
SECRET_KEY = os.environ.get('SECRET_KEY', '123456')
BASE_DOMAIN = os.environ.get('BASE_DOMAIN', 'https://localhost')
USERNAME = os.environ.get('USERNAME', 'admin')
PASSWORD = os.environ.get('PASSWORD', 'admin')

# Sicherstellen, dass das persistente Verzeichnis für die DB existiert
db_dir = '/data'
if not os.path.exists(db_dir):
    os.makedirs(db_dir)

# Sicherstellen, dass der Upload-Ordner existiert
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

BASE_DIR = os.path.abspath(".")
app = Flask(__name__, static_folder=BASE_DIR, template_folder=BASE_DIR)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = SECRET_KEY

# Damit hinter Reverse-Proxies (Nginx, Traefik o.ä.) die echten IPs ankommen:
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Gemeinsamer Header und Footer
HEADER_HTML = '''
<header style="display: flex; align-items: center; justify-content: center; background-color: #f8f9fa; padding: 10px;">
  <span style="font-size: 24px; font-weight: bold; margin-right: 5px;">Lizens</span>
  <img src="https://raw.githubusercontent.com/mrder/lizenzmanager/refs/heads/main/icon.png" alt="Logo" style="max-height: 60px; margin: 0 5px;">
  <span style="font-size: 24px; font-weight: bold; margin-left: 5px;">Manager</span>
</header>
'''

FOOTER_HTML = '''
<footer style="display: flex; justify-content: center; align-items: center; background-color: #f8f9fa; padding: 10px; margin-top: 20px;">
  <img src="https://s20.directupload.net/images/240723/oejqar3j.png" alt="Footer Logo" style="max-height: 40px; margin-right: 5px;">
  <p style="margin: 0;">&copy; sonnyathome.online Version 1.1</p>
</footer>
'''

# -------------------- Datenbankmodelle --------------------
class License(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(120))
    client_id = db.Column(db.String(120), unique=True, nullable=False)
    license_key = db.Column(db.String(120), unique=True, nullable=False)
    acquired_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    contact = db.Column(db.String(120))
    last_login_at = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(120))
    error_counter = db.Column(db.Integer, default=0)
    tool = db.Column(db.String(120))
    expiry_date = db.Column(db.DateTime)
    client_version = db.Column(db.String(20))
    error_logs = db.relationship(
        'ErrorLog',
        backref='license',
        lazy=True,
        cascade='all, delete-orphan',
        passive_deletes=True
    )

class ErrorLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    license_id = db.Column(
        db.Integer,
        db.ForeignKey('license.id', ondelete='CASCADE'),
        nullable=True
    )
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    message = db.Column(db.String(255))

class ToolUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tool = db.Column(db.String(120), nullable=False)
    version = db.Column(db.String(20), nullable=False)
    download_count = db.Column(db.Integer, default=0)
    last_download_at = db.Column(db.DateTime)
    update_url = db.Column(db.String(255))

# -------------------- Hilfsfunktionen --------------------
def is_newer_version(client_ver, latest_ver):
    try:
        client_tuple = tuple(map(int, client_ver.split('.')))
        latest_tuple = tuple(map(int, latest_ver.split('.')))
        return latest_tuple > client_tuple
    except Exception:
        return False

def is_public_ip(ip):
    try:
        addr = ipaddress.ip_address(ip)
        return not addr.is_private and not addr.is_loopback
    except ValueError:
        return False

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_client_ip():
    if request.json and request.json.get('ClientIP'):
        return request.json['ClientIP']
    header = request.headers.get('X-Forwarded-For') or request.headers.get('X-Real-IP')
    if header:
        for ip in [h.strip() for h in header.split(',')]:
            try:
                addr = ipaddress.ip_address(ip)
                if not addr.is_private and not addr.is_loopback:
                    return ip
            except ValueError:
                continue
        return header.split(',')[0].strip()
    return request.remote_addr

# -------------------- Lizenz-API --------------------
@app.route('/api/verify', methods=['POST'])
def verify_license():
    data = request.get_json()
    client_id = data.get('ClientID')
    license_key = data.get('Lizenz')
    client_version = data.get('Version')
    client_ip = get_client_ip()

    license_record = License.query.filter_by(client_id=client_id, license_key=license_key).first()
    if not license_record:
        license_by_client = License.query.filter_by(client_id=client_id).first()
        if license_by_client:
            log = ErrorLog(
                license_id=license_by_client.id,
                message=f"Ungültige Lizenzdaten: ClientID {client_id}, Lizenz {license_key}"
            )
        else:
            log = ErrorLog(
                message=f"Ungültige Lizenzdaten: ClientID {client_id}, Lizenz {license_key}"
            )
        db.session.add(log)
        db.session.commit()
        return jsonify({
            'Lizenzstatus': False,
            'Ablaufdatum': None,
            'Nachricht': 'Ungültige Lizenzdaten'
        })

    if client_version:
        license_record.client_version = client_version

    if license_record.expiry_date and license_record.expiry_date < datetime.datetime.utcnow():
        license_record.error_counter += 1
        log = ErrorLog(license_id=license_record.id, message="Lizenz abgelaufen")
        db.session.add(log)
        db.session.commit()
        return jsonify({
            'Lizenzstatus': False,
            'Ablaufdatum': license_record.expiry_date.strftime('%d.%m.%Y'),
            'Nachricht': 'Lizenz abgelaufen'
        })

    # IP-Wechsel prüfen, nur wenn neue IP öffentlich ist
    if license_record.last_login_ip and license_record.last_login_ip != client_ip and is_public_ip(client_ip):
        license_record.error_counter += 1
        log = ErrorLog(license_id=license_record.id, message="Double IP Login")
        db.session.add(log)
        db.session.commit()
        return jsonify({
            'Lizenzstatus': False,
            'Ablaufdatum': license_record.expiry_date.strftime('%d.%m.%Y') if license_record.expiry_date else None,
            'Nachricht': 'Double IP Login'
        })

    license_record.last_login_at = datetime.datetime.utcnow()
    license_record.last_login_ip = client_ip

    update_info = {
        "UpdateAvailable": False,
        "LatestVersion": None,
        "UpdateURL": None
    }
    if license_record.tool and license_record.client_version:
        tool_update = ToolUpdate.query.filter_by(tool=license_record.tool).order_by(ToolUpdate.id.desc()).first()
        if tool_update and is_newer_version(license_record.client_version, tool_update.version):
            update_info = {
                "UpdateAvailable": True,
                "LatestVersion": tool_update.version,
                "UpdateURL": tool_update.update_url
            }

    db.session.commit()
    response = {
        'Lizenzstatus': True,
        'Ablaufdatum': license_record.expiry_date.strftime('%d.%m.%Y') if license_record.expiry_date else None,
        'Nachricht': None,
    }
    response.update(update_info)
    return jsonify(response)

# -------------------- Backup-Routen --------------------
@app.route('/backup/download')
@login_required
def backup_download():
    if DATABASE_URI.startswith("sqlite:///"):
        db_path = DATABASE_URI.replace("sqlite:///", "", 1)
    else:
        db_path = os.path.join(BASE_DIR, "licenses.db")
    return send_from_directory(
        os.path.dirname(db_path),
        os.path.basename(db_path),
        as_attachment=True,
        download_name="licenses.db"
    )

@app.route('/backup/upload', methods=['GET', 'POST'])
@login_required
def backup_upload():
    if request.method == 'POST':
        if 'backup_file' not in request.files:
            flash("Keine Datei ausgewählt")
            return redirect(request.url)
        file = request.files['backup_file']
        if file.filename == "":
            flash("Keine Datei ausgewählt")
            return redirect(request.url)
        if not file.filename.lower().endswith('.db'):
            flash("Ungültige Dateiendung. Bitte eine .db-Datei hochladen.")
            return redirect(request.url)
        temp_path = os.path.join(UPLOAD_FOLDER, "temp_backup.db")
        file.save(temp_path)
        if DATABASE_URI.startswith("sqlite:///"):
            db_path = DATABASE_URI.replace("sqlite:///", "", 1)
        else:
            db_path = os.path.join(BASE_DIR, "licenses.db")
        db.session.remove()
        try:
            shutil.copy(temp_path, db_path)
            flash("Backup erfolgreich wiederhergestellt. Bitte starten Sie die Anwendung neu.")
        except Exception as e:
            flash(f"Fehler beim Wiederherstellen des Backups: {str(e)}")
        finally:
            os.remove(temp_path)
        return redirect(url_for('dashboard'))

    upload_form = '''
    <!doctype html>
    <html lang="de">
      <head>
        <meta charset="utf-8">
        <title>Backup hochladen</title>
        <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css">
      </head>
      <body>
        ''' + HEADER_HTML + '''
        <div class="container">
          <h1 class="mt-4">Backup hochladen</h1>
          <form method="post" enctype="multipart/form-data">
            <div class="form-group">
              <label>Backup-Datei (.db):</label>
              <input type="file" name="backup_file" class="form-control-file" required>
            </div>
            <button type="submit" class="btn btn-primary">Hochladen und Wiederherstellen</button>
          </form>
          <br>
          <a href="{{ url_for('dashboard') }}" class="btn btn-secondary">Zurück zum Dashboard</a>
        </div>
        ''' + FOOTER_HTML + '''
      </body>
    </html>
    '''
    return render_template_string(upload_form, base_domain=BASE_DOMAIN)

# -------------------- Login-Routen --------------------
login_template = '''
<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <title>Login</title>
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css">
  </head>
  <body>
    ''' + HEADER_HTML + '''
    <div class="container">
      <h1 class="mt-4">Login</h1>
      {% with messages = get_flashed_messages() %}{% if messages %}{% for message in messages %}<div class="alert alert-danger">{{ message }}</div>{% endfor %}{% endif %}{% endwith %}
      <form method="post">
        <div class="form-group"><label>Nutzername:</label><input type="text" name="username" class="form-control"></div>
        <div class="form-group"><label>Passwort:</label><input type="password" name="password" class="form-control"></div>
        <button type="submit" class="btn btn-primary">Login</button>
      </form>
    </div>
    ''' + FOOTER_HTML + '''
  </body>
</html>
'''

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uname = request.form.get('username')
        pwd = request.form.get('password')
        if uname == USERNAME and pwd == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            flash("Ungültiger Nutzername oder Passwort")
    return render_template_string(login_template, base_domain=BASE_DOMAIN)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# -------------------- Dashboard & Lizenzverwaltung --------------------
dashboard_template = '''
<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>Lizenz Dashboard</title><link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>
''' + HEADER_HTML + '''
<div class="container">
  <div class="d-flex justify-content-between align-items-center mt-4">
    <h1>Lizenz Dashboard</h1>
    <a href="{{ url_for('logout') }}" class="btn btn-secondary">Logout</a>
  </div>
  <div class="mb-3">
    <a href="{{ url_for('generate_license') }}" class="btn btn-primary">Neue Lizenz generieren</a>
    <a href="{{ url_for('add_license') }}" class="btn btn-success">Neue Lizenz hinzufügen</a>
    <a href="{{ url_for('updates') }}" class="btn btn-info">Update Manager</a>
    <a href="{{ url_for('backup_download') }}" class="btn btn-warning">Backup herunterladen</a>
    <a href="{{ url_for('backup_upload') }}" class="btn btn-warning">Backup hochladen</a>
  </div>
  <table class="table table-striped table-bordered">
    <thead><tr>
      <th>ID</th><th>Eigentümer</th><th>ClientID</th><th>Lizenzschlüssel</th><th>Erworben am</th><th>Kontakt</th>
      <th>Letzter Login</th><th>Letzte Login IP</th><th>Fehlercounter</th><th>Tool/Programm</th>
      <th>Ablaufdatum</th><th>Client Version</th><th>Aktionen</th>
    </tr></thead>
    <tbody>
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
          <a href="{{ url_for('edit_license', license_id=lic.id) }}" class="btn btn-warning btn-sm">Bearbeiten</a>
          <a href="{{ url_for('delete_license', license_id=lic.id) }}" class="btn btn-danger btn-sm" onclick="return confirm('Wirklich löschen?');">Löschen</a>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
''' + FOOTER_HTML + '''
</body></html>
'''

add_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Neue Lizenz hinzufügen</title><link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>
''' + HEADER_HTML + '''
<div class="container">
  <h1 class="mt-4">Neue Lizenz hinzufügen</h1>
  <form method="post">
    <div class="form-group"><label>Eigentümer:</label><input type="text" name="owner" class="form-control"></div>
    <div class="form-group"><label>Kontakt:</label><input type="text" name="contact" class="form-control"></div>
    <div class="form-group"><label>Tool/Programm:</label><input type="text" name="tool" class="form-control"></div>
    <div class="form-group"><label>Ablaufdatum (TT.MM.JJJJ):</label><input type="text" name="expiry_date" class="form-control"></div>
    <button type="submit" class="btn btn-success">Lizenz hinzufügen</button>
  </form>
  <br><a href="{{ url_for('dashboard') }}" class="btn btn-secondary">Zurück zum Dashboard</a>
</div>
''' + FOOTER_HTML + '''
</body></html>
'''

edit_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Lizenz bearbeiten</title><link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>
''' + HEADER_HTML + '''
<div class="container">
  <h1 class="mt-4">Lizenz bearbeiten</h1>
  <form method="post">
    <div class="form-group"><label>Eigentümer:</label><input type="text" name="owner" class="form-control" value="{{ license.owner }}"></div>
    <div class="form-group"><label>Kontakt:</label><input type="text" name="contact" class="form-control" value="{{ license.contact }}"></div>
    <div class="form-group"><label>Tool/Programm:</label><input type="text" name="tool" class="form-control" value="{{ license.tool }}"></div>
    <div class="form-group"><label>Ablaufdatum (TT.MM.JJJJ):</label><input type="text" name="expiry_date" class="form-control" value="{{ license.expiry_date.strftime('%d.%m.%Y') if license.expiry_date else '' }}"></div>
    <button type="submit" class="btn btn-success">Speichern</button>
  </form>
  <br><a href="{{ url_for('dashboard') }}" class="btn btn-secondary">Zurück zum Dashboard</a>
</div>
''' + FOOTER_HTML + '''
</body></html>
'''

error_log_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Fehlerlog für Lizenz {{ license.client_id }}</title><link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>
''' + HEADER_HTML + '''
<div class="container">
  <h1 class="mt-4">Fehlerlog für Lizenz {{ license.client_id }}</h1>
  <a href="{{ url_for('dashboard') }}" class="btn btn-secondary mb-3">Zurück zum Dashboard</a>
  <table class="table table-bordered">
    <thead><tr><th>ID</th><th>Timestamp</th><th>Fehlermeldung</th></tr></thead>
    <tbody>
      {% for log in error_logs %}
      <tr>
        <td>{{ log.id }}</td>
        <td>{{ log.timestamp.strftime('%d.%m.%Y %H:%M:%S') }}</td>
        <td>{{ log.message }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
''' + FOOTER_HTML + '''
</body></html>
'''

# -------------------- Update Manager --------------------
update_dashboard_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Update Manager</title><link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>
''' + HEADER_HTML + '''
<div class="container">
  <a href="{{ url_for('dashboard') }}" class="btn btn-secondary mb-3">Zurück zum Dashboard</a>
  <a href="{{ url_for('upload_update') }}" class="btn btn-success mb-3">Neues Update hochladen</a>
  {% for tool, updates in grouped_updates.items() %}
    <h3 class="mt-4">{{ tool }}</h3>
    <table class="table table-striped table-bordered">
      <thead><tr><th>ID</th><th>Version</th><th>Download Count</th><th>Letzter Download</th><th>Update Link</th><th>Aktionen</th></tr></thead>
      <tbody>
        {% for upd in updates %}
        <tr>
          <td>{{ upd.id }}</td>
          <td>{{ upd.version }}</td>
          <td>{{ upd.download_count }}</td>
          <td>{{ upd.last_download_at.strftime('%d.%m.%Y %H:%M:%S') if upd.last_download_at else '' }}</td>
          <td><a href="{{ upd.update_url }}" target="_blank">{{ upd.update_url }}</a></td>
          <td>
            <a href="{{ url_for('download_update', update_id=upd.id) }}" class="btn btn-primary btn-sm">Download</a>
            <a href="{{ url_for('delete_update', update_id=upd.id) }}" class="btn btn-danger btn-sm" onclick="return confirm('Update wirklich löschen?');">Löschen</a>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  {% endfor %}
</div>
''' + FOOTER_HTML + '''
</body></html>
'''

upload_update_template = '''
<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Update hochladen</title><link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css"></head><body>
''' + HEADER_HTML + '''
<div class="container">
  <h1 class="mt-4">Neues Update hochladen</h1>
  <form method="post" enctype="multipart/form-data">
    <div class="form-group"><label>Tool/Programm:</label><input type="text" name="tool" class="form-control" required></div>
    <div class="form-group"><label>Version:</label><input type="text" name="version" class="form-control" required></div>
    <div class="form-group"><label>Externer Link (optional):</label><input type="text" name="external_link" class="form-control" placeholder="https://github.com/..."></div>
    <div class="form-group"><label>Update-Datei (ZIP) (optional):</label><input type="file" name="update_file" class="form-control-file"></div>
    <button type="submit" class="btn btn-primary">Upload</button>
  </form>
  <br><a href="{{ url_for('updates') }}" class="btn btn-secondary">Zurück zum Update Manager</a>
</div>
''' + FOOTER_HTML + '''
</body></html>
'''

# -------------------- Update Manager Routen --------------------
@app.route('/updates')
@login_required
def updates():
    updates_all = ToolUpdate.query.order_by(ToolUpdate.tool, ToolUpdate.id.desc()).all()
    grouped_updates = {}
    for upd in updates_all:
        grouped_updates.setdefault(upd.tool, []).append(upd)
    return render_template_string(update_dashboard_template, grouped_updates=grouped_updates, base_domain=BASE_DOMAIN)

@app.route('/upload_update', methods=['GET', 'POST'])
@login_required
def upload_update():
    if request.method == 'POST':
        tool = request.form.get('tool')
        version = request.form.get('version')
        external_link = request.form.get('external_link')
        file = request.files.get('update_file')
        if not file and not external_link:
            flash("Entweder eine Datei oder einen externen Link angeben!")
            return redirect(url_for('upload_update'))
        if file:
            filename = secure_filename(file.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(file_path)
            update_url = f"{BASE_DOMAIN}/uploads/{unique_filename}"
        else:
            update_url = external_link
        new_update = ToolUpdate(tool=tool, version=version, update_url=update_url)
        db.session.add(new_update)
        db.session.commit()
        flash("Update erfolgreich hochgeladen!")
        return redirect(url_for('updates'))
    return render_template_string(upload_update_template)

@app.route('/download_update/<int:update_id>')
@login_required
def download_update(update_id):
    update = ToolUpdate.query.get_or_404(update_id)
    update.download_count += 1
    update.last_download_at = datetime.datetime.utcnow()
    db.session.commit()
    return redirect(update.update_url)

@app.route('/delete_update/<int:update_id>')
@login_required
def delete_update(update_id):
    update = ToolUpdate.query.get_or_404(update_id)
    if update.update_url and update.update_url.startswith(BASE_DOMAIN):
        filename = update.update_url.rsplit('/', 1)[-1]
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    db.session.delete(update)
    db.session.commit()
    flash("Update erfolgreich gelöscht!")
    return redirect(url_for('updates'))

# -------------------- Lizenzverwaltung Routen --------------------
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    licenses = License.query.all()
    return render_template_string(dashboard_template, licenses=licenses, base_domain=BASE_DOMAIN)

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_license():
    if request.method == 'POST':
        owner = request.form.get('owner')
        contact = request.form.get('contact')
        tool = request.form.get('tool')
        expiry_date_str = request.form.get('expiry_date')
        try:
            expiry_date = datetime.datetime.strptime(expiry_date_str, '%d.%m.%Y')
        except Exception:
            expiry_date = None
        client_id = uuid.uuid4().hex
        license_key = uuid.uuid4().hex
        new_license = License(
            owner=owner,
            contact=contact,
            tool=tool,
            expiry_date=expiry_date,
            client_id=client_id,
            license_key=license_key
        )
        db.session.add(new_license)
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template_string(add_template)

@app.route('/edit/<int:license_id>', methods=['GET', 'POST'])
@login_required
def edit_license(license_id):
    license_record = License.query.get_or_404(license_id)
    if request.method == 'POST':
        license_record.owner = request.form.get('owner')
        license_record.contact = request.form.get('contact')
        license_record.tool = request.form.get('tool')
        expiry_date_str = request.form.get('expiry_date')
        try:
            license_record.expiry_date = datetime.datetime.strptime(expiry_date_str, '%d.%m.%Y')
        except Exception:
            license_record.expiry_date = None
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template_string(edit_template, license=license_record)

@app.route('/delete/<int:license_id>')
@login_required
def delete_license(license_id):
    license_record = License.query.get_or_404(license_id)
    db.session.delete(license_record)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/generate_license')
@login_required
def generate_license():
    client_id = uuid.uuid4().hex
    license_key = uuid.uuid4().hex
    expiry_date = datetime.datetime.utcnow() + timedelta(days=365)
    new_license = License(
        client_id=client_id,
        license_key=license_key,
        expiry_date=expiry_date
    )
    db.session.add(new_license)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/error_log/<int:license_id>')
@login_required
def error_log(license_id):
    license_record = License.query.get_or_404(license_id)
    error_logs = ErrorLog.query.filter_by(license_id=license_id).order_by(ErrorLog.timestamp.desc()).all()
    return render_template_string(error_log_template, license=license_record, error_logs=error_logs)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=PORT, debug=True)
