"""Paquet Hinga : fabrique applicative + blueprints (V2)."""
import os

from dotenv import load_dotenv
from flask import Flask, render_template

# Charger les variables d'environnement (.env)
load_dotenv()

from hinga.helpers import MOIS_FR, MOIS_FR_ABBR, mois_nom, periode_label, month_in_range  # noqa: E402

app = Flask(__name__, template_folder='../templates', static_folder='../static')

_secret = os.environ.get('SECRET_KEY')
if not _secret:
    if os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError('SECRET_KEY manquante : renseignez-la dans le .env (prod).')
    _secret = 'dev-local-uniquement'
    print('⚠️  SECRET_KEY absente : clé de développement (ne pas utiliser en production).')
app.secret_key = _secret


@app.context_processor
def inject_helpers():
    from flask import session
    unread_msg, unread_notif = 0, 0
    if 'user_id' in session:
        try:
            from hinga.db import get_db
            db = get_db()
            unread_msg = db.execute("SELECT COUNT(*) FROM messages m JOIN conversations c "
                                    "ON m.conversation_id=c.id WHERE (c.user_a=? OR c.user_b=?) "
                                    "AND m.author_id!=? AND (m.read_at IS NULL OR m.read_at='')",
                                    (session['user_id'], session['user_id'],
                                     session['user_id'])).fetchone()[0]
            unread_notif = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? "
                                      "AND (read_at IS NULL OR read_at='')",
                                      (session['user_id'],)).fetchone()[0]
        except Exception:
            pass
    return dict(
        mois_nom=mois_nom, periode_label=periode_label,
        month_in_range=month_in_range, MOIS_FR=MOIS_FR, MOIS_FR_ABBR=MOIS_FR_ABBR,
        unread_msg=unread_msg, unread_notif=unread_notif,
    )

# Racine projet (static/, hinga.db vivent à côté du paquet)
basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static')
app.config['DATABASE'] = os.path.join(basedir, 'hinga.db')

# Sessions : HttpOnly + SameSite stricts ; Secure en prod (SESSION_COOKIE_SECURE=1).
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'

from flask_limiter import Limiter  # noqa: E402
from flask_limiter.util import get_remote_address  # noqa: E402
from flask_wtf import CSRFProtect  # noqa: E402

csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app)

from hinga.db import close_connection  # noqa: E402
app.teardown_appcontext(close_connection)

from hinga import auth, garden, admin, exchange, social  # noqa: E402
app.register_blueprint(auth.bp)
app.register_blueprint(garden.bp)
app.register_blueprint(admin.bp)
app.register_blueprint(exchange.bp)
app.register_blueprint(social.bp)


@app.before_request
def check_account_status():
    """Comptes non approuvés : seul le message d'attente (+ déconnexion)."""
    from flask import redirect, request, session, url_for, flash
    from hinga.db import get_db
    if request.endpoint in (None, 'static'):
        return None
    if 'user_id' not in session:
        return None
    if request.endpoint in ('auth.login', 'auth.logout', 'auth.pending',
                            'auth.register', 'auth.password_help', 'auth.charte'):
        return None
    db = get_db()
    user = db.execute('SELECT status, is_active FROM users WHERE id=?',
                      (session['user_id'],)).fetchone()
    if user is None:
        session.clear()
        return redirect(url_for('auth.login'))
    if not user['is_active']:
        session.clear()
        flash('Compte désactivé. Contactez un administrateur.')
        return redirect(url_for('auth.login'))
    session['status'] = user['status']
    if user['status'] != 'approved':
        return redirect(url_for('auth.pending'))
    return None


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


@app.errorhandler(429)
def too_many_requests(e):
    return render_template('429.html'), 429
