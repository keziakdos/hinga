"""Blueprint exchange : annonces don/échange/recherche (V2.2)."""
import sqlite3
import uuid as uuidlib
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from hinga.auth import login_required
from hinga.db import get_db
from hinga.services.images import is_managed_image, thumb_name
from hinga.services.images import save_tip_image
from hinga.utils import _delete_managed_image, audit, notify_admins

bp = Blueprint('exchange', __name__)

KINDS = (('don', 'Don'), ('echange', 'Échange'), ('recherche', 'Recherche'))
KIND_LABELS = dict(KINDS)
STATUSES = (('disponible', 'Disponible'), ('reserve', 'Réservé'), ('termine', 'Terminé'),
            ('masquee', 'Masquée (modération)'))
STATUS_LABELS = dict(STATUSES)
MAX_PHOTOS = 4


def _today():
    return datetime.now().strftime('%Y-%m-%d')


def expire_old(db):
    """Passe en 'terminé' les annonces à date dépassée (fainéant, une requête)."""
    db.execute("UPDATE listings SET status='termine', updated_at=? WHERE status='disponible' "
               "AND available_until IS NOT NULL AND available_until != '' AND available_until < ?",
               (_today(), _today()))
    db.commit()


def active_categories(db):
    try:
        return db.execute("SELECT * FROM listing_categories WHERE active=1 ORDER BY position, name").fetchall()
    except sqlite3.OperationalError:
        return []


def listing_photos(db, listing_id):
    try:
        rows = db.execute("SELECT * FROM listing_photos WHERE listing_id=? ORDER BY position",
                          (listing_id,)).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        d = dict(r)
        img = d['filename']
        if is_managed_image(img):
            t = thumb_name(img)
            import os
            if os.path.exists(os.path.join(current_app.config['UPLOAD_FOLDER'], 'img', t)):
                img = t
        d['thumb'] = img
        out.append(d)
    return out


@bp.route('/echanges')
def exchanges():
    db = get_db()
    expire_old(db)
    q = request.args.get('q', '').strip()[:80]
    cat = request.args.get('categorie', '')
    kind = request.args.get('type', '')
    zone = request.args.get('zone', '').strip()[:80]
    status = request.args.get('statut', 'disponible')
    tri = request.args.get('tri', 'recent')

    query = """SELECT l.*, c.name AS category_name, u.username AS owner
               FROM listings l
               LEFT JOIN listing_categories c ON l.category_id = c.id
               JOIN users u ON l.user_id = u.id WHERE l.status != 'masquee'"""
    params = []
    if status in ('disponible', 'reserve', 'termine'):
        query += " AND l.status = ?"
        params.append(status)
    if kind in ('don', 'echange', 'recherche'):
        query += " AND l.kind = ?"
        params.append(kind)
    if cat.isdigit():
        query += " AND l.category_id = ?"
        params.append(int(cat))
    if zone:
        query += " AND l.zone LIKE ?"
        params.append(f"%{zone}%")
    if q:
        query += " AND (l.title LIKE ? OR l.description LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    query += " ORDER BY l.created_at DESC, l.id DESC" if tri != 'ancien' else " ORDER BY l.created_at, l.id"
    query += " LIMIT 60"
    try:
        rows = db.execute(query, params).fetchall()
    except sqlite3.OperationalError:
        rows = []
    listings = []
    for r in rows:
        d = dict(r)
        photos = listing_photos(db, d['id'])
        d['photo'] = photos[0]['thumb'] if photos else None
        listings.append(d)
    return render_template('exchanges/list.html', listings=listings, categories=active_categories(db),
                           q=q, cat=cat, kind=kind, zone=zone, status=status, tri=tri,
                           kinds=KINDS, statuses=STATUSES)


@bp.route('/echanges/<int:listing_id>')
def exchange_detail(listing_id):
    db = get_db()
    expire_old(db)
    try:
        row = db.execute("""SELECT l.*, c.name AS category_name, u.username AS owner, u.zone AS owner_zone
                            FROM listings l
                            LEFT JOIN listing_categories c ON l.category_id = c.id
                            JOIN users u ON l.user_id = u.id WHERE l.id = ?""",
                         (listing_id,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row is None:
        flash("Annonce introuvable.")
        return redirect(url_for('exchange.exchanges'))
    listing = dict(row)
    if listing['status'] == 'masquee' and not (
            ('user_id' in session) and (session['user_id'] == listing['user_id']
                                        or session.get('role') in ('admin', 'moderateur'))):
        flash("Annonce masquée par la modération.")
        return redirect(url_for('exchange.exchanges'))
    db.execute("UPDATE listings SET views = views + 1 WHERE id = ?", (listing_id,))
    db.commit()
    mine = 'user_id' in session and session['user_id'] == listing['user_id']
    return render_template('exchanges/detail.html', listing=listing,
                           photos=listing_photos(db, listing_id), mine=mine,
                           kinds=KIND_LABELS, statuses=STATUS_LABELS)


@bp.route('/echanges/mes-annonces')
@login_required
def my_listings():
    db = get_db()
    try:
        rows = db.execute("""SELECT l.*, c.name AS category_name FROM listings l
                             LEFT JOIN listing_categories c ON l.category_id = c.id
                             WHERE l.user_id = ? ORDER BY l.created_at DESC""",
                          (session['user_id'],)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    listings = []
    for r in rows:
        d = dict(r)
        photos = listing_photos(db, d['id'])
        d['photo'] = photos[0]['thumb'] if photos else None
        listings.append(d)
    return render_template('exchanges/mine.html', listings=listings,
                           kinds=KIND_LABELS, statuses=STATUS_LABELS)


def _save_form(db, listing_id=None):
    """Crée ou met à jour une annonce depuis le formulaire. Retourne l'id ou None."""
    title = request.form.get('title', '').strip()[:120]
    description = request.form.get('description', '').strip()[:2000]
    kind = request.form.get('kind', 'don')
    if kind not in ('don', 'echange', 'recherche'):
        kind = 'don'
    cat_raw = request.form.get('category_id', '')
    category_id = int(cat_raw) if cat_raw.isdigit() else None
    quantity = request.form.get('quantity', '').strip()[:60]
    zone = request.form.get('zone', '').strip()[:80]
    available_until = request.form.get('available_until', '').strip()[:10]
    if not title or not description:
        flash('Titre et description sont obligatoires.')
        return None
    if listing_id:
        db.execute("""UPDATE listings SET kind=?, category_id=?, title=?, description=?,
                      quantity=?, zone=?, available_until=?, updated_at=? WHERE id=?""",
                   (kind, category_id, title, description, quantity, zone,
                    available_until, _today(), listing_id))
        db.commit()
        return listing_id
    cur = db.execute("""INSERT INTO listings (uuid, user_id, kind, category_id, title, description,
                      quantity, zone, available_until, status, views, created_at, updated_at)
                      VALUES (?,?,?,?,?,?,?,?,?,'disponible',0,?,?)""",
                     (uuidlib.uuid4().hex, session['user_id'], kind, category_id, title,
                      description, quantity, zone, available_until, _today(), _today()))
    db.commit()
    return cur.lastrowid


def _store_photos(db, listing_id):
    """Enregistre les photos uploadées (max 4 au total)."""
    existing = db.execute("SELECT COUNT(*) FROM listing_photos WHERE listing_id=?",
                          (listing_id,)).fetchone()[0]
    for file in request.files.getlist('photos'):
        if not file or not file.filename:
            continue
        if existing >= MAX_PHOTOS:
            flash(f'Maximum {MAX_PHOTOS} photos par annonce.')
            break
        page, error = save_tip_image(file, current_app.config['UPLOAD_FOLDER'] + '/img')
        if error:
            flash(error)
            continue
        pos = db.execute("SELECT COALESCE(MAX(position), -1)+1 FROM listing_photos WHERE listing_id=?",
                         (listing_id,)).fetchone()[0]
        db.execute("INSERT INTO listing_photos (listing_id, filename, position) VALUES (?,?,?)",
                   (listing_id, page, pos))
        existing += 1
    db.commit()


@bp.route('/echanges/nouvelle', methods=['GET', 'POST'])
@login_required
def exchange_new():
    db = get_db()
    if request.method == 'POST':
        lid = _save_form(db)
        if lid is None:
            return redirect(url_for('exchange.exchange_new'))
        _store_photos(db, lid)
        audit('listing_create', 'listing', lid, 'annonce créée')
        flash('Annonce publiée !')
        return redirect(url_for('exchange.exchange_detail', listing_id=lid))
    me = db.execute('SELECT zone FROM users WHERE id=?', (session['user_id'],)).fetchone()
    return render_template('exchanges/form.html', listing=None, categories=active_categories(db),
                           kinds=KINDS, my_zone=me['zone'] if me else '')


@bp.route('/echanges/<int:listing_id>/modifier', methods=['GET', 'POST'])
@login_required
def exchange_edit(listing_id):
    db = get_db()
    listing = db.execute('SELECT * FROM listings WHERE id=?', (listing_id,)).fetchone()
    if listing is None:
        flash("Annonce introuvable.")
        return redirect(url_for('exchange.exchanges'))
    if session['user_id'] != listing['user_id'] and session.get('role') != 'admin':
        flash('Cette annonce ne vous appartient pas.')
        return redirect(url_for('exchange.exchange_detail', listing_id=listing_id))
    if request.method == 'POST':
        if _save_form(db, listing_id) is None:
            return redirect(url_for('exchange.exchange_edit', listing_id=listing_id))
        _store_photos(db, listing_id)
        audit('listing_edit', 'listing', listing_id, 'annonce modifiée')
        flash('Annonce mise à jour.')
        return redirect(url_for('exchange.exchange_detail', listing_id=listing_id))
    return render_template('exchanges/form.html', listing=listing,
                           photos=listing_photos(db, listing_id),
                           categories=active_categories(db), kinds=KINDS, my_zone='')


@bp.route('/echanges/photo/<int:photo_id>/supprimer')
@login_required
def exchange_photo_delete(photo_id):
    db = get_db()
    photo = db.execute("""SELECT p.*, l.user_id FROM listing_photos p
                          JOIN listings l ON p.listing_id = l.id WHERE p.id=?""", (photo_id,)).fetchone()
    if photo is None:
        return redirect(url_for('exchange.exchanges'))
    if session['user_id'] != photo['user_id'] and session.get('role') != 'admin':
        flash('Action interdite.')
        return redirect(url_for('exchange.exchange_detail', listing_id=photo['listing_id']))
    _delete_managed_image(photo['filename'])
    db.execute('DELETE FROM listing_photos WHERE id=?', (photo_id,))
    db.commit()
    flash('Photo supprimée.')
    return redirect(url_for('exchange.exchange_edit', listing_id=photo['listing_id']))


@bp.route('/echanges/<int:listing_id>/termine', methods=['POST'])
@login_required
def exchange_done(listing_id):
    db = get_db()
    listing = db.execute('SELECT user_id FROM listings WHERE id=?', (listing_id,)).fetchone()
    if listing is None:
        return redirect(url_for('exchange.exchanges'))
    if session['user_id'] != listing['user_id'] and session.get('role') != 'admin':
        flash('Action interdite.')
        return redirect(url_for('exchange.exchange_detail', listing_id=listing_id))
    db.execute("UPDATE listings SET status='termine', updated_at=? WHERE id=?", (_today(), listing_id))
    db.commit()
    audit('listing_done', 'listing', listing_id, 'annonce marquée terminée')
    flash('Annonce marquée comme terminée.')
    return redirect(url_for('exchange.exchange_detail', listing_id=listing_id))


@bp.route('/echanges/<int:listing_id>/signaler', methods=['POST'])
@login_required
def exchange_report(listing_id):
    db = get_db()
    reason = request.form.get('reason', '').strip()[:40] or 'Autre'
    details = request.form.get('details', '').strip()[:500]
    exists = db.execute("""SELECT id FROM reports WHERE target_kind='listing' AND target_id=?
                           AND reporter_id=? AND status='open'""",
                        (listing_id, session['user_id'])).fetchone()
    if exists:
        flash('Vous avez déjà signalé cette annonce.')
    else:
        db.execute("""INSERT INTO reports (reporter_id, target_kind, target_id, reason, details, status, created_at)
                      VALUES (?,?,?,?,?, 'open', ?)""",
                   (session['user_id'], 'listing', listing_id, reason, details, _today()))
        db.commit()
        notify_admins('signalement', f"Annonce #{listing_id} signalée ({reason})",
                      '/admin/moderation')
        flash('Annonce signalée, merci. Un modérateur va l’examiner.')
    return redirect(url_for('exchange.exchange_detail', listing_id=listing_id))
