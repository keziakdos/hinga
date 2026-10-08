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

from helpers import MOIS_FR, MOIS_FR_ABBR, mois_nom, periode_label, month_in_range, plants_for_month

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



ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

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

# --- ROUTES PUBLIQUES (Calendrier, Fiche Plante, Conseils) ---
@app.route('/')
def index():
    return redirect(url_for('calendar'))

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
        tips_list = db.execute('''SELECT t.*, c.name as category_name FROM tips t
                                  LEFT JOIN tip_categories c ON t.category_id = c.id''').fetchall()
    except sqlite3.OperationalError:
        tips_list = db.execute('SELECT *, NULL as category_name FROM tips').fetchall()
    return render_template('tips.html', tips=tips_list)

@app.route('/tip/<int:tip_id>')
def tip_details(tip_id):
    db = get_db()
    try:
        tip = db.execute('''SELECT t.*, c.name as category_name FROM tips t
                            LEFT JOIN tip_categories c ON t.category_id = c.id
                            WHERE t.id = ?''', (tip_id,)).fetchone()
    except sqlite3.OperationalError:
        tip = db.execute('SELECT *, NULL as category_name FROM tips WHERE id = ?', (tip_id,)).fetchone()
    if not tip: return "Conseil introuvable", 404
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

    # Seules les récoltes de l'utilisateur connecté
    harvests_list = db.execute('SELECT h.*, p.name as plant_name FROM harvests h JOIN plants p ON h.plant_id = p.id WHERE h.user_id = ? ORDER BY h.date DESC', (user_id,)).fetchall()
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
        SELECT p.name, SUM(h.quantity) FROM harvests h 
        JOIN plants p ON h.plant_id = p.id 
        WHERE h.user_id = ? GROUP BY p.name ORDER BY SUM(h.quantity) DESC
    ''', (user_id,)).fetchall()
    
    plant_labels = [row[0] for row in rows_plants]
    plant_data = [row[1] for row in rows_plants]

    monthly_map = {f"{i:02d}": 0 for i in range(1, 13)}
    rows_months = db.execute("SELECT strftime('%m', date) as m, SUM(quantity) FROM harvests WHERE user_id = ? GROUP BY m", (user_id,)).fetchall()
    for row in rows_months:
        if row[0] in monthly_map: monthly_map[row[0]] = row[1]
            
    month_labels_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']
    month_values = list(monthly_map.values())

    return render_template('stats.html', total_weight=round(total_weight, 2),
                           plant_labels=json.dumps(plant_labels), plant_data=json.dumps(plant_data),
                           month_labels=json.dumps(month_labels_fr), month_values=json.dumps(month_values))









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

        # Sauvegarde image
        filename = secure_filename(f"user_{user_id}_{int(datetime.now().timestamp())}.jpg")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'img', filename)
        file.save(filepath)
        
        try:
            base64_image = encode_image(filepath)

            # --- LE NOUVEAU PROMPT PLUS COMPLET ---
            prompt_text = """
            Tu es un expert botaniste. Analyse cette image.
            Réponds UNIQUEMENT au format JSON strict avec cette structure :
            {
                "name": "Nom commun (Nom latin)",
                "confidence": "XX%",
                "strengths": ["Point fort 1", "Point fort 2"],
                "weaknesses": ["Maladie ou problème 1", "Problème 2"],
                "advice": "Conseil principal pour le soin.",
                "details": {
                    "sun": "Exposition idéale (ex: Plein soleil)",
                    "water": "Besoins en eau (ex: 2x par semaine)",
                    "soil": "Type de sol idéal",
                    "hardiness": "Résistance au froid/Climat"
                }
            }
            Si ce n'est pas une plante, mets "Non identifié" dans le name. En Français.
            """

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                max_tokens=700
            )

            ai_json = json.loads(response.choices[0].message.content)

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
            flash(f"Erreur IA : {str(e)}")
            print(e)

    # Récupérer l'historique
    monitored = db.execute('SELECT * FROM monitored_plants WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
            
    return render_template('maplante.html', result=result, monitored=monitored)




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
        username = request.form['username']
        password = request.form['password']
        # Vérif si existe déjà
        exist = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if exist:
            flash('Ce nom d\'utilisateur existe déjà.')
        else:
            pwd_hash = generate_password_hash(password)
            db.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)', (username, pwd_hash, 'user'))
            db.commit()
            flash(f'Utilisateur {username} créé !')
        return redirect(url_for('admin_users'))
        
    users = db.execute('SELECT * FROM users').fetchall()
    return render_template('admin/users.html', users=users)

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

        # Gestion image (inchangée)
        image_filename = request.form.get('current_image')
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '' and allowed_file(file.filename):
                image_filename = secure_filename(file.filename)
                # Utilisation du chemin absolu basedir défini plus haut
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'img', image_filename))

        if plant_id:
            # UPDATE AVEC LES NOUVEAUX CHAMPS
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
    
    return render_template('admin/plant_form.html', plant=plant)











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
@app.route('/admin/tips', methods=['GET', 'POST'])
@login_required
def admin_tips():
    if session.get('role') != 'admin': return redirect(url_for('index'))
    db = get_db()
    
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        image_filename = 'default_tip.jpg'
        
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '' and allowed_file(file.filename):
                image_filename = secure_filename(file.filename)


                # On utilise le bon chemin UPLOAD_FOLDER qui pointe vers static
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'img', image_filename))

        
        db.execute('INSERT INTO tips (title, content, image) VALUES (?,?,?)', (title, content, image_filename))
        db.commit()
        flash('Conseil ajouté.')
        return redirect(url_for('admin_tips'))

    tips = db.execute('SELECT * FROM tips').fetchall()
    return render_template('admin/tips.html', tips=tips)

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
