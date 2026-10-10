"""Utilitaires partagés des blueprints (code V1 constant)."""
import os
import re

from flask import current_app

from hinga.services.images import is_managed_image, thumb_name

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,30}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def valid_username(username):
    return bool(USERNAME_RE.match(username or ''))


def valid_email(email):
    return bool(EMAIL_RE.match((email or '').strip()))


def valid_password(password):
    return len(password or '') >= 8


def audit(action, target_kind='', target_id=None, details=''):
    """Trace une action admin (V2.1, table audit_log)."""
    from datetime import datetime

    from flask import session

    from hinga.db import get_db
    db = get_db()
    db.execute('''INSERT INTO audit_log (actor_id, action, target_kind, target_id, details, created_at)
                  VALUES (?,?,?,?,?,?)''',
               (session.get('user_id'), action, target_kind or '',
                target_id, details or '', datetime.now().strftime('%Y-%m-%d %H:%M')))
    db.commit()


def notify(user_id, kind, title, link=''):
    """Notification interne (V2.3). Silencieuse si table absente."""
    import sqlite3
    from datetime import datetime

    from hinga.db import get_db
    db = get_db()
    try:
        db.execute('''INSERT INTO notifications (user_id, kind, title, link, created_at)
                      VALUES (?,?,?,?,?)''',
                   (user_id, kind, title, link or '', datetime.now().strftime('%Y-%m-%d %H:%M')))
        db.commit()
    except sqlite3.OperationalError:
        pass


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _tip_thumb(image):
    """Miniature si gérée et présente sur disque, sinon l'image elle-même."""
    if is_managed_image(image):
        t = thumb_name(image)
        if os.path.exists(os.path.join(current_app.config['UPLOAD_FOLDER'], 'img', t)):
            return t
    return image


def _delete_managed_image(filename):
    """Supprime version page + miniature (fichiers gérés uniquement)."""
    if is_managed_image(filename):
        for f in (filename, thumb_name(filename)):
            p = os.path.join(current_app.config['UPLOAD_FOLDER'], 'img', f)
            if os.path.exists(p):
                os.remove(p)
