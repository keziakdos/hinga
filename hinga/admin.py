"""Blueprint admin : plantes, conseils, utilisateurs (V1 constant)."""
import os
import sqlite3
from datetime import datetime  # noqa: F401 (compat)

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from hinga.auth import login_required
from hinga.db import get_db
from hinga.helpers import MOIS_FR, PLANT_TYPES, unique_filename
from hinga.services.images import is_managed_image, save_tip_image, thumb_name  # noqa: F401
from hinga.utils import _delete_managed_image, _tip_thumb, allowed_file, audit  # noqa: F401
from hinga.utils import notify, valid_email, valid_password, valid_username

bp = Blueprint('admin', __name__)

ROLES = ('membre', 'moderateur', 'admin')


def active_admin_count(db):
    return db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0]


def is_last_admin(db, user_id):
    row = db.execute("SELECT role, is_active FROM users WHERE id=?", (user_id,)).fetchone()
    return bool(row and row['role'] == 'admin' and row['is_active']
                and active_admin_count(db) <= 1)

# --- SECTION ADMINISTRATION ---

@bp.route('/admin')
@login_required
def admin_dashboard():
    if session.get('role') != 'admin':
        flash('Accès réservé aux administrateurs.')
        return redirect(url_for('garden.index'))
    return render_template('admin/dashboard.html')

# --- GESTION UTILISATEURS & MEMBRES (V2.1 : approbation, rôles, audit) ---
@bp.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()

    if request.method == 'POST':
        # Création directe par un admin (compte approuvé d'office)
        import uuid as uuidlib
        from datetime import datetime
        username = request.form['username'].strip()
        password = request.form['password']
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        notes = request.form.get('notes', '').strip()
        exist = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if exist:
            flash('Ce nom d\'utilisateur existe déjà.')
        elif not valid_username(username):
            flash('Pseudo invalide (3-30 lettres, chiffres, . _ -).')
        elif not valid_password(password):
            flash('Mot de passe trop court (8 caractères minimum).')
        elif email and not valid_email(email):
            flash('Email invalide.')
        else:
            pwd_hash = generate_password_hash(password)
            today = datetime.now().strftime('%Y-%m-%d')
            cur = db.execute('''INSERT INTO users (username, password, role, first_name, last_name,
                              email, notes, is_active, status, created_at, uuid)
                              VALUES (?, ?, 'membre', ?, ?, ?, ?, 1, 'approved', ?, ?)''',
                       (username, pwd_hash, first_name, last_name, email, notes, today, uuidlib.uuid4().hex))
            db.commit()
            audit('user_create', 'user', cur.lastrowid, f"création de {username}")
            flash(f'Utilisateur {username} créé !')
        return redirect(url_for('admin.admin_users'))

    pending = db.execute("SELECT * FROM users WHERE status='pending' ORDER BY created_at").fetchall()
    refused = db.execute("SELECT * FROM users WHERE status='refused' ORDER BY created_at DESC").fetchall()
    suspended = db.execute("SELECT * FROM users WHERE status='suspended' ORDER BY username").fetchall()
    members = db.execute("SELECT * FROM users WHERE status='approved' ORDER BY username").fetchall()
    # Qui a approuvé / créé chaque membre, et quand (journal d'audit)
    approvals = {}
    try:
        for r in db.execute("""SELECT a.target_id, a.action, a.created_at, u.username AS actor
                               FROM audit_log a LEFT JOIN users u ON a.actor_id = u.id
                               WHERE a.target_kind='user' AND a.action IN ('user_approve','user_create')
                               ORDER BY a.id""").fetchall():
            tid = r['target_id']
            cur = approvals.get(tid)
            if cur is None or (cur['action'] != 'user_approve' and r['action'] == 'user_approve'):
                approvals[tid] = dict(actor=r['actor'] or '?', date=r['created_at'],
                                      action=r['action'])
    except sqlite3.OperationalError:
        pass
    return render_template('admin/users.html', pending=pending, refused=refused,
                           suspended=suspended, members=members, approvals=approvals)


@bp.route('/admin/users/status/<int:user_id>', methods=['POST'])
@login_required
def admin_user_status(user_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    target = db.execute('SELECT username, status FROM users WHERE id=?', (user_id,)).fetchone()
    if target is None:
        flash("Utilisateur introuvable.")
        return redirect(url_for('admin.admin_users'))
    do = request.form.get('do', '')
    motif = request.form.get('motif', '').strip()[:300]
    name = target['username']
    if do == 'approve':
        db.execute("UPDATE users SET status='approved', is_active=1, motif='' WHERE id=?", (user_id,))
        db.commit()
        audit('user_approve', 'user', user_id, f"approbation de {name}")
        notify(user_id, 'compte', 'Bienvenue sur Hinga ! Votre compte est approuvé.', '/echanges')
        flash(f'{name} approuvé, bienvenue !')
    elif do == 'refuse':
        db.execute("UPDATE users SET status='refused', motif=? WHERE id=?", (motif, user_id))
        db.commit()
        audit('user_refuse', 'user', user_id, f"refus de {name} : {motif}")
        flash(f'Demande de {name} refusée.')
    elif do == 'suspend':
        if is_last_admin(db, user_id):
            flash('Impossible : dernier administrateur.')
        else:
            db.execute("UPDATE users SET status='suspended', is_active=0, motif=? WHERE id=?", (motif, user_id))
            db.commit()
            audit('user_suspend', 'user', user_id, f"suspension de {name} : {motif}")
            flash(f'{name} suspendu.')
    elif do == 'reactivate':
        db.execute("UPDATE users SET status='approved', is_active=1, motif='' WHERE id=?", (user_id,))
        db.commit()
        audit('user_reactivate', 'user', user_id, f"réactivation de {name}")
        flash(f'{name} réactivé.')
    return redirect(url_for('admin.admin_users'))

@bp.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if user is None:
        flash("Utilisateur introuvable.")
        return redirect(url_for('admin.admin_users'))

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        if email and not valid_email(email):
            flash('Email invalide.')
            return redirect(url_for('admin.admin_edit_user', user_id=user_id))
        notes = request.form.get('notes', '').strip()
        motif = request.form.get('motif', '').strip()[:300]
        role = request.form.get('role', 'membre')
        if role not in ROLES:
            role = user['role'] if user['role'] in ROLES else 'membre'
        # Impossible de désactiver son propre compte ou de se rétrograder
        if user_id == session['user_id']:
            is_active = 1
            role = user['role']
        else:
            is_active = 1 if request.form.get('is_active') else 0
            if user['role'] == 'admin' and role != 'admin' and is_last_admin(db, user_id):
                flash('Impossible : dernier administrateur.')
                return redirect(url_for('admin.admin_users'))
            if not is_active and is_last_admin(db, user_id):
                flash('Impossible : dernier administrateur.')
                return redirect(url_for('admin.admin_users'))
        old_role = user['role']
        db.execute('''UPDATE users SET first_name=?, last_name=?, email=?, notes=?, motif=?, role=?, is_active=?
                      WHERE id=?''', (first_name, last_name, email, notes, motif, role, is_active, user_id))
        if old_role != role:
            audit('user_role', 'user', user_id, f"{user['username']} : {old_role} -> {role}")
        new_password = request.form.get('new_password', '')
        if new_password:
            if not valid_password(new_password):
                flash('Nouveau mot de passe trop court (8 minimum), non modifié.')
            else:
                db.execute('UPDATE users SET password=? WHERE id=?',
                           (generate_password_hash(new_password), user_id))
                audit('user_password', 'user', user_id, f"mot de passe redéfini pour {user['username']}")
        db.commit()
        audit('user_edit', 'user', user_id, f"fiche de {user['username']} mise à jour")
        flash('Utilisateur mis à jour.')
        return redirect(url_for('admin.admin_users'))

    return render_template('admin/user_form.html', user=user)

@bp.route('/admin/users/delete/<int:user_id>')
@login_required
def admin_delete_user(user_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    # On empêche de se supprimer soi-même, ainsi que le dernier admin
    if user_id == session['user_id']:
        flash('Impossible de supprimer votre propre compte ici.')
    else:
        db = get_db()
        target = db.execute('SELECT username FROM users WHERE id=?', (user_id,)).fetchone()
        if target is None:
            flash("Utilisateur introuvable.")
        elif is_last_admin(db, user_id):
            flash('Impossible : dernier administrateur.')
        else:
            db.execute('DELETE FROM users WHERE id = ?', (user_id,))
            db.commit()
            audit('user_delete', 'user', user_id, f"suppression de {target['username']}")
            flash('Utilisateur supprimé.')
    return redirect(url_for('admin.admin_users'))


@bp.route('/admin/audit')
@login_required
def admin_audit():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    try:
        entries = db.execute('''SELECT a.*, u.username AS actor FROM audit_log a
                                LEFT JOIN users u ON a.actor_id = u.id
                                ORDER BY a.id DESC LIMIT 200''').fetchall()
    except sqlite3.OperationalError:
        entries = []
    return render_template('admin/audit.html', entries=entries)

# --- GESTION PLANTES ---
@bp.route('/admin/plants')
@login_required
def admin_plants():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    plants = db.execute('SELECT * FROM plants ORDER BY name').fetchall()
    return render_template('admin/plants.html', plants=plants)












@bp.route('/admin/plants/edit', methods=['GET', 'POST'])
@bp.route('/admin/plants/edit/<int:plant_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_plant(plant_id=None):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
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
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], 'img', image_filename))

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
            audit('plant_edit', 'plant', plant_id, f"fiche {name} modifiée")
        else:
            # INSERT AVEC LES NOUVEAUX CHAMPS
            if not image_filename: image_filename = 'default.jpg'
            db.execute('''INSERT INTO plants (name, type, sow_start, sow_end, harvest_start, harvest_end, details, conditions, roots, image,
                          section_sun, section_soil, section_water, section_sowing, section_diseases, section_harvest)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (name, ptype, sow_start, sow_end, har_start, har_end, details, conditions, roots, image_filename,
                        sec_sun, sec_soil, sec_water, sec_sowing, sec_diseases, sec_harvest))
            flash('Nouvelle plante ajoutée.')
            audit('plant_create', 'plant', None, f"fiche {name} créée")
        db.commit()
        return redirect(url_for('admin.admin_plants'))

    plant = None
    if plant_id:
        plant = db.execute('SELECT * FROM plants WHERE id = ?', (plant_id,)).fetchone()
    
    return render_template('admin/plant_form.html', plant=plant, plant_types=PLANT_TYPES, mois=MOIS_FR)











@bp.route('/admin/plants/delete/<int:plant_id>')
@login_required
def admin_delete_plant(plant_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    target = db.execute('SELECT name FROM plants WHERE id=?', (plant_id,)).fetchone()
    db.execute('DELETE FROM plants WHERE id = ?', (plant_id,))
    db.commit()
    audit('plant_delete', 'plant', plant_id, f"fiche {target['name'] if target else plant_id} supprimée")
    flash('Plante supprimée.')
    return redirect(url_for('admin.admin_plants'))

# --- GESTION CONSEILS (Tips) ---
def _tip_categories(db):
    try:
        return db.execute('SELECT * FROM tip_categories ORDER BY name').fetchall()
    except sqlite3.OperationalError:
        return []

@bp.route('/admin/tips', methods=['GET', 'POST'])
@login_required
def admin_tips():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
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
                page, error = save_tip_image(file, os.path.join(current_app.config['UPLOAD_FOLDER'], 'img'))
                if error:
                    flash(error)
                    return redirect(url_for('admin.admin_tips'))
                image_filename = page

        try:
            db.execute('INSERT INTO tips (title, content, image, category_id) VALUES (?,?,?,?)',
                       (title, content, image_filename, category_id))
        except sqlite3.OperationalError:
            db.execute('INSERT INTO tips (title, content, image) VALUES (?,?,?)',
                       (title, content, image_filename))
        db.commit()
        audit('tip_create', 'tip', None, f"conseil {title} créé")
        flash('Conseil ajouté.')
        return redirect(url_for('admin.admin_tips'))

    try:
        tips = db.execute('''SELECT t.*, c.name as category_name FROM tips t
                             LEFT JOIN tip_categories c ON t.category_id = c.id
                             ORDER BY t.id DESC''').fetchall()
    except sqlite3.OperationalError:
        tips = db.execute('SELECT *, NULL as category_name FROM tips ORDER BY id DESC').fetchall()
    tips = [dict(t, thumb=_tip_thumb(t['image'])) for t in tips]
    return render_template('admin/tips.html', tips=tips, categories=_tip_categories(db))

@bp.route('/admin/tips/edit/<int:tip_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_tip(tip_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    tip = db.execute('SELECT * FROM tips WHERE id = ?', (tip_id,)).fetchone()
    if tip is None:
        flash("Conseil introuvable.")
        return redirect(url_for('admin.admin_tips'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        cat_raw = request.form.get('category_id', '')
        category_id = int(cat_raw) if cat_raw.isdigit() else None
        image_filename = tip['image']

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                page, error = save_tip_image(file, os.path.join(current_app.config['UPLOAD_FOLDER'], 'img'))
                if error:
                    flash(error)
                    return redirect(url_for('admin.admin_edit_tip', tip_id=tip_id))
                _delete_managed_image(image_filename)
                image_filename = page

        try:
            db.execute('UPDATE tips SET title=?, content=?, image=?, category_id=? WHERE id=?',
                       (title, content, image_filename, category_id, tip_id))
        except sqlite3.OperationalError:
            db.execute('UPDATE tips SET title=?, content=?, image=? WHERE id=?',
                       (title, content, image_filename, tip_id))
        db.commit()
        audit('tip_edit', 'tip', tip_id, f"conseil {title} modifié")
        flash('Conseil modifié.')
        return redirect(url_for('admin.admin_tips'))

    return render_template('admin/tip_form.html', tip=tip, categories=_tip_categories(db))

@bp.route('/admin/tip-categories', methods=['GET', 'POST'])
@login_required
def admin_tip_categories():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name:
            try:
                db.execute('INSERT INTO tip_categories (name) VALUES (?)', (name,))
                db.commit()
                audit('tipcat_create', 'tip_category', None, f"catégorie {name} créée")
                flash('Catégorie créée.')
            except sqlite3.IntegrityError:
                flash('Cette catégorie existe déjà.')
        return redirect(url_for('admin.admin_tip_categories'))
    return render_template('admin/tip_categories.html', categories=_tip_categories(db))

@bp.route('/admin/tip-categories/edit/<int:cat_id>', methods=['POST'])
@login_required
def admin_edit_tip_category(cat_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    name = request.form.get('name', '').strip()
    if name:
        try:
            db.execute('UPDATE tip_categories SET name=? WHERE id=?', (name, cat_id))
            db.commit()
            audit('tipcat_rename', 'tip_category', cat_id, f"renommée en {name}")
            flash('Catégorie renommée.')
        except sqlite3.IntegrityError:
            flash('Ce nom de catégorie existe déjà.')
    return redirect(url_for('admin.admin_tip_categories'))

@bp.route('/admin/tip-categories/delete/<int:cat_id>')
@login_required
def admin_delete_tip_category(cat_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    try:
        db.execute('UPDATE tips SET category_id=NULL WHERE category_id=?', (cat_id,))
    except sqlite3.OperationalError:
        pass
    db.execute('DELETE FROM tip_categories WHERE id=?', (cat_id,))
    db.commit()
    audit('tipcat_delete', 'tip_category', cat_id, 'catégorie supprimée')
    flash('Catégorie supprimée (les conseils sont conservés).')
    return redirect(url_for('admin.admin_tip_categories'))

@bp.route('/admin/tips/delete/<int:tip_id>')
@login_required
def admin_delete_tip(tip_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    target = db.execute('SELECT title FROM tips WHERE id=?', (tip_id,)).fetchone()
    db.execute('DELETE FROM tips WHERE id = ?', (tip_id,))
    db.commit()
    audit('tip_delete', 'tip', tip_id, f"conseil {target['title'] if target else tip_id} supprimé")
    flash('Conseil supprimé.')
    return redirect(url_for('admin.admin_tips'))




# --- CATEGORIES D'ANNONCES (V2.2 : ordre, actif, sous-catégories) ---
def _listing_cats(db):
    try:
        return db.execute("SELECT * FROM listing_categories ORDER BY position, name").fetchall()
    except sqlite3.OperationalError:
        return []


@bp.route('/admin/annonces-categories', methods=['GET', 'POST'])
@login_required
def admin_listing_categories():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    if request.method == 'POST':
        import uuid as uuidlib
        from datetime import datetime
        name = request.form.get('name', '').strip()[:80]
        parent_raw = request.form.get('parent_id', '')
        parent_id = int(parent_raw) if parent_raw.isdigit() else None
        if name:
            pos = db.execute("SELECT COALESCE(MAX(position), -1)+1 FROM listing_categories").fetchone()[0]
            db.execute("""INSERT INTO listing_categories (uuid, name, parent_id, position, active, created_at)
                          VALUES (?,?,?,?,1,?)""",
                       (uuidlib.uuid4().hex, name, parent_id, pos,
                        datetime.now().strftime('%Y-%m-%d')))
            db.commit()
            audit('lcat_create', 'listing_category', None, f"catégorie annonce {name} créée")
            flash('Catégorie créée.')
        return redirect(url_for('admin.admin_listing_categories'))
    cats = _listing_cats(db)
    by_id = {c['id']: dict(c) for c in cats}
    for c in by_id.values():
        c['children'] = [x for x in cats if x['parent_id'] == c['id']]
    roots = [by_id[c['id']] for c in cats if not c['parent_id']]
    return render_template('admin/listing_categories.html', roots=roots)


@bp.route('/admin/annonces-categories/edit/<int:cat_id>', methods=['POST'])
@login_required
def admin_edit_listing_category(cat_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    name = request.form.get('name', '').strip()[:80]
    parent_raw = request.form.get('parent_id', '')
    parent_id = int(parent_raw) if parent_raw.isdigit() else None
    active = 1 if request.form.get('active') else 0
    if parent_id == cat_id:
        parent_id = None
    if name:
        db.execute("UPDATE listing_categories SET name=?, parent_id=?, active=? WHERE id=?",
                   (name, parent_id, active, cat_id))
        db.commit()
        audit('lcat_edit', 'listing_category', cat_id, f"renommée en {name}")
        flash('Catégorie mise à jour.')
    return redirect(url_for('admin.admin_listing_categories'))


@bp.route('/admin/annonces-categories/move/<int:cat_id>', methods=['POST'])
@login_required
def admin_move_listing_category(cat_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    direction = request.form.get('dir', 'up')
    cats = list(db.execute("SELECT id, position FROM listing_categories ORDER BY position").fetchall())
    ids = [c['id'] for c in cats]
    if cat_id in ids:
        i = ids.index(cat_id)
        j = i - 1 if direction == 'up' else i + 1
        if 0 <= j < len(ids):
            a, b = cats[i], cats[j]
            db.execute("UPDATE listing_categories SET position=? WHERE id=?", (b['position'], a['id']))
            db.execute("UPDATE listing_categories SET position=? WHERE id=?", (a['position'], b['id']))
            db.commit()
    return redirect(url_for('admin.admin_listing_categories'))


@bp.route('/admin/annonces-categories/delete/<int:cat_id>')
@login_required
def admin_delete_listing_category(cat_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    kids = db.execute("SELECT COUNT(*) FROM listing_categories WHERE parent_id=?", (cat_id,)).fetchone()[0]
    used = db.execute("SELECT COUNT(*) FROM listings WHERE category_id=?", (cat_id,)).fetchone()[0]
    if kids:
        flash('Impossible : cette catégorie a des sous-catégories.')
    elif used:
        flash(f'Impossible : {used} annonce(s) utilisent cette catégorie.')
    else:
        db.execute('DELETE FROM listing_categories WHERE id=?', (cat_id,))
        db.commit()
        audit('lcat_delete', 'listing_category', cat_id, 'catégorie annonce supprimée')
        flash('Catégorie supprimée.')
    return redirect(url_for('admin.admin_listing_categories'))

# --- INDICATEURS D'IMPACT (V2.4) ---
@bp.route('/admin/impact')
@login_required
def admin_impact():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    impact = {}
    try:
        impact['membres'] = db.execute("SELECT COUNT(*) FROM users WHERE status='approved'").fetchone()[0]
        impact['en_attente'] = db.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0]
        impact['annonces'] = db.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        impact['annonces_terminees'] = db.execute("SELECT COUNT(*) FROM listings WHERE status='termine'").fetchone()[0]
        impact['par_type'] = db.execute("SELECT kind, COUNT(*) FROM listings GROUP BY kind").fetchall()
        impact['conversations'] = db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        impact['messages'] = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        impact['billets'] = db.execute("SELECT COUNT(*) FROM journal_posts").fetchone()[0]
        impact['avis'] = db.execute("SELECT COUNT(*), AVG(score) FROM ratings").fetchone()
        impact['signalements'] = db.execute("SELECT COUNT(*) FROM reports WHERE status='open'").fetchone()[0]
    except sqlite3.OperationalError:
        pass
    return render_template('admin/impact.html', impact=impact)

# --- MODERATION (V2.5 : signalements, masquer/supprimer) ---
from hinga.auth import staff_required  # noqa: E402
from hinga.utils import notify_admins  # noqa: E402


@bp.route('/admin/moderation')
@login_required
@staff_required
def admin_moderation():
    db = get_db()
    try:
        reports = db.execute("""SELECT r.*, u1.username AS reporter, u2.username AS listing_owner,
                                l.title AS listing_title, l.status AS listing_status,
                                substr(j.text, 1, 120) AS journal_text
                                FROM reports r
                                LEFT JOIN users u1 ON r.reporter_id = u1.id
                                LEFT JOIN listings l ON r.target_kind='listing' AND r.target_id = l.id
                                LEFT JOIN users u2 ON l.user_id = u2.id
                                LEFT JOIN journal_posts j ON r.target_kind='journal' AND r.target_id = j.id
                                WHERE r.status='open' ORDER BY r.id DESC""").fetchall()
    except sqlite3.OperationalError:
        reports = []
    return render_template('admin/moderation.html', reports=reports)


@bp.route('/admin/signalements/<int:report_id>/clore', methods=['POST'])
@login_required
@staff_required
def admin_report_close(report_id):
    db = get_db()
    db.execute("UPDATE reports SET status='closed' WHERE id=?", (report_id,))
    db.commit()
    audit('report_close', 'report', report_id, 'signalement classé sans suite')
    flash('Signalement classé.')
    return redirect(url_for('admin.admin_moderation'))


@bp.route('/admin/signalements/<int:report_id>/masquer', methods=['POST'])
@login_required
@staff_required
def admin_report_hide(report_id):
    db = get_db()
    rep = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if rep is None:
        return redirect(url_for('admin.admin_moderation'))
    if rep['target_kind'] == 'listing':
        db.execute("UPDATE listings SET status='masquee' WHERE id=?", (rep['target_id'],))
        owner = db.execute('SELECT user_id FROM listings WHERE id=?', (rep['target_id'],)).fetchone()
        if owner:
            from hinga.utils import notify
            notify(owner['user_id'], 'modération',
                   'Votre annonce a été masquée par la modération.', f"/echanges/{rep['target_id']}")
    db.execute("UPDATE reports SET status='closed' WHERE id=?", (report_id,))
    db.commit()
    audit('listing_hide', rep['target_kind'], rep['target_id'], f"masqué suite signalement #{report_id}")
    flash('Contenu masqué.')
    return redirect(url_for('admin.admin_moderation'))


@bp.route('/admin/annonces/<int:listing_id>/demasquer', methods=['POST'])
@login_required
@staff_required
def admin_listing_unhide(listing_id):
    db = get_db()
    db.execute("UPDATE listings SET status='disponible' WHERE id=?", (listing_id,))
    db.commit()
    audit('listing_unhide', 'listing', listing_id, 'annonce démasquée')
    flash('Annonce de nouveau visible.')
    return redirect(url_for('admin.admin_moderation'))


@bp.route('/admin/annonces/<int:listing_id>/supprimer')
@login_required
def admin_listing_delete(listing_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    target = db.execute('SELECT title FROM listings WHERE id=?', (listing_id,)).fetchone()
    for (fn,) in db.execute('SELECT filename FROM listing_photos WHERE listing_id=?', (listing_id,)).fetchall():
        _delete_managed_image(fn)
    db.execute('DELETE FROM listing_photos WHERE listing_id=?', (listing_id,))
    db.execute('DELETE FROM listings WHERE id=?', (listing_id,))
    db.execute("UPDATE reports SET status='closed' WHERE target_kind='listing' AND target_id=?", (listing_id,))
    db.commit()
    audit('listing_delete', 'listing', listing_id,
          f"annonce {target['title'] if target else listing_id} supprimée (modération)")
    flash('Annonce supprimée.')
    return redirect(url_for('admin.admin_moderation'))

# --- ANNONCES D'ACCUEIL (admin) ---
@bp.route('/admin/annonces', methods=['GET', 'POST'])
@login_required
def admin_announcements():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    if request.method == 'POST':
        from datetime import datetime
        title = request.form.get('title', '').strip()[:120]
        body = request.form.get('body', '').strip()[:1000]
        if title:
            today = datetime.now().strftime('%Y-%m-%d')
            cur = db.execute("INSERT INTO site_announcements (title, body, active, created_at, updated_at) "
                             "VALUES (?,?,1,?,?)", (title, body, today, today))
            db.commit()
            audit('annonce_create', 'announcement', cur.lastrowid, f"annonce accueil {title}")
            flash('Annonce publiée sur l’accueil.')
        return redirect(url_for('admin.admin_announcements'))
    try:
        items = db.execute('SELECT * FROM site_announcements ORDER BY id DESC').fetchall()
    except sqlite3.OperationalError:
        items = []
    return render_template('admin/announcements.html', items=items)


@bp.route('/admin/annonces/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_announcement_edit(item_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    item = db.execute('SELECT * FROM site_announcements WHERE id=?', (item_id,)).fetchone()
    if item is None:
        return redirect(url_for('admin.admin_announcements'))
    if request.method == 'POST':
        from datetime import datetime
        title = request.form.get('title', '').strip()[:120]
        body = request.form.get('body', '').strip()[:1000]
        if title:
            db.execute("UPDATE site_announcements SET title=?, body=?, updated_at=? WHERE id=?",
                       (title, body, datetime.now().strftime('%Y-%m-%d'), item_id))
            db.commit()
            audit('annonce_edit', 'announcement', item_id, f"annonce {title} modifiée")
            flash('Annonce mise à jour.')
        return redirect(url_for('admin.admin_announcements'))
    return render_template('admin/announcement_form.html', item=item)


@bp.route('/admin/annonces/<int:item_id>/toggle', methods=['POST'])
@login_required
def admin_announcement_toggle(item_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    db.execute("UPDATE site_announcements SET active = 1 - active WHERE id=?", (item_id,))
    db.commit()
    audit('annonce_toggle', 'announcement', item_id, 'affichage basculé')
    return redirect(url_for('admin.admin_announcements'))


@bp.route('/admin/annonces/<int:item_id>/retirer')
@login_required
def admin_announcement_delete(item_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    db.execute('DELETE FROM site_announcements WHERE id=?', (item_id,))
    db.commit()
    audit('annonce_delete', 'announcement', item_id, 'annonce accueil supprimée')
    flash('Annonce supprimée.')
    return redirect(url_for('admin.admin_announcements'))

# --- VISITES : HUMAINS / ROBOTS / INTRUSIONS (V2, module hinga.visits) ---
from hinga import visits as _visits  # noqa: E402


@bp.route('/admin/visites')
@login_required
def admin_visits():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    from datetime import date as _date
    db = get_db()
    log_path = current_app.config.get('NGINX_ACCESS_LOG', '')
    entries, missing = _load_visit_entries(db, log_path)
    if entries is None:
        return render_template('admin/visits.html', missing=missing, stats=None)
    filt = _filter_period(entries)
    entries, periode, ref_label, du, au = filt['entries'], filt['periode'], filt['label'], filt['du'], filt['au']
    exclure = request.args.get('exclure', '1') == '1'
    excluded = _visits.excluded_ips(db)
    n_excluded = 0
    if exclure and excluded:
        kept = []
        for e in entries:
            if _visits.is_excluded(e['ip'], excluded):
                n_excluded += 1
            else:
                kept.append(e)
        entries = kept
    ip_info = _enrich_ips(db, {e['ip'] for e in entries})
    for e in entries:
        info = ip_info.get(e['ip'], {})
        e['cat'] = info.get('categorie', 'inconnu')
        e['label'] = info.get('label', e['ip'])
        if e['cat'] in _visits.ROBOT_CATS:
            e['bot'] = True
    stats = _visit_stats(entries, ip_info)
    inspect_ip = request.args.get('ip', '').strip()[:45]
    inspect = None
    if inspect_ip:
        hits = [_enrich_hit(e, ip_info) for e in entries if e['ip'] == inspect_ip][-40:][::-1]
        s = stats['by_ip'].get(inspect_ip, {'n': 0, 'bad': 0, 'bot': False})
        info = ip_info.get(inspect_ip, {})
        inspect = dict(ip=inspect_ip, n=s['n'], bad=s['bad'], bot=s['bot'], hits=hits,
                       label=info.get('label', inspect_ip), cat=info.get('categorie', 'inconnu'))
    import json as _json
    stats.update(log_path=log_path, periode=periode, du=du, au=au, ref_day=ref_label,
                 exclure=1 if exclure else 0, n_excluded=n_excluded,
                 trend_labels=_json.dumps(stats['trend_labels']),
                 trend_values=_json.dumps(stats['trend_values']),
                 daily_labels=_json.dumps(stats['daily_labels']),
                 daily_values=_json.dumps(stats['daily_values']),
                 inspect=inspect)
    return render_template('admin/visits.html', missing=None, stats=stats)


def _load_visit_entries(db, log_path):
    try:
        with open(log_path, 'r', errors='replace') as fh:
            lines = fh.readlines()[-current_app.config.get('VISIT_MAX_LINES', 5000):]
    except OSError:
        return None, log_path
    entries = []
    for line in lines:
        m = _visits.COMBINED_RE.match(line)
        if not m:
            continue
        d = m.groupdict()
        ua = d['ua'] or ''
        try:
            status = int(d['status'])
        except ValueError:
            status = 0
        entries.append(dict(ip=d['ip'], time=d['time'], method=d['method'], path=d['path'][:160],
                            status=status, ua=ua[:160], ref=(d.get('ref') or '')[:200],
                            bot=bool(_visits.BOT_RE.search(ua)),
                            probe=bool(_visits.PROBE_RE.search(d['path'])),
                            attack=bool(_visits.ATTACK_RE.search(d['path'])),
                            bad=status in (400, 403, 404)))
    return entries, ''


def _filter_period(entries):
    from datetime import datetime as _dt, timedelta
    du = request.args.get('du', '').strip()[:10]
    au = request.args.get('au', '').strip()[:10]
    dated = [(e, _visits._log_day(e['time'])) for e in entries]
    ref_day = max((d for _, d in dated if d), default=None)
    if du or au:
        try:
            d1 = _dt.strptime(du, '%Y-%m-%d').date() if du else None
            d2 = _dt.strptime(au, '%Y-%m-%d').date() if au else None
        except ValueError:
            d1, d2 = None, None
        if d1 and d2 and d2 < d1:
            d1, d2 = d2, d1
        kept = [e for e, d in dated if d and (not d1 or d >= d1) and (not d2 or d <= d2)]
        label = f"du {d1.strftime('%d/%m/%Y') if d1 else '…'} au {d2.strftime('%d/%m/%Y') if d2 else '…'}"
        return dict(entries=kept, periode='custom', label=label,
                    du=d1.strftime('%Y-%m-%d') if d1 else '', au=d2.strftime('%Y-%m-%d') if d2 else '')
    try:
        days = int(request.args.get('periode', '7'))
    except (TypeError, ValueError):
        days = 7
    if days not in (1, 7, 30):
        days = 7
    if ref_day:
        kept = [e for e, d in dated if d and d >= ref_day - timedelta(days=days - 1)]
        label = ref_day.strftime('%d/%m/%Y')
    else:
        kept, label = [], '—'
    return dict(entries=kept, periode=days, label=label, du='', au='')


def _enrich_ips(db, ips):
    info = {}
    vps_ip = current_app.config.get('VPS_IP', '')
    budget = [25]
    for ip in ips:
        label, cat, src, host = _visits.resolve_ip(ip, db, vps_ip, budget[0])
        if host:
            budget[0] = max(0, budget[0] - 1)
        flag, country, iso = _visits.geo_lookup(ip)
        info[ip] = dict(label=label, categorie=cat, source=src, host=host,
                        flag=flag, country=country, iso=iso)
    return info


def _enrich_hit(e, ip_info):
    from datetime import datetime as _dt, timezone as _tz
    try:
        dt = _dt.strptime(e['time'].split()[0], '%d/%b/%Y:%H:%M:%S').replace(tzinfo=_tz.utc)
        when = _visits._brussels(dt).strftime('%d/%m %H:%M')
    except (ValueError, IndexError):
        when = e['time']
    code, badge, phrase = _visits.status_info(e['status'])
    browser, os_name, device = _visits.parse_ua(e['ua'])
    info = ip_info.get(e['ip'], {})
    if e['bot']:
        reason = 'User-Agent de bot'
    elif info.get('categorie') in _visits.ROBOT_CATS:
        reason = f"IP {info.get('categorie')} ({info.get('label')})"
    elif e['probe'] or e['attack']:
        reason = 'comportement suspect'
    else:
        reason = 'comportement humain'
    return dict(e, when=when,
                action='Consultation' if e['method'] == 'GET' else
                       ('Envoi de formulaire' if e['method'] == 'POST' else e['method']),
                page=_visits.page_name(e['path']), code=code, badge=badge, phrase=phrase,
                browser=browser, os_name=os_name, device=device,
                referer=_visits.ref_label(e['ref']), reason=reason)


def _visit_stats(entries, ip_info):
    from datetime import timedelta
    humans = [e for e in entries if not e['bot']]
    bots = [e for e in entries if e['bot']]
    by_ip = {}
    for e in entries:
        s = by_ip.setdefault(e['ip'], {'n': 0, 'bad': 0, 'bot': False, 'probe': False, 'attack': False})
        s['n'] += 1
        s['bad'] += 1 if e['bad'] else 0
        s['bot'] = s['bot'] or e['bot']
        s['probe'] = s['probe'] or e['probe']
        s['attack'] = s['attack'] or e['attack']
    suspicious = []
    for ip, s in by_ip.items():
        reasons = []
        if s['attack']:
            reasons.append('attaque (injection/traversée)')
        if s['probe']:
            reasons.append('sonde (fichiers sensibles)')
        if s['bad'] >= 10:
            reasons.append(f"{s['bad']} erreurs 4xx")
        if not s['bot'] and s['n'] >= 200:
            reasons.append(f"{s['n']} requêtes (rafale ?)")
        if reasons:
            suspicious.append(dict(ip=ip, n=s['n'], bad=s['bad'], bot=s['bot'], reasons=reasons))
    suspicious.sort(key=lambda x: -x['bad'])
    pages = {}
    for e in humans:
        p = e['path'].split('?')[0]
        if p.startswith('/static/') or _visits.RES_RE.search(p):
            continue
        if p == '/':
            p = '/ (Accueil)'
        pages[p] = pages.get(p, 0) + 1
    sources = {}
    for e in humans:
        s = _visits.ref_label(e['ref'])
        sources[s] = sources.get(s, 0) + 1
    mobile = sum(1 for e in humans if _visits.MOB_RE.search(e['ua']))
    devices = dict(mobile=mobile, desktop=len(humans) - mobile)
    per_hour = [0] * 24
    for e in humans:
        try:
            h = int(e['time'].split(':')[1])
            if 0 <= h <= 23:
                per_hour[h] += 1
        except (ValueError, IndexError):
            continue
    by_day = {}
    for e in humans:
        d = _visits._log_day(e['time'])
        if d:
            by_day[d.strftime('%d/%m')] = by_day.get(d.strftime('%d/%m'), 0) + 1
    top_ips = []
    for ip, s in sorted(by_ip.items(), key=lambda x: -x[1]['n'])[:15]:
        info = ip_info.get(ip, {})
        top_ips.append(dict(ip=ip, n=s['n'], bot=s['bot'], label=info.get('label', ip),
                            flag=info.get('flag', '🌍'), country=info.get('country', 'Inconnu')))
    countries = {}
    for e in humans:
        c = ip_info.get(e['ip'], {}).get('country', 'Inconnu')
        countries[c] = countries.get(c, 0) + 1
    return dict(total=len(entries), humans=len(humans), bots=len(bots),
                unique=len({_visits.ua_hash(e['ua']) + e['ip'] for e in humans}),
                ips=len(by_ip), suspicious=suspicious[:50],
                top_pages=sorted(pages.items(), key=lambda x: -x[1])[:15],
                sources=sorted(sources.items(), key=lambda x: -x[1])[:10],
                devices=devices, top_ips=top_ips, by_ip=by_ip,
                countries=sorted(countries.items(), key=lambda x: -x[1])[:10],
                recent=[_enrich_hit(e, ip_info) for e in entries if e['probe'] or e['attack']][-30:][::-1],
                trend_labels=[f"{h:02d}h" for h in range(24)], trend_values=per_hour,
                daily_labels=list(by_day.keys()), daily_values=list(by_day.values()))


@bp.route('/admin/visites/visiteurs')
@login_required
def admin_visitors():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    log_path = current_app.config.get('NGINX_ACCESS_LOG', '')
    entries, missing = _load_visit_entries(db, log_path)
    if entries is None:
        return render_template('admin/visitors.html', missing=missing, data=None)
    filt = _filter_period(entries)
    entries = filt['entries']
    if request.args.get('exclure', '1') == '1':
        excluded = _visits.excluded_ips(db)
        if excluded:
            entries = [e for e in entries if not _visits.is_excluded(e['ip'], excluded)]
    ip_info = _enrich_ips(db, {e['ip'] for e in entries})
    for e in entries:
        e['cat'] = ip_info.get(e['ip'], {}).get('categorie', 'inconnu')
        if e['cat'] in _visits.ROBOT_CATS:
            e['bot'] = True
    vtype = request.args.get('type', 'total')
    if vtype == 'humains':
        entries = [e for e in entries if not e['bot']]
    elif vtype == 'robots':
        entries = [e for e in entries if e['bot']]
    groups = {}
    for e in entries:
        key = e['ip'] + '|' + _visits.ua_hash(e['ua'])
        g = groups.setdefault(key, {'ip': e['ip'], 'uah': _visits.ua_hash(e['ua']), 'n': 0,
                                    'pages': 0, 'first': e['time'], 'last': e['time'],
                                    'browser': '', 'os': '', 'device': '', 'ref': '', 'tops': {}})
        g['n'] += 1
        if e['time'] < g['first']:
            g['first'] = e['time']
        if e['time'] > g['last']:
            g['last'] = e['time']
        p = e['path'].split('?')[0]
        if e['method'] == 'GET' and e['status'] == 200 and not p.startswith('/static/') \
                and not _visits.RES_RE.search(p):
            g['pages'] += 1
        g['tops'][_visits.page_name(e['path'])] = g['tops'].get(_visits.page_name(e['path']), 0) + 1
        if not g['ref'] and e['ref'] not in ('', '-'):
            g['ref'] = e['ref']
    visitors = []
    for key, g in groups.items():
        browser, os_name, device = _visits.parse_ua(next(
            (e['ua'] for e in entries if e['ip'] == g['ip']), ''))
        info = ip_info.get(g['ip'], {})
        visitors.append(dict(g, label=info.get('label', g['ip']),
                             cat=info.get('categorie', 'inconnu'),
                             flag=info.get('flag', '🌍'), country=info.get('country', 'Inconnu'),
                             browser=browser, os_name=os_name, device=device,
                             bot=any(e['bot'] for e in entries if e['ip'] == g['ip']),
                             top3=sorted(g['tops'].items(), key=lambda x: -x[1])[:3]))
    q = request.args.get('q', '').strip().lower()[:60]
    if q:
        visitors = [v for v in visitors
                    if q in v['ip'].lower() or q in (v['label'] or '').lower()
                    or q in (v['country'] or '').lower()]
    tri = request.args.get('tri', 'requetes')
    visitors.sort(key=lambda v: (v['n'] if tri == 'requetes'
                                 else v['last'] if tri == 'derniere' else v['first']),
                  reverse=(tri != 'premiere'))
    if request.args.get('export') == 'csv':
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        w = _csv.writer(buf, delimiter=';')
        w.writerow(['ip', 'label', 'categorie', 'pays', 'navigateur', 'appareil',
                    'premiere_visite', 'derniere_visite', 'pages_vues', 'requetes', 'referer'])
        for v in visitors[:5000]:
            w.writerow([v['ip'], v['label'], v['cat'], v['country'], v['browser'], v['device'],
                        v['first'], v['last'], v['pages'], v['n'], v['ref']])
        resp = current_app.response_class(buf.getvalue(), mimetype='text/csv; charset=utf-8')
        resp.headers['Content-Disposition'] = 'attachment; filename=visiteurs.csv'
        return resp
    try:
        page = max(1, int(request.args.get('page', '1')))
    except (TypeError, ValueError):
        page = 1
    per_page = 20
    total_pages = max(1, (len(visitors) + per_page - 1) // per_page)
    page = min(page, total_pages)
    detail = None
    vkey = request.args.get('visiteur', '')
    if vkey:
        match = next((v for v in visitors if v['ip'] + '|' + v['uah'] == vkey), None)
        if match:
            hits = [_enrich_hit(e, ip_info) for e in entries
                    if e['ip'] == match['ip'] and _visits.ua_hash(e['ua']) == match['uah']]
            detail = dict(visitor=match, hits=hits[::-1][:200])
    return render_template('admin/visitors.html', missing=None,
                           data=dict(visitors=visitors[(page - 1) * per_page:page * per_page],
                                     total=len(visitors), page=page, total_pages=total_pages,
                                     type=vtype, q=request.args.get('q', ''), tri=tri,
                                     periode=request.args.get('periode', '7'),
                                     du=request.args.get('du', ''), au=request.args.get('au', ''),
                                     detail=detail))


@bp.route('/admin/visites/ip', methods=['POST'])
@login_required
def admin_ip_rename():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    from datetime import datetime as _dt
    db = get_db()
    ip = request.form.get('ip', '').strip()[:80]
    if not ip:
        return redirect(url_for('admin.admin_visits'))
    if request.form.get('supprimer'):
        db.execute('DELETE FROM known_ips WHERE cidr=?', (ip,))
        db.commit()
        flash('Label supprimé (retour à la détection auto).')
        return redirect(url_for('admin.admin_visits', ip=ip))
    label = request.form.get('label', '').strip()[:80] or ip
    cat = request.form.get('categorie', 'inconnu')
    if cat not in _visits.CATEGORIES:
        cat = 'inconnu'
    note = request.form.get('note', '').strip()[:300]
    exclude = 1 if request.form.get('exclude') else 0
    row = db.execute('SELECT id FROM known_ips WHERE cidr=?', (ip,)).fetchone()
    if row:
        db.execute("UPDATE known_ips SET label=?, categorie=?, note=?, exclude=?, updated_at=? WHERE id=?",
                   (label, cat, note, exclude, _dt.now().strftime('%Y-%m-%d'), row['id']))
    else:
        db.execute("INSERT INTO known_ips (cidr, label, categorie, note, exclude, updated_at) "
                   "VALUES (?,?,?,?,?,?)",
                   (ip, label, cat, note, exclude, _dt.now().strftime('%Y-%m-%d')))
    db.commit()
    flash(f"IP {ip} nommée « {label} ».")
    return redirect(url_for('admin.admin_visits', ip=ip))
