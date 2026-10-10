"""Blueprint auth : connexion / déconnexion (code V1 constant)."""
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from hinga import limiter
from hinga.db import get_db
from hinga.utils import valid_email, valid_password, valid_username

bp = Blueprint('auth', __name__)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Veuillez vous connecter pour accéder à cette page.")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# --- ROUTES AUTHENTIFICATION ---
@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('20/minute')
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
            return redirect(url_for('garden.index'))
        else:
            flash('Identifiants incorrects.')
    return render_template('login.html')

@bp.route('/logout')
def logout():
    session.clear()
    flash('Vous êtes déconnecté.')
    return redirect(url_for('auth.login'))


@bp.route('/charte')
def charte():
    return render_template('charte.html')


@bp.route('/mot-de-passe-oublie')
def password_help():
    return render_template('password_help.html')


@bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('10/hour')
def register():
    import uuid as uuidlib
    from datetime import datetime
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        email = request.form.get('email', '').strip()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        zone = request.form.get('zone', '').strip()[:80]
        presentation = request.form.get('presentation', '').strip()[:500]
        cherche = request.form.get('cherche', '').strip()[:300]
        offre = request.form.get('offre', '').strip()[:300]
        db = get_db()
        if not valid_username(username):
            flash('Pseudo invalide (3-30 lettres, chiffres, . _ -).')
        elif db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
            flash("Ce pseudo est déjà pris.")
        elif not valid_email(email):
            flash('Email invalide.')
        elif not valid_password(password):
            flash('Mot de passe trop court (8 caractères minimum).')
        elif request.form.get('rules') != 'on':
            flash('Vous devez accepter la charte de la communauté.')
        else:
            today = datetime.now().strftime('%Y-%m-%d')
            db.execute('''INSERT INTO users (username, password, role, first_name, last_name,
                          email, notes, is_active, status, zone, presentation, cherche, offre,
                          rules_accepted_at, created_at, uuid)
                          VALUES (?, ?, 'membre', ?, ?, ?, '', 1, 'pending', ?, ?, ?, ?, ?, ?, ?)''',
                       (username, generate_password_hash(password), first_name, last_name,
                        email, zone, presentation, cherche, offre, today, today, uuidlib.uuid4().hex))
            db.commit()
            flash('Inscription envoyée ! Un administrateur va la valider.')
            return redirect(url_for('auth.login'))
    return render_template('register.html')


@bp.route('/en-attente')
def pending():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    db = get_db()
    user = db.execute('SELECT status, motif FROM users WHERE id=?',
                      (session['user_id'],)).fetchone()
    if user is None:
        session.clear()
        return redirect(url_for('auth.login'))
    if user['status'] == 'approved':
        return redirect(url_for('garden.index'))
    return render_template('pending.html', status=user['status'], motif=user['motif'])

