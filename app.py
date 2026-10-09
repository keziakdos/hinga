import os
import sqlite3
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, g, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime

import base64
from dotenv import load_dotenv
from openai import OpenAI

# Charger les variables d'environnement (.env)
load_dotenv()

# Initialiser le client OpenAI
client = OpenAI()




# --- CONFIGURATION ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'changez-moi-en-local')

from helpers import MOIS_FR, MOIS_FR_ABBR, mois_nom, periode_label, month_in_range, plants_for_month, PLANT_TYPES, unique_filename
from services.images import save_tip_image, thumb_name, is_managed_image
from services.plant_analysis import is_analysis_enabled, analyze_image, downscaled_copy


def _tip_thumb(image):
    """Miniature si gérée et présente sur disque, sinon l'image elle-même."""
    if is_managed_image(image):
        t = thumb_name(image)
        if os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'img', t)):
            return t
    return image


def _delete_managed_image(filename):
    """Supprime version page + miniature (fichiers gérés uniquement)."""
    if is_managed_image(filename):
        for f in (filename, thumb_name(filename)):
            p = os.path.join(app.config['UPLOAD_FOLDER'], 'img', f)
            if os.path.exists(p):
                os.remove(p)

@app.context_processor
def inject_helpers():
    return dict(
        mois_nom=mois_nom, periode_label=periode_label,
        month_in_range=month_in_range, MOIS_FR=MOIS_FR, MOIS_FR_ABBR=MOIS_FR_ABBR,
    )

# On définit le chemin absolu du dossier actuel pour éviter les erreurs
basedir = os.path.abspath(os.path.dirname(__file__))

# On pointe vers 'static' car le code rajoute '/img' ensuite
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static') 
app.config['DATABASE'] = os.path.join(basedir, 'hinga.db')



ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- GESTION BDD ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- DECORATEUR LOGIN REQUIS ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Veuillez vous connecter pour accéder à cette page.")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- INITIALISATION BDD ---
def init_db():
    with app.app_context():
        db = get_db()
        
        # 1. Table Utilisateurs
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user' -- 'admin' ou 'user'
            )
        ''')



	# 2. Table Plantes (Globale) - MISE A JOUR AVEC SECTIONS DETAILLEES
        db.execute('''
            CREATE TABLE IF NOT EXISTS plants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, type TEXT,
                sow_start INTEGER, sow_end INTEGER,
                harvest_start INTEGER, harvest_end INTEGER,
                image TEXT, details TEXT, conditions TEXT, roots TEXT,
                section_sun TEXT,
                section_soil TEXT,
                section_water TEXT,
                section_sowing TEXT,
                section_diseases TEXT,
                section_harvest TEXT
            )
        ''')


        # 3. Table Récoltes (Liée à l'utilisateur)
        db.execute('''
            CREATE TABLE IF NOT EXISTS harvests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plant_id INTEGER,
                date TEXT, quantity REAL, notes TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(plant_id) REFERENCES plants(id)
            )
        ''')

        # 4. Table Conseils (Globale)
        db.execute('''
            CREATE TABLE IF NOT EXISTS tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, content TEXT, image TEXT
            )
        ''')

	# 5. Table Plantes Surveillées (Liée à l'utilisateur)
        db.execute('''
            CREATE TABLE IF NOT EXISTS monitored_plants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plant_name TEXT,
                image_path TEXT,
                diagnosis_summary TEXT,
                full_json TEXT,  -- <--- NOUVELLE COLONNE pour stocker tout le rapport AI
                date_added TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')


        
        # Remplissage initial si vide (Admin par défaut + Plantes)
        cur = db.execute('SELECT count(*) FROM users')
        if cur.fetchone()[0] == 0:
            seed_data(db)
        
        db.commit()




# Fonction pour encoder l'image en Base64 (nécessaire pour l'API Vision)
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')




def seed_data(db):
    print("🌱 Création des données initiales...")
    # Admin par défaut (admin / admin123)
    pwd_hash = generate_password_hash('admin123')
    db.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)', ('admin', pwd_hash, 'admin'))
    
    # Plantes (copie de la liste précédente pour abréger ici, ajoutez vos 30 plantes)
    plants = [
        ('Tomate', 'Légume', 3, 5, 7, 10, 'tomato.jpg', 'Adore le soleil.', 'Soleil, sol riche', 'Racines fasciculées'),
        ('Aubergine', 'Légume', 2, 4, 7, 10, 'eggplant.jpg', 'Demande beaucoup de chaleur.', 'Plein soleil', 'Racines pivotantes'),
        # ... (Gardez votre liste complète ici)
    ]
    for p in plants:
        db.execute('INSERT INTO plants (name, type, sow_start, sow_end, harvest_start, harvest_end, image, details, conditions, roots) VALUES (?,?,?,?,?,?,?,?,?,?)', p)

    tips = [
        ('Préparez la terre', 'Ameublissez et enrichissez le sol avant les semis. Il est crucial de...', 'soil.jpg'),
        ('Arrosez tôt', 'Le matin est idéal pour limiter l’évaporation...', 'water.jpg')
    ]
    for t in tips:
        db.execute('INSERT INTO tips (title, content, image) VALUES (?,?,?)', t)

# --- ROUTES AUTHENTIFICATION ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user and check_password_hash(user['password'], password):
            # Compte désactivé (colonne ajoutée par migrate.py, absente des vieilles bases)
            try:
                if user['is_active'] == 0:
                    flash('Compte désactivé. Contactez un administrateur.')
                    return render_template('login.html')
            except (KeyError, IndexError, TypeError):
                pass
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash(f'Bonjour {username} !')
            return redirect(url_for('calendar'))
        else:
            flash('Identifiants incorrects.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Vous êtes déconnecté.')
    return redirect(url_for('login'))

# --- ROUTES PUBLIQUES (Accueil, Calendrier, Fiche Plante, Conseils) ---
@app.route('/')
def index():
    db = get_db()
    plants = db.execute('SELECT * FROM plants ORDER BY name').fetchall()
    now_m = datetime.now().month
    next_m = now_m % 12 + 1
    semer_mtn, recolter_mtn = plants_for_month(plants, now_m)
    # Bientôt : fenêtre qui s'ouvre le mois prochain (hors fenêtre actuelle)
    semer_bientot = [p for p in plants
                     if int(p['sow_start']) == next_m
                     and not month_in_range(now_m, p['sow_start'], p['sow_end'])]
    recolter_bientot = [p for p in plants
                        if int(p['harvest_start']) == next_m
                        and not month_in_range(now_m, p['harvest_start'], p['harvest_end'])]
    return render_template('home.html', plants=plants,
                           mois_actuel=MOIS_FR[now_m - 1], mois_suivant=MOIS_FR[next_m - 1],
                           semer_mtn=semer_mtn, recolter_mtn=recolter_mtn,
                           semer_bientot=semer_bientot, recolter_bientot=recolter_bientot)

@app.route('/calendar')
def calendar():
    # Accessible à tous (lecture seule)
    db = get_db()
    plants = db.execute('SELECT * FROM plants ORDER BY name').fetchall()
    months = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']
    # Mois sélectionné (?mois=1..12) : deux listes semer / récolter
    try:
        selected_month = int(request.args.get('mois', 0))
    except (TypeError, ValueError):
        selected_month = 0
    if not 1 <= selected_month <= 12:
        selected_month = 0
    a_semis, a_recolter = ([], [])
    if selected_month:
        a_semis, a_recolter = plants_for_month(plants, selected_month)
    return render_template('calendar.html', plants=plants, months=months,
                           selected_month=selected_month,
                           a_semis=a_semis, a_recolter=a_recolter)

@app.route('/plant/<int:plant_id>')
def plant_details(plant_id):
    db = get_db()
    plant = db.execute('SELECT * FROM plants WHERE id = ?', (plant_id,)).fetchone()
    return render_template('plant.html', plant=plant)

@app.route('/tips')
def tips():
    db = get_db()
    try:
        rows = db.execute('''SELECT t.*, c.name as category_name FROM tips t
                             LEFT JOIN tip_categories c ON t.category_id = c.id''').fetchall()
    except sqlite3.OperationalError:
        rows = db.execute('SELECT *, NULL as category_name FROM tips').fetchall()
    tips_list = [dict(t, thumb=_tip_thumb(t['image'])) for t in rows]
    return render_template('tips.html', tips=tips_list)

@app.route('/tip/<int:tip_id>')
def tip_details(tip_id):
    db = get_db()
    try:
        row = db.execute('''SELECT t.*, c.name as category_name FROM tips t
                            LEFT JOIN tip_categories c ON t.category_id = c.id
                            WHERE t.id = ?''', (tip_id,)).fetchone()
    except sqlite3.OperationalError:
        row = db.execute('SELECT *, NULL as category_name FROM tips WHERE id = ?', (tip_id,)).fetchone()
    if not row: return "Conseil introuvable", 404
    tip = dict(row)
    tip['thumb'] = _tip_thumb(tip['image'])
    return render_template('tip_detail.html', tip=tip)

# --- ROUTES PRIVÉES (Récoltes, Stats, Ma Plante) ---

@app.route('/harvests', methods=['GET', 'POST'])
@login_required
def harvests():
    db = get_db()
    user_id = session['user_id']
    
    if request.method == 'POST':
        plant_id = request.form['plant_id']
        date = request.form['date']
        quantity = request.form['quantity']
        notes = request.form['notes']
        
        db.execute('INSERT INTO harvests (user_id, plant_id, date, quantity, notes) VALUES (?,?,?,?,?)',
                   (user_id, plant_id, date, quantity, notes))
        db.commit()
        flash('✅ Récolte ajoutée !')
        return redirect(url_for('harvests'))

    # Seules les récoltes de l'utilisateur connecté (avec photo de la plante)
    harvests_list = db.execute('''SELECT h.*, p.name as plant_name, p.image as plant_image
                                  FROM harvests h JOIN plants p ON h.plant_id = p.id
                                  WHERE h.user_id = ? ORDER BY h.date DESC''', (user_id,)).fetchall()
    plants = db.execute('SELECT id, name FROM plants ORDER BY name').fetchall()
    return render_template('harvests.html', harvests=harvests_list, plants=plants, today=datetime.today().strftime('%Y-%m-%d'))

@app.route('/stats')
@login_required
def stats():
    db = get_db()
    user_id = session['user_id']
    
    # Stats filtrées par user_id
    total_weight = db.execute('SELECT SUM(quantity) FROM harvests WHERE user_id = ?', (user_id,)).fetchone()[0] or 0
    
    rows_plants = db.execute('''
        SELECT p.id, p.name, SUM(h.quantity) FROM harvests h 
        JOIN plants p ON h.plant_id = p.id 
        WHERE h.user_id = ? GROUP BY p.id ORDER BY SUM(h.quantity) DESC
    ''', (user_id,)).fetchall()
    
    plant_ids = [row[0] for row in rows_plants]
    plant_labels = [row[1] for row in rows_plants]
    plant_data = [row[2] for row in rows_plants]

    # --- Filtres production : année / grain (mois-semaine) / plante ---
    year_rows = db.execute("SELECT DISTINCT strftime('%Y', date) FROM harvests WHERE user_id = ? AND date IS NOT NULL",
                           (user_id,)).fetchall()
    cur_year = str(datetime.now().year)
    years = sorted({r[0] for r in year_rows if r[0]} | {cur_year}, reverse=True)
    sel_year = request.args.get('annee', cur_year)
    if sel_year not in years:
        sel_year = cur_year
    grain = 'semaine' if request.args.get('grain') == 'semaine' else 'mois'
    try:
        plant_filter = int(request.args.get('plante', 0))
    except (TypeError, ValueError):
        plant_filter = 0

    filt_query = "SELECT date, quantity FROM harvests WHERE user_id = ? AND strftime('%Y', date) = ?"
    filt_params = [user_id, sel_year]
    if plant_filter:
        filt_query += " AND plant_id = ?"
        filt_params.append(plant_filter)
    entries = db.execute(filt_query, filt_params).fetchall()

    if grain == 'semaine':
        prod_labels = [f"S{w}" for w in range(1, 54)]
        prod_values = [0] * 53
        for e in entries:
            try:
                d = datetime.strptime(e['date'][:10], '%Y-%m-%d')
                if d.strftime('%Y') == sel_year:
                    prod_values[d.isocalendar()[1] - 1] += e['quantity'] or 0
            except (ValueError, TypeError):
                continue
        prod_values = [round(v, 2) for v in prod_values]
        prod_title = "Production par Semaine"
    else:
        prod_labels = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']
        prod_values = [0] * 12
        for e in entries:
            try:
                m = int(e['date'][5:7])
                if 1 <= m <= 12:
                    prod_values[m - 1] += e['quantity'] or 0
            except (ValueError, TypeError, IndexError):
                continue
        prod_values = [round(v, 2) for v in prod_values]
        prod_title = "Production par Mois"

    user_plants = db.execute('''SELECT DISTINCT p.id, p.name FROM harvests h
                                JOIN plants p ON h.plant_id = p.id
                                WHERE h.user_id = ? ORDER BY p.name''', (user_id,)).fetchall()

    monthly_map = {f"{i:02d}": 0 for i in range(1, 13)}
    rows_months = db.execute("SELECT strftime('%m', date) as m, SUM(quantity) FROM harvests WHERE user_id = ? GROUP BY m", (user_id,)).fetchall()
    for row in rows_months:
        if row[0] in monthly_map: monthly_map[row[0]] = row[1]
            
    month_labels_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']
    month_values = list(monthly_map.values())

    # Comptage par plante (nb de récoltes + kg) + fenêtres semis/récolte
    rows_counts = db.execute('''SELECT p.name, COUNT(*), SUM(h.quantity),
        p.sow_start, p.sow_end, p.harvest_start, p.harvest_end, p.id
        FROM harvests h JOIN plants p ON h.plant_id = p.id
        WHERE h.user_id = ? GROUP BY p.id ORDER BY SUM(h.quantity) DESC''', (user_id,)).fetchall()
    per_plant = [dict(name=r[0], count=r[1], qty=round(r[2] or 0, 2),
                      sow=periode_label(r[3], r[4]), harvest=periode_label(r[5], r[6]),
                      plant_id=r[7]) for r in rows_counts]
    total_entries = sum(r['count'] for r in per_plant)
    distinct_plants = len(per_plant)
    avg_entry = round(total_weight / total_entries, 2) if total_entries else 0

    # Semis par mois (calendrier global : nb de plantes à semer chaque mois)
    all_plants = db.execute('SELECT sow_start, sow_end FROM plants').fetchall()
    sow_per_month = [sum(1 for p in all_plants if month_in_range(m, p['sow_start'], p['sow_end']))
                     for m in range(1, 13)]
    top_sow_month = MOIS_FR[max(range(12), key=lambda i: sow_per_month[i])] if any(sow_per_month) else '—'

    # Meilleur mois de production (kg récoltés)
    best_prod_month = MOIS_FR[month_values.index(max(month_values))] if total_weight > 0 else '—'

    # Estimation des récoltes à venir (plantes déjà cultivées par l'utilisateur)
    now_m = datetime.now().month
    upcoming = []
    for r in rows_counts:
        hs, he = r[5], r[6]
        current = month_in_range(now_m, hs, he)
        if current:
            status = 'En récolte actuellement'
        else:
            nxt = next((k for k in range(1, 13)
                        if month_in_range(((now_m - 1 + k) % 12) + 1, hs, he)), None)
            status = f"Dès {mois_nom(((now_m - 1 + nxt) % 12) + 1)}" if nxt else '—'
        upcoming.append(dict(name=r[0], window=periode_label(hs, he),
                             status=status, current=current))

    return render_template('stats.html', total_weight=round(total_weight, 2),
                           plant_labels=json.dumps(plant_labels), plant_data=json.dumps(plant_data),
                           plant_ids=json.dumps(plant_ids),
                           month_labels=json.dumps(month_labels_fr), month_values=json.dumps(month_values),
                           per_plant=per_plant, total_entries=total_entries,
                           distinct_plants=distinct_plants, avg_entry=avg_entry,
                           sow_per_month=json.dumps(sow_per_month), top_sow_month=top_sow_month,
                           best_prod_month=best_prod_month, upcoming=upcoming,
                           current_month_name=MOIS_FR[now_m - 1],
                           years=years, sel_year=sel_year, grain=grain,
                           plant_filter=plant_filter, user_plants=user_plants,
                           prod_labels=json.dumps(prod_labels),
                           prod_values=json.dumps(prod_values), prod_title=prod_title)


@app.route('/stats/plant/<int:plant_id>')
@login_required
def stats_plant(plant_id):
    """Historique d'une culture : ajouts + période la plus récoltée."""
    db = get_db()
    user_id = session['user_id']
    plant = db.execute('SELECT * FROM plants WHERE id = ?', (plant_id,)).fetchone()
    if plant is None:
        flash("Plante introuvable.")
        return redirect(url_for('stats'))

    entries = db.execute('''SELECT date, quantity, notes FROM harvests
                            WHERE user_id = ? AND plant_id = ? ORDER BY date DESC''',
                         (user_id, plant_id)).fetchall()
    monthly = [0] * 12
    for e in entries:
        try:
            m = int((e['date'] or '')[5:7])
            if 1 <= m <= 12:
                monthly[m - 1] += e['quantity'] or 0
        except (ValueError, TypeError, IndexError):
            continue
    monthly = [round(v, 2) for v in monthly]
    total = round(sum(monthly), 2)
    count = len(entries)
    best_month = MOIS_FR[monthly.index(max(monthly))] if total > 0 else '—'

    return render_template('stats_plant.html', plant=plant, entries=entries,
                           monthly=json.dumps(monthly),
                           month_labels=json.dumps(['Jan', 'Fév', 'Mar', 'Avr', 'Mai',
                                                    'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']),
                           total=total, count=count,
                           avg=round(total / count, 2) if count else 0,
                           best_month=best_month)









@app.route('/maplante', methods=['GET', 'POST'])
@login_required
def maplante():
    db = get_db()
    user_id = session['user_id']
    result = None
    
    if request.method == 'POST':
        if 'file' not in request.files: return redirect(request.url)
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename): return redirect(request.url)

        # Sauvegarde image (nom sûr et unique, extension d'origine)
        filename = unique_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'img', filename)
        file.save(filepath)

        if not is_analysis_enabled():
            # V1 : service non branché -> photo enregistrée en "attente d'analyse"
            db.execute('''INSERT INTO monitored_plants
                          (user_id, plant_name, image_path, diagnosis_summary, full_json, date_added)
                          VALUES (?, ?, ?, ?, ?, ?)''',
                       (user_id, 'Analyse en attente', filename,
                        f"Photo enregistrée le {datetime.now().strftime('%Y-%m-%d')}, analyse automatique à configurer.",
                        '{}', datetime.now().strftime('%Y-%m-%d')))
            db.commit()
            flash("📸 Photo enregistrée. L'analyse automatique sera configurée à la fin du projet.")
            return redirect(url_for('maplante'))

        try:
            # Envoi d'une copie réduite (rapide) ; l'original reste archivé.
            tmp_path = downscaled_copy(filepath)
            try:
                ai_json = analyze_image(tmp_path)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            result = {
                "image_filename": filename,
                "name": ai_json.get('name', 'Inconnue'),
                "confidence": ai_json.get('confidence', '?'),
                "strengths": ai_json.get('strengths', []),
                "weaknesses": ai_json.get('weaknesses', []),
                "advice": ai_json.get('advice', ''),
                "details": ai_json.get('details', {}) # Les nouvelles infos
            }
            flash('✅ Analyse approfondie terminée !')

        except Exception as e:
            msg = str(e)
            if 'timeout' in msg.lower() or 'deadline' in msg.lower():
                flash("⏳ L'analyse prend trop de temps. Réessayez (photo plus légère, ou dans un moment).")
            else:
                flash(f"Erreur IA : {msg}")
            print(e)

    # Récupérer l'historique
    monitored = db.execute('SELECT * FROM monitored_plants WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
            
    return render_template('maplante.html', result=result, monitored=monitored,
                           analysis_enabled=is_analysis_enabled())




@app.route('/monitor_save', methods=['POST'])
@login_required
def monitor_save():
    db = get_db()
    # On récupère le gros JSON caché dans le formulaire
    full_data_str = request.form['full_data']
    full_data = json.loads(full_data_str) # On vérifie que c'est du JSON valide
    
    image_filename = full_data['image_filename']
    plant_name = full_data['name']
    summary = f"{full_data.get('details', {}).get('sun', '')} - {full_data['advice'][:50]}..."

    db.execute('''INSERT INTO monitored_plants (user_id, plant_name, image_path, diagnosis_summary, full_json, date_added) 
                  VALUES (?, ?, ?, ?, ?, ?)''',
               (session['user_id'], plant_name, image_filename, summary, full_data_str, datetime.now().strftime('%Y-%m-%d')))
    db.commit()
    flash('✅ Rapport complet sauvegardé !')
    return redirect(url_for('maplante'))

@app.route('/monitor/view/<int:id>')
@login_required
def monitor_view(id):
    db = get_db()
    # On récupère la plante seulement si elle appartient à l'utilisateur
    entry = db.execute('SELECT * FROM monitored_plants WHERE id = ? AND user_id = ?', (id, session['user_id'])).fetchone()
    
    if entry is None:
        flash("Ce rapport n'existe pas ou ne vous appartient pas.")
        return redirect(url_for('maplante'))
    
    # On convertit le texte JSON stocké en objet Python utilisable
    import json
    try:
        data = json.loads(entry['full_json'])
    except:
        data = {} # Cas où l'ancien format n'a pas de JSON
        
    # On ajoute l'URL de l'image au dictionnaire pour l'affichage
    data['image_url'] = url_for('static', filename='img/' + entry['image_path'])
    
    return render_template('monitor_detail.html', result=data, entry_id=entry['id'])

@app.route('/monitor/delete/<int:id>')
@login_required
def monitor_delete(id):
    db = get_db()
    db.execute('DELETE FROM monitored_plants WHERE id = ? AND user_id = ?', (id, session['user_id']))
    db.commit()
    flash('🗑️ Rapport supprimé.')
    return redirect(url_for('maplante'))






# --- SECTION ADMINISTRATION ---

@app.route('/admin')
@login_required
def admin_dashboard():
    if session.get('role') != 'admin':
        flash('Accès réservé aux administrateurs.')
        return redirect(url_for('calendar'))
    return render_template('admin/dashboard.html')

# --- GESTION UTILISATEURS ---
@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    
    if request.method == 'POST':
        # Création d'un utilisateur
        username = request.form['username'].strip()
        password = request.form['password']
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        notes = request.form.get('notes', '').strip()
        # Vérif si existe déjà
        exist = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if exist:
            flash('Ce nom d\'utilisateur existe déjà.')
        else:
            pwd_hash = generate_password_hash(password)
            db.execute('''INSERT INTO users (username, password, role, first_name, last_name, email, notes, is_active)
                          VALUES (?, ?, 'user', ?, ?, ?, ?, 1)''',
                       (username, pwd_hash, first_name, last_name, email, notes))
            db.commit()
            flash(f'Utilisateur {username} créé !')
        return redirect(url_for('admin_users'))
        
    users = db.execute('SELECT * FROM users').fetchall()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if user is None:
        flash("Utilisateur introuvable.")
        return redirect(url_for('admin_users'))

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        notes = request.form.get('notes', '').strip()
        role = request.form.get('role', 'user')
        if role not in ('admin', 'user'):
            role = 'user'
        # Impossible de désactiver son propre compte ou de se rétrograder
        if user_id == session['user_id']:
            is_active = 1
            role = user['role']
        else:
            is_active = 1 if request.form.get('is_active') else 0
        db.execute('''UPDATE users SET first_name=?, last_name=?, email=?, notes=?, role=?, is_active=?
                      WHERE id=?''', (first_name, last_name, email, notes, role, is_active, user_id))
        new_password = request.form.get('new_password', '')
        if new_password:
            db.execute('UPDATE users SET password=? WHERE id=?',
                       (generate_password_hash(new_password), user_id))
        db.commit()
        flash('Utilisateur mis à jour.')
        return redirect(url_for('admin_users'))

    return render_template('admin/user_form.html', user=user)

@app.route('/admin/users/delete/<int:user_id>')
@login_required
def admin_delete_user(user_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    # On empêche de se supprimer soi-même
    if user_id == session['user_id']:
        flash('Impossible de supprimer votre propre compte ici.')
    else:
        db = get_db()
        db.execute('DELETE FROM users WHERE id = ?', (user_id,))
        db.commit()
        flash('Utilisateur supprimé.')
    return redirect(url_for('admin_users'))

# --- GESTION PLANTES ---
@app.route('/admin/plants')
@login_required
def admin_plants():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    plants = db.execute('SELECT * FROM plants ORDER BY name').fetchall()
    return render_template('admin/plants.html', plants=plants)












@app.route('/admin/plants/edit', methods=['GET', 'POST'])
@app.route('/admin/plants/edit/<int:plant_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_plant(plant_id=None):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    
    if request.method == 'POST':
        # Champs de base
        name = request.form['name']
        ptype = request.form['type']
        sow_start = request.form['sow_start']
        sow_end = request.form['sow_end']
        har_start = request.form['harvest_start']
        har_end = request.form['harvest_end']
        # Note: on garde 'details', 'conditions', 'roots' pour compatibilité si besoin, 
        # mais on va surtout utiliser les nouvelles sections ci-dessous.
        details = request.form.get('details', '')
        conditions = request.form.get('conditions', '')
        roots = request.form.get('roots', '')
        
        # NOUVELLES SECTIONS DETAILLEES
        sec_sun = request.form.get('section_sun', '')
        sec_soil = request.form.get('section_soil', '')
        sec_water = request.form.get('section_water', '')
        sec_sowing = request.form.get('section_sowing', '')
        sec_diseases = request.form.get('section_diseases', '')
        sec_harvest = request.form.get('section_harvest', '')

        # Gestion image : nom sûr et unique, remplacement de l'ancienne
        image_filename = request.form.get('current_image')
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '' and allowed_file(file.filename):
                image_filename = unique_filename(file.filename)
                # Utilisation du chemin absolu basedir défini plus haut
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'img', image_filename))

        if plant_id:
            # UPDATE AVEC LES NOUVEAUX CHAMPS
            if not image_filename:
                # Conserver l'image existante si aucune nouvelle image
                row = db.execute('SELECT image FROM plants WHERE id = ?', (plant_id,)).fetchone()
                image_filename = row['image'] if row and row['image'] else 'default.jpg'
            db.execute('''UPDATE plants SET name=?, type=?, sow_start=?, sow_end=?, harvest_start=?, harvest_end=?, 
                          details=?, conditions=?, roots=?, image=?,
                          section_sun=?, section_soil=?, section_water=?, section_sowing=?, section_diseases=?, section_harvest=?
                          WHERE id=?''',
                       (name, ptype, sow_start, sow_end, har_start, har_end, details, conditions, roots, image_filename, 
                        sec_sun, sec_soil, sec_water, sec_sowing, sec_diseases, sec_harvest, plant_id))
            flash('Plante modifiée avec succès.')
        else:
            # INSERT AVEC LES NOUVEAUX CHAMPS
            if not image_filename: image_filename = 'default.jpg'
            db.execute('''INSERT INTO plants (name, type, sow_start, sow_end, harvest_start, harvest_end, details, conditions, roots, image,
                          section_sun, section_soil, section_water, section_sowing, section_diseases, section_harvest)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (name, ptype, sow_start, sow_end, har_start, har_end, details, conditions, roots, image_filename,
                        sec_sun, sec_soil, sec_water, sec_sowing, sec_diseases, sec_harvest))
            flash('Nouvelle plante ajoutée.')
        db.commit()
        return redirect(url_for('admin_plants'))

    plant = None
    if plant_id:
        plant = db.execute('SELECT * FROM plants WHERE id = ?', (plant_id,)).fetchone()
    
    return render_template('admin/plant_form.html', plant=plant, plant_types=PLANT_TYPES, mois=MOIS_FR)











@app.route('/admin/plants/delete/<int:plant_id>')
@login_required
def admin_delete_plant(plant_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    db.execute('DELETE FROM plants WHERE id = ?', (plant_id,))
    db.commit()
    flash('Plante supprimée.')
    return redirect(url_for('admin_plants'))

# --- GESTION CONSEILS (Tips) ---
def _tip_categories(db):
    try:
        return db.execute('SELECT * FROM tip_categories ORDER BY name').fetchall()
    except sqlite3.OperationalError:
        return []

@app.route('/admin/tips', methods=['GET', 'POST'])
@login_required
def admin_tips():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()

    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        cat_raw = request.form.get('category_id', '')
        category_id = int(cat_raw) if cat_raw.isdigit() else None
        image_filename = 'default_tip.jpg'

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                page, error = save_tip_image(file, os.path.join(app.config['UPLOAD_FOLDER'], 'img'))
                if error:
                    flash(error)
                    return redirect(url_for('admin_tips'))
                image_filename = page

        try:
            db.execute('INSERT INTO tips (title, content, image, category_id) VALUES (?,?,?,?)',
                       (title, content, image_filename, category_id))
        except sqlite3.OperationalError:
            db.execute('INSERT INTO tips (title, content, image) VALUES (?,?,?)',
                       (title, content, image_filename))
        db.commit()
        flash('Conseil ajouté.')
        return redirect(url_for('admin_tips'))

    try:
        tips = db.execute('''SELECT t.*, c.name as category_name FROM tips t
                             LEFT JOIN tip_categories c ON t.category_id = c.id
                             ORDER BY t.id DESC''').fetchall()
    except sqlite3.OperationalError:
        tips = db.execute('SELECT *, NULL as category_name FROM tips ORDER BY id DESC').fetchall()
    tips = [dict(t, thumb=_tip_thumb(t['image'])) for t in tips]
    return render_template('admin/tips.html', tips=tips, categories=_tip_categories(db))

@app.route('/admin/tips/edit/<int:tip_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_tip(tip_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    tip = db.execute('SELECT * FROM tips WHERE id = ?', (tip_id,)).fetchone()
    if tip is None:
        flash("Conseil introuvable.")
        return redirect(url_for('admin_tips'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        cat_raw = request.form.get('category_id', '')
        category_id = int(cat_raw) if cat_raw.isdigit() else None
        image_filename = tip['image']

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                page, error = save_tip_image(file, os.path.join(app.config['UPLOAD_FOLDER'], 'img'))
                if error:
                    flash(error)
                    return redirect(url_for('admin_edit_tip', tip_id=tip_id))
                _delete_managed_image(image_filename)
                image_filename = page

        try:
            db.execute('UPDATE tips SET title=?, content=?, image=?, category_id=? WHERE id=?',
                       (title, content, image_filename, category_id, tip_id))
        except sqlite3.OperationalError:
            db.execute('UPDATE tips SET title=?, content=?, image=? WHERE id=?',
                       (title, content, image_filename, tip_id))
        db.commit()
        flash('Conseil modifié.')
        return redirect(url_for('admin_tips'))

    return render_template('admin/tip_form.html', tip=tip, categories=_tip_categories(db))

@app.route('/admin/tip-categories', methods=['GET', 'POST'])
@login_required
def admin_tip_categories():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name:
            try:
                db.execute('INSERT INTO tip_categories (name) VALUES (?)', (name,))
                db.commit()
                flash('Catégorie créée.')
            except sqlite3.IntegrityError:
                flash('Cette catégorie existe déjà.')
        return redirect(url_for('admin_tip_categories'))
    return render_template('admin/tip_categories.html', categories=_tip_categories(db))

@app.route('/admin/tip-categories/edit/<int:cat_id>', methods=['POST'])
@login_required
def admin_edit_tip_category(cat_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    name = request.form.get('name', '').strip()
    if name:
        try:
            db.execute('UPDATE tip_categories SET name=? WHERE id=?', (name, cat_id))
            db.commit()
            flash('Catégorie renommée.')
        except sqlite3.IntegrityError:
            flash('Ce nom de catégorie existe déjà.')
    return redirect(url_for('admin_tip_categories'))

@app.route('/admin/tip-categories/delete/<int:cat_id>')
@login_required
def admin_delete_tip_category(cat_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    try:
        db.execute('UPDATE tips SET category_id=NULL WHERE category_id=?', (cat_id,))
    except sqlite3.OperationalError:
        pass
    db.execute('DELETE FROM tip_categories WHERE id=?', (cat_id,))
    db.commit()
    flash('Catégorie supprimée (les conseils sont conservés).')
    return redirect(url_for('admin_tip_categories'))

@app.route('/admin/tips/delete/<int:tip_id>')
@login_required
def admin_delete_tip(tip_id):
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    db.execute('DELETE FROM tips WHERE id = ?', (tip_id,))
    db.commit()
    flash('Conseil supprimé.')
    return redirect(url_for('admin_tips'))



@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)
