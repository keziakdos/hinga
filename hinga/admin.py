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
from hinga.utils import _delete_managed_image, _tip_thumb  # noqa: F401

bp = Blueprint('admin', __name__)

# --- SECTION ADMINISTRATION ---

@bp.route('/admin')
@login_required
def admin_dashboard():
    if session.get('role') != 'admin':
        flash('Accès réservé aux administrateurs.')
        return redirect(url_for('garden.index'))
    return render_template('admin/dashboard.html')

# --- GESTION UTILISATEURS ---
@bp.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    
    if request.method == 'POST':
        # Création d'un utilisateur
        username = request.form['username'].strip()
        password = request.form['password']
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        notes = request.form.get('notes', '').strip()
        # Vérif si existe déjà
        exist = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if exist:
            flash('Ce nom d\'utilisateur existe déjà.')
        else:
            pwd_hash = generate_password_hash(password)
            db.execute('''INSERT INTO users (username, password, role, first_name, last_name, email, notes, is_active)
                          VALUES (?, ?, 'user', ?, ?, ?, ?, 1)''',
                       (username, pwd_hash, first_name, last_name, email, notes))
            db.commit()
            flash(f'Utilisateur {username} créé !')
        return redirect(url_for('admin.admin_users'))
        
    users = db.execute('SELECT * FROM users').fetchall()
    return render_template('admin/users.html', users=users)

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
        notes = request.form.get('notes', '').strip()
        role = request.form.get('role', 'user')
        if role not in ('admin', 'user'):
            role = 'user'
        # Impossible de désactiver son propre compte ou de se rétrograder
        if user_id == session['user_id']:
            is_active = 1
            role = user['role']
        else:
            is_active = 1 if request.form.get('is_active') else 0
        db.execute('''UPDATE users SET first_name=?, last_name=?, email=?, notes=?, role=?, is_active=?
                      WHERE id=?''', (first_name, last_name, email, notes, role, is_active, user_id))
        new_password = request.form.get('new_password', '')
        if new_password:
            db.execute('UPDATE users SET password=? WHERE id=?',
                       (generate_password_hash(new_password), user_id))
        db.commit()
        flash('Utilisateur mis à jour.')
        return redirect(url_for('admin.admin_users'))

    return render_template('admin/user_form.html', user=user)

@bp.route('/admin/users/delete/<int:user_id>')
@login_required
def admin_delete_user(user_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    # On empêche de se supprimer soi-même
    if user_id == session['user_id']:
        flash('Impossible de supprimer votre propre compte ici.')
    else:
        db = get_db()
        db.execute('DELETE FROM users WHERE id = ?', (user_id,))
        db.commit()
        flash('Utilisateur supprimé.')
    return redirect(url_for('admin.admin_users'))

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
    db.execute('DELETE FROM plants WHERE id = ?', (plant_id,))
    db.commit()
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
    flash('Catégorie supprimée (les conseils sont conservés).')
    return redirect(url_for('admin.admin_tip_categories'))

@bp.route('/admin/tips/delete/<int:tip_id>')
@login_required
def admin_delete_tip(tip_id):
    if session.get('role') != 'admin': return redirect(url_for('garden.index'))
    db = get_db()
    db.execute('DELETE FROM tips WHERE id = ?', (tip_id,))
    db.commit()
    flash('Conseil supprimé.')
    return redirect(url_for('admin.admin_tips'))



