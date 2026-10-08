"""Service d'upload d'images Hinga (Lot 3, réutilisable).

- Extensions : jpg, jpeg, png, webp (+ gif recopié tel quel).
- Valide le type réel (Pillow) et la taille (10 Mo max).
- Génère : version page (max 1200 px) + miniature (max 400 px),
  proportions conservées, orientation EXIF corrigée.
- Noms sûrs et uniques : <uuid>_page.<ext> / <uuid>_thumb.<ext>.
"""
import os

from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

from helpers import unique_filename

PAGE_MAX_SIZE = (1200, 1200)
THUMB_MAX_SIZE = (400, 400)
MAX_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'webp', 'gif'}


def thumb_name(page_filename: str) -> str:
    """Nom de la miniature dérivé de la version page."""
    stem, ext = os.path.splitext(page_filename or "")
    if not stem:
        return ""
    return f"{stem}_thumb{ext}"


def is_managed_image(filename: str) -> bool:
    """Vrai si le fichier suit la convention <uuid>_page.<ext>."""
    stem, _ext = os.path.splitext(filename or "")
    return stem.endswith("_page")


def _fitted_copy(img: Image.Image, max_size: tuple) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    out = img.copy()
    out.thumbnail(max_size, Image.LANCZOS)
    return out


def _save_pil(img: Image.Image, path: str, ext: str) -> None:
    if ext in ('jpg', 'jpeg'):
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        img.save(path, 'JPEG', quality=85, optimize=True)
    elif ext == 'png':
        img.save(path, 'PNG', optimize=True)
    elif ext == 'webp':
        img.save(path, 'WEBP', quality=85, method=4)
    else:
        img.save(path)


def save_tip_image(file_storage, dest_dir: str):
    """Valide et enregistre une image de conseil.

    Retourne (page_filename, erreur). En cas d'erreur, page_filename est None
    et erreur contient le message à flasher.
    """
    if file_storage is None or not getattr(file_storage, 'filename', ''):
        return None, "Aucun fichier reçu."

    ext = secure_filename(file_storage.filename).rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in ALLOWED_IMAGE_EXTS:
        return None, "Format refusé (jpg, jpeg, png, webp, gif uniquement)."

    # Taille (sans tout charger en mémoire deux fois)
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_BYTES:
        return None, "Image trop lourde (10 Mo maximum)."
    if size == 0:
        return None, "Fichier vide."

    base = unique_filename(f"tip.{ext}")
    stem, _ = os.path.splitext(base)
    page_filename = f"{stem}_page.{ext}"
    page_path = os.path.join(dest_dir, page_filename)

    if ext == 'gif':
        # GIF (souvent animé) : recopié tel quel, sans miniature
        file_storage.save(page_path)
        return page_filename, None

    try:
        img = Image.open(file_storage.stream)
        img.verify()
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)
        img.load()
    except Exception:
        return None, "Fichier image illisible."

    try:
        page = _fitted_copy(img, PAGE_MAX_SIZE)
        _save_pil(page, page_path, ext)
        thumb = _fitted_copy(img, THUMB_MAX_SIZE)
        _save_pil(thumb, os.path.join(dest_dir, thumb_name(page_filename)), ext)
    except Exception:
        for p in (page_path, os.path.join(dest_dir, thumb_name(page_filename))):
            if os.path.exists(p):
                os.remove(p)
        return None, "Échec du traitement de l'image."

    return page_filename, None
