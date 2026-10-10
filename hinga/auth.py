"""Blueprint auth : connexion / déconnexion (code V1 constant)."""
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from hinga import limiter
from hinga.db import get_db

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

