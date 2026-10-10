"""Accès SQLite + initialisation (code V1 constant)."""
import sqlite3

from flask import current_app, g
from werkzeug.security import generate_password_hash


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(current_app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db


def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    from hinga import app
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
