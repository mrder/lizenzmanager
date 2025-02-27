import os
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import uuid
from functools import wraps
from werkzeug.utils import secure_filename

# Konfiguration über Umgebungsvariablen
USERNAME = os.environ.get('USERNAME', 'admin')
PASSWORD = os.environ.get('PASSWORD', 'secret1991')
BASE_DOMAIN = os.environ.get('BASE_DOMAIN', 'http://localhost:5200')
# UPLOAD_FOLDER wird entweder über Umgebungsvariable oder im Containerverzeichnis /app/uploads gesetzt
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(os.getcwd(), 'uploads'))
PORT = int(os.environ.get('PORT', 5200))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///licenses.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'a1s2d3f4g5h6j7k8l8ö9')

# Konfiguration für Uploads
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db = SQLAlchemy(app)

# Datenbankmodell für eine Lizenz
class License(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(120))
    client_id = db.Column(db.String(120), unique=True, nullable=False)
    license_key = db.Column(db.String(120), unique=True, nullable=False)
    acquired_at = db.Column(db.DateTime, default=datetime.utcnow)
    contact = db.Column(db.String(120))
    last_login_at = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(120))
    error_counter = db.Column(db.Integer, default=0)
    tool = db.Column(db.String(120))
    expiry_date = db.Column(db.DateTime)
    client_version = db.Column(db.String(20))
    error_logs = db.relationship('ErrorLog', backref='license', lazy=True)

# Datenbankmodell für ein Fehlerlog
class ErrorLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    license_id = db.Column(db.Integer, db.ForeignKey('license.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.Column(db.String(255))

# Datenbankmodell für Update-Informationen pro Tool/Programm
class ToolUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tool = db.Column(db.String(120), nullable=False)
    version = db.Column(db.String(20), nullable=False)
    download_count = db.Column(db.Integer, default=0)
    last_download_at = db.Column(db.DateTime)
    update_url = db.Column(db.String(255))

with app.app_context():
    db.create_all()

# Hilfsfunktion zum Vergleich von Versionsnummern (z.B. "2.1" > "2.0")
def is_newer_version(client_ver, latest_ver):
    try:
        client_tuple = tuple(map(int, client_ver.split('.')))
        latest_tuple = tuple(map(int, latest_ver.split('.')))
        return latest_tuple > client_tuple
    except Exception:
        return False

# Login-Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# Route für hochgeladene Dateien
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# API-Endpunkt zur Lizenzüberprüfung mit Versions- und Update-Check
@app.route('/api/verify', methods=['POST'])
def verify_license():
    data = request.get_json()
    client_id = data.get('ClientID')
    license_key = data.get('Lizenz')
    client_version = data.get('Version')
    client_ip = data.get('ClientIP') or request.remote_addr

    license_record = License.query.filter_by(client_id=client_id, license_key=license_key).first()
    if not license_record:
        return jsonify({
            'Lizenzstatus': False,
            'Ablaufdatum': None,
            'Nachricht': 'Ungültige Lizenzdaten'
        })

    if client_version:
        license_record.client_version = client_version

    if license_record.expiry_date and license_record.expiry_date < datetime.utcnow():
        license_record.error_counter += 1
        log = ErrorLog(license_id=license_record.id, message="Lizenz abgelaufen")
        db.session.add(log)
        db.session.commit()
        return jsonify({
            'Lizenzstatus': False,
            'Ablaufdatum': license_record.expiry_date.strftime('%d.%m.%Y'),
            'Nachricht': 'Lizenz abgelaufen'
        })

    if license_record.last_login_ip and license_record.last_login_ip != client_ip:
        license_record.error_counter += 1
        log = ErrorLog(license_id=license_record.id, message="Double IP Login")
        db.session.add(log)
        db.session.commit()
        return jsonify({
            'Lizenzstatus': False,
            'Ablaufdatum': license_record.expiry_date.strftime('%d.%m.%Y') if license_record.expiry_date else None,
            'Nachricht': 'Double IP Login'
        })

    license_record.last_login_at = datetime.utcnow()
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

# --- Login-Routen und Template ---
login_template = '''
<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <title>Login</title>
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css">
  </head>
  <body>
  <div class="container">
    <div class="mt-3 text-center">
      <img src="https://s20.directupload.net/images/240723/oejqar3j.png" alt="Logo" style="max-height: 50px;">
    </div>
    <h1 class="mt-4">Login</h1>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          <div class="alert alert-danger">{{ message }}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    <form method="post">
      <div class="form-group">
        <label>Nutzername:</label>
        <input type="text" name="username" class="form-control">
      </div>
      <div class="form-group">
        <label>Passwort:</label>
        <input type="password" name="password" class="form-control">
      </div>
      <button type="submit" class="btn btn-primary">Login</button>
    </form>
  </div>
  </body>
</html>
'''

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == USERNAME and password == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            flash("Ungültiger Nutzername oder Passwort")
    return render_template_string(login_template)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# --- Dashboard und Lizenzverwaltung ---
dashboard_template = '''
<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <title>Lizenz Dashboard</title>
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css">
  </head>
  <body>
  <div class="container">
    <div class="mt-3 text-center">
      <img src="https://s20.directupload.net/images/240723/oejqar3j.png" alt="Logo" style="max-height: 50px;">
    </div>
    <div class="d-flex justify-content-between align-items-center mt-4">
      <h1>Lizenz Dashboard</h1>
      <a href="{{ url_for('logout') }}" class="btn btn-secondary">Logout</a>
    </div>
    <div class="mb-3">
      <a href="{{ url_for('generate_license') }}" class="btn btn-primary">Neue Lizenz generieren</a>
      <a href="{{ url_for('add_license') }}" class="btn btn-success">Neue Lizenz hinzufügen</a>
      <a href="{{ url_for('updates') }}" class="btn btn-info">Update Manager</a>
    </div>
    <table class="table table-striped table-bordered">
      <thead>
        <tr>
          <th>ID</th>
          <th>Eigentümer</th>
          <th>ClientID</th>
          <th>Lizenzschlüssel</th>
          <th>Erworben am</th>
          <th>Kontakt</th>
          <th>Letzter Login</th>
          <th>Letzte Login IP</th>
          <th>Fehlercounter</th>
          <th>Tool/Programm</th>
          <th>Ablaufdatum</th>
          <th>Client Version</th>
          <th>Aktionen</th>
        </tr>
      </thead>
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
  </body>
</html>
'''

add_template = '''
<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <title>Neue Lizenz hinzufügen</title>
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css">
  </head>
  <body>
  <div class="container">
    <h1 class="mt-4">Neue Lizenz hinzufügen</h1>
    <form method="post">
      <div class="form-group">
        <label>Eigentümer:</label>
        <input type="text" name="owner" class="form-control">
      </div>
      <div class="form-group">
        <label>Kontakt:</label>
        <input type="text" name="contact" class="form-control">
      </div>
      <div class="form-group">
        <label>Tool/Programm:</label>
        <input type="text" name="tool" class="form-control">
      </div>
      <div class="form-group">
        <label>Ablaufdatum (TT.MM.JJJJ):</label>
        <input type="text" name="expiry_date" class="form-control">
      </div>
      <button type="submit" class="btn btn-success">Lizenz hinzufügen</button>
    </form>
    <br>
    <a href="{{ url_for('dashboard') }}" class="btn btn-secondary">Zurück zum Dashboard</a>
  </div>
  </body>
</html>
'''

edit_template = '''
<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <title>Lizenz bearbeiten</title>
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css">
  </head>
  <body>
  <div class="container">
    <h1 class="mt-4">Lizenz bearbeiten</h1>
    <form method="post">
      <div class="form-group">
        <label>Eigentümer:</label>
        <input type="text" name="owner" class="form-control" value="{{ license.owner }}">
      </div>
      <div class="form-group">
        <label>Kontakt:</label>
        <input type="text" name="contact" class="form-control" value="{{ license.contact }}">
      </div>
      <div class="form-group">
        <label>Tool/Programm:</label>
        <input type="text" name="tool" class="form-control" value="{{ license.tool }}">
      </div>
      <div class="form-group">
        <label>Ablaufdatum (TT.MM.JJJJ):</label>
        <input type="text" name="expiry_date" class="form-control" value="{{ license.expiry_date.strftime('%d.%m.%Y') if license.expiry_date else '' }}">
      </div>
      <button type="submit" class="btn btn-success">Speichern</button>
    </form>
    <br>
    <a href="{{ url_for('dashboard') }}" class="btn btn-secondary">Zurück zum Dashboard</a>
  </div>
  </body>
</html>
'''

error_log_template = '''
<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <title>Fehlerlog für Lizenz {{ license.client_id }}</title>
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css">
  </head>
  <body>
  <div class="container">
    <h1 class="mt-4">Fehlerlog für Lizenz {{ license.client_id }}</h1>
    <a href="{{ url_for('dashboard') }}" class="btn btn-secondary mb-3">Zurück zum Dashboard</a>
    <table class="table table-bordered">
      <thead>
        <tr>
          <th>ID</th>
          <th>Timestamp</th>
          <th>Fehlermeldung</th>
        </tr>
      </thead>
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
  </body>
</html>
'''

# --- Update Manager: gruppiert nach Tool/Programm, mit Logo im Header ---
update_dashboard_template = '''
<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <title>Update Manager</title>
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css">
  </head>
  <body>
  <div class="container">
    <div class="mt-3 text-center">
      <img src="https://s20.directupload.net/images/240723/oejqar3j.png" alt="Logo" style="max-height: 50px;">
    </div>
    <h1 class="mt-4">Update Manager</h1>
    <a href="{{ url_for('dashboard') }}" class="btn btn-secondary mb-3">Zurück zum Dashboard</a>
    <a href="{{ url_for('upload_update') }}" class="btn btn-success mb-3">Neues Update hochladen</a>
    {% for tool, updates in grouped_updates.items() %}
      <h3 class="mt-4">{{ tool }}</h3>
      <table class="table table-striped table-bordered">
        <thead>
          <tr>
             <th>ID</th>
             <th>Version</th>
             <th>Download Count</th>
             <th>Letzter Download</th>
             <th>Update Link</th>
             <th>Aktionen</th>
          </tr>
        </thead>
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
  </body>
</html>
'''

upload_update_template = '''
<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <title>Update hochladen</title>
    <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css">
  </head>
  <body>
  <div class="container">
    <h1 class="mt-4">Neues Update hochladen</h1>
    <form method="post" enctype="multipart/form-data">
      <div class="form-group">
        <label>Tool/Programm:</label>
        <input type="text" name="tool" class="form-control" required>
      </div>
      <div class="form-group">
        <label>Version:</label>
        <input type="text" name="version" class="form-control" required>
      </div>
      <div class="form-group">
        <label>Update-Datei (ZIP):</label>
        <input type="file" name="update_file" class="form-control-file" required>
      </div>
      <button type="submit" class="btn btn-primary">Upload</button>
    </form>
    <br>
    <a href="{{ url_for('updates') }}" class="btn btn-secondary">Zurück zum Update Manager</a>
  </div>
  </body>
</html>
'''

@app.route('/updates')
@login_required
def updates():
    updates_all = ToolUpdate.query.order_by(ToolUpdate.tool, ToolUpdate.id.desc()).all()
    grouped_updates = {}
    for upd in updates_all:
        grouped_updates.setdefault(upd.tool, []).append(upd)
    return render_template_string(update_dashboard_template, grouped_updates=grouped_updates)

@app.route('/upload_update', methods=['GET', 'POST'])
@login_required
def upload_update():
    if request.method == 'POST':
        tool = request.form.get('tool')
        version = request.form.get('version')
        file = request.files.get('update_file')
        if not file:
            flash("Keine Datei ausgewählt!")
            return redirect(url_for('upload_update'))
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        update_url = f"{BASE_DOMAIN}/uploads/{unique_filename}"
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
    update.last_download_at = datetime.utcnow()
    db.session.commit()
    return redirect(update.update_url)

@app.route('/delete_update/<int:update_id>')
@login_required
def delete_update(update_id):
    update = ToolUpdate.query.get_or_404(update_id)
    if update.update_url:
        filename = update.update_url.rsplit('/', 1)[-1]
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    db.session.delete(update)
    db.session.commit()
    flash("Update erfolgreich gelöscht!")
    return redirect(url_for('updates'))

# --- Bestehende Routen für Lizenzverwaltung ---
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    licenses = License.query.all()
    return render_template_string(dashboard_template, licenses=licenses)

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_license():
    if request.method == 'POST':
        owner = request.form.get('owner')
        contact = request.form.get('contact')
        tool = request.form.get('tool')
        expiry_date_str = request.form.get('expiry_date')
        try:
            expiry_date = datetime.strptime(expiry_date_str, '%d.%m.%Y')
        except Exception:
            expiry_date = None
        client_id = uuid.uuid4().hex
        license_key = uuid.uuid4().hex
        new_license = License(owner=owner, contact=contact, tool=tool,
                              expiry_date=expiry_date, client_id=client_id,
                              license_key=license_key)
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
            license_record.expiry_date = datetime.strptime(expiry_date_str, '%d.%m.%Y')
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
    expiry_date = datetime.utcnow() + timedelta(days=365)
    new_license = License(client_id=client_id, license_key=license_key,
                          expiry_date=expiry_date)
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
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5200)), debug=True)
