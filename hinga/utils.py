"""Utilitaires partagés des blueprints (code V1 constant)."""
import os

from flask import current_app

from hinga.services.images import is_managed_image, thumb_name

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


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
