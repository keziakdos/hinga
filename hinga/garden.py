"""Blueprint garden : accueil, calendrier, récoltes, stats, Ma Plante (V1 constant)."""
import json
import os
import sqlite3
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from hinga.auth import login_required
from hinga.db import get_db
from hinga.helpers import (MOIS_FR, MOIS_FR_ABBR, mois_nom, month_in_range,
                           periode_label, plants_for_month, unique_filename)
from hinga.services.images import thumb_name  # noqa: F401 (re-export compat)
from hinga.services.plant_analysis import analyze_image, downscaled_copy, is_analysis_enabled
from hinga.utils import _delete_managed_image, _tip_thumb, allowed_file  # noqa: F401

bp = Blueprint('garden', __name__)

# --- ROUTES PUBLIQUES (Accueil, Calendrier, Fiche Plante, Conseils) ---
@bp.route('/')
def index():
    db = get_db()
    plants = db.execute('SELECT * FROM plants ORDER BY name').fetchall()
    now_m = datetime.now().month
    next_m = now_m % 12 + 1
    semer_mtn, recolter_mtn = plants_for_month(plants, now_m)
    # Bientôt : fenêtre qui s'ouvre le mois prochain (hors fenêtre actuelle)
    semer_bientot = [p for p in plants
                     if int(p['sow_start']) == next_m
                     and not month_in_range(now_m, p['sow_start'], p['sow_end'])]
    recolter_bientot = [p for p in plants
                        if int(p['harvest_start']) == next_m
                        and not month_in_range(now_m, p['harvest_start'], p['harvest_end'])]
    return render_template('home.html', plants=plants,
                           mois_actuel=MOIS_FR[now_m - 1], mois_suivant=MOIS_FR[next_m - 1],
                           semer_mtn=semer_mtn, recolter_mtn=recolter_mtn,
                           semer_bientot=semer_bientot, recolter_bientot=recolter_bientot)

@bp.route('/calendar')
def calendar():
    # Accessible à tous (lecture seule)
    db = get_db()
    plants = db.execute('SELECT * FROM plants ORDER BY name').fetchall()
    months = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']
    # Mois sélectionné (?mois=1..12) : deux listes semer / récolter
    try:
        selected_month = int(request.args.get('mois', 0))
    except (TypeError, ValueError):
        selected_month = 0
    if not 1 <= selected_month <= 12:
        selected_month = 0
    a_semis, a_recolter = ([], [])
    if selected_month:
        a_semis, a_recolter = plants_for_month(plants, selected_month)
    return render_template('calendar.html', plants=plants, months=months,
                           selected_month=selected_month,
                           a_semis=a_semis, a_recolter=a_recolter)

@bp.route('/plant/<int:plant_id>')
def plant_details(plant_id):
    db = get_db()
    plant = db.execute('SELECT * FROM plants WHERE id = ?', (plant_id,)).fetchone()
    return render_template('plant.html', plant=plant)

@bp.route('/tips')
def tips():
    db = get_db()
    try:
        rows = db.execute('''SELECT t.*, c.name as category_name FROM tips t
                             LEFT JOIN tip_categories c ON t.category_id = c.id''').fetchall()
    except sqlite3.OperationalError:
        rows = db.execute('SELECT *, NULL as category_name FROM tips').fetchall()
    tips_list = [dict(t, thumb=_tip_thumb(t['image'])) for t in rows]
    return render_template('tips.html', tips=tips_list)

@bp.route('/tip/<int:tip_id>')
def tip_details(tip_id):
    db = get_db()
    try:
        row = db.execute('''SELECT t.*, c.name as category_name FROM tips t
                            LEFT JOIN tip_categories c ON t.category_id = c.id
                            WHERE t.id = ?''', (tip_id,)).fetchone()
    except sqlite3.OperationalError:
        row = db.execute('SELECT *, NULL as category_name FROM tips WHERE id = ?', (tip_id,)).fetchone()
    if not row: return "Conseil introuvable", 404
    tip = dict(row)
    tip['thumb'] = _tip_thumb(tip['image'])
    return render_template('tip_detail.html', tip=tip)

# --- PWA / HORS-LIGNE (V2.6) ---
@bp.route('/sw.js')
def service_worker():
    return current_app.send_static_file('js/sw.js')


@bp.route('/hors-ligne')
def offline():
    return render_template('offline.html')


# --- ROUTES PRIVÉES (Récoltes, Stats, Ma Plante) ---

@bp.route('/harvests', methods=['GET', 'POST'])
@login_required
def harvests():
    db = get_db()
    user_id = session['user_id']
    
    if request.method == 'POST':
        plant_id = request.form['plant_id']
        date = request.form['date']
        try:
            quantity = float(request.form['quantity'])
            if quantity <= 0:
                raise ValueError
        except (ValueError, TypeError):
            flash('Quantité invalide (nombre positif attendu).')
            return redirect(url_for('garden.harvests'))
        notes = request.form['notes']
        
        db.execute('INSERT INTO harvests (user_id, plant_id, date, quantity, notes) VALUES (?,?,?,?,?)',
                   (user_id, plant_id, date, quantity, notes))
        db.commit()
        flash('✅ Récolte ajoutée !')
        return redirect(url_for('garden.harvests'))

    # Seules les récoltes de l'utilisateur connecté (avec photo de la plante)
    harvests_list = db.execute('''SELECT h.*, p.name as plant_name, p.image as plant_image
                                  FROM harvests h JOIN plants p ON h.plant_id = p.id
                                  WHERE h.user_id = ? ORDER BY h.date DESC''', (user_id,)).fetchall()
    plants = db.execute('SELECT id, name FROM plants ORDER BY name').fetchall()
    return render_template('harvests.html', harvests=harvests_list, plants=plants, today=datetime.today().strftime('%Y-%m-%d'))

@bp.route('/stats')
@login_required
def stats():
    db = get_db()
    user_id = session['user_id']
    
    # Stats filtrées par user_id
    total_weight = db.execute('SELECT SUM(quantity) FROM harvests WHERE user_id = ?', (user_id,)).fetchone()[0] or 0
    
    rows_plants = db.execute('''
        SELECT p.id, p.name, SUM(h.quantity) FROM harvests h 
        JOIN plants p ON h.plant_id = p.id 
        WHERE h.user_id = ? GROUP BY p.id ORDER BY SUM(h.quantity) DESC
    ''', (user_id,)).fetchall()
    
    plant_ids = [row[0] for row in rows_plants]
    plant_labels = [row[1] for row in rows_plants]
    plant_data = [row[2] for row in rows_plants]

    # --- Filtres production : année / grain (mois-semaine) / plante ---
    year_rows = db.execute("SELECT DISTINCT strftime('%Y', date) FROM harvests WHERE user_id = ? AND date IS NOT NULL",
                           (user_id,)).fetchall()
    cur_year = str(datetime.now().year)
    years = sorted({r[0] for r in year_rows if r[0]} | {cur_year}, reverse=True)
    sel_year = request.args.get('annee', cur_year)
    if sel_year not in years:
        sel_year = cur_year
    grain = 'semaine' if request.args.get('grain') == 'semaine' else 'mois'
    try:
        plant_filter = int(request.args.get('plante', 0))
    except (TypeError, ValueError):
        plant_filter = 0

    filt_query = "SELECT date, quantity FROM harvests WHERE user_id = ? AND strftime('%Y', date) = ?"
    filt_params = [user_id, sel_year]
    if plant_filter:
        filt_query += " AND plant_id = ?"
        filt_params.append(plant_filter)
    entries = db.execute(filt_query, filt_params).fetchall()

    if grain == 'semaine':
        prod_labels = [f"S{w}" for w in range(1, 54)]
        prod_values = [0] * 53
        for e in entries:
            try:
                d = datetime.strptime(e['date'][:10], '%Y-%m-%d')
                if d.strftime('%Y') == sel_year:
                    prod_values[d.isocalendar()[1] - 1] += e['quantity'] or 0
            except (ValueError, TypeError):
                continue
        prod_values = [round(v, 2) for v in prod_values]
        prod_title = "Production par Semaine"
    else:
        prod_labels = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']
        prod_values = [0] * 12
        for e in entries:
            try:
                m = int(e['date'][5:7])
                if 1 <= m <= 12:
                    prod_values[m - 1] += e['quantity'] or 0
            except (ValueError, TypeError, IndexError):
                continue
        prod_values = [round(v, 2) for v in prod_values]
        prod_title = "Production par Mois"

    user_plants = db.execute('''SELECT DISTINCT p.id, p.name FROM harvests h
                                JOIN plants p ON h.plant_id = p.id
                                WHERE h.user_id = ? ORDER BY p.name''', (user_id,)).fetchall()

    monthly_map = {f"{i:02d}": 0 for i in range(1, 13)}
    rows_months = db.execute("SELECT strftime('%m', date) as m, SUM(quantity) FROM harvests WHERE user_id = ? GROUP BY m", (user_id,)).fetchall()
    for row in rows_months:
        if row[0] in monthly_map: monthly_map[row[0]] = row[1]
            
    month_labels_fr = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']
    month_values = list(monthly_map.values())

    # Comptage par plante (nb de récoltes + kg) + fenêtres semis/récolte
    rows_counts = db.execute('''SELECT p.name, COUNT(*), SUM(h.quantity),
        p.sow_start, p.sow_end, p.harvest_start, p.harvest_end, p.id
        FROM harvests h JOIN plants p ON h.plant_id = p.id
        WHERE h.user_id = ? GROUP BY p.id ORDER BY SUM(h.quantity) DESC''', (user_id,)).fetchall()
    per_plant = [dict(name=r[0], count=r[1], qty=round(r[2] or 0, 2),
                      sow=periode_label(r[3], r[4]), harvest=periode_label(r[5], r[6]),
                      plant_id=r[7]) for r in rows_counts]
    total_entries = sum(r['count'] for r in per_plant)
    distinct_plants = len(per_plant)
    avg_entry = round(total_weight / total_entries, 2) if total_entries else 0

    # Semis par mois (calendrier global : nb de plantes à semer chaque mois)
    all_plants = db.execute('SELECT sow_start, sow_end FROM plants').fetchall()
    sow_per_month = [sum(1 for p in all_plants if month_in_range(m, p['sow_start'], p['sow_end']))
                     for m in range(1, 13)]
    top_sow_month = MOIS_FR[max(range(12), key=lambda i: sow_per_month[i])] if any(sow_per_month) else '—'

    # Meilleur mois de production (kg récoltés)
    best_prod_month = MOIS_FR[month_values.index(max(month_values))] if total_weight > 0 else '—'

    # Estimation des récoltes à venir (plantes déjà cultivées par l'utilisateur)
    now_m = datetime.now().month
    upcoming = []
    for r in rows_counts:
        hs, he = r[5], r[6]
        current = month_in_range(now_m, hs, he)
        if current:
            status = 'En récolte actuellement'
        else:
            nxt = next((k for k in range(1, 13)
                        if month_in_range(((now_m - 1 + k) % 12) + 1, hs, he)), None)
            status = f"Dès {mois_nom(((now_m - 1 + nxt) % 12) + 1)}" if nxt else '—'
        upcoming.append(dict(name=r[0], window=periode_label(hs, he),
                             status=status, current=current))

    return render_template('stats.html', total_weight=round(total_weight, 2),
                           plant_labels=json.dumps(plant_labels), plant_data=json.dumps(plant_data),
                           plant_ids=json.dumps(plant_ids),
                           month_labels=json.dumps(month_labels_fr), month_values=json.dumps(month_values),
                           per_plant=per_plant, total_entries=total_entries,
                           distinct_plants=distinct_plants, avg_entry=avg_entry,
                           sow_per_month=json.dumps(sow_per_month), top_sow_month=top_sow_month,
                           best_prod_month=best_prod_month, upcoming=upcoming,
                           current_month_name=MOIS_FR[now_m - 1],
                           years=years, sel_year=sel_year, grain=grain,
                           plant_filter=plant_filter, user_plants=user_plants,
                           prod_labels=json.dumps(prod_labels),
                           prod_values=json.dumps(prod_values), prod_title=prod_title)


@bp.route('/stats/plant/<int:plant_id>')
@login_required
def stats_plant(plant_id):
    """Historique d'une culture : ajouts + période la plus récoltée."""
    db = get_db()
    user_id = session['user_id']
    plant = db.execute('SELECT * FROM plants WHERE id = ?', (plant_id,)).fetchone()
    if plant is None:
        flash("Plante introuvable.")
        return redirect(url_for('garden.stats'))

    entries = db.execute('''SELECT date, quantity, notes FROM harvests
                            WHERE user_id = ? AND plant_id = ? ORDER BY date DESC''',
                         (user_id, plant_id)).fetchall()
    monthly = [0] * 12
    for e in entries:
        try:
            m = int((e['date'] or '')[5:7])
            if 1 <= m <= 12:
                monthly[m - 1] += e['quantity'] or 0
        except (ValueError, TypeError, IndexError):
            continue
    monthly = [round(v, 2) for v in monthly]
    total = round(sum(monthly), 2)
    count = len(entries)
    best_month = MOIS_FR[monthly.index(max(monthly))] if total > 0 else '—'

    return render_template('stats_plant.html', plant=plant, entries=entries,
                           monthly=json.dumps(monthly),
                           month_labels=json.dumps(['Jan', 'Fév', 'Mar', 'Avr', 'Mai',
                                                    'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']),
                           total=total, count=count,
                           avg=round(total / count, 2) if count else 0,
                           best_month=best_month)









@bp.route('/maplante', methods=['GET', 'POST'])
@login_required
def maplante():
    db = get_db()
    user_id = session['user_id']
    result = None
    
    if request.method == 'POST':
        if 'file' not in request.files: return redirect(request.url)
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename): return redirect(request.url)

        # Sauvegarde image (nom sûr et unique, extension d'origine)
        filename = unique_filename(file.filename)
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], 'img', filename)
        file.save(filepath)

        if not is_analysis_enabled():
            # V1 : service non branché -> photo enregistrée en "attente d'analyse"
            db.execute('''INSERT INTO monitored_plants
                          (user_id, plant_name, image_path, diagnosis_summary, full_json, date_added)
                          VALUES (?, ?, ?, ?, ?, ?)''',
                       (user_id, 'Analyse en attente', filename,
                        f"Photo enregistrée le {datetime.now().strftime('%Y-%m-%d')}, analyse automatique à configurer.",
                        '{}', datetime.now().strftime('%Y-%m-%d')))
            db.commit()
            flash("📸 Photo enregistrée. L'analyse automatique sera configurée à la fin du projet.")
            return redirect(url_for('garden.maplante'))

        try:
            # Envoi d'une copie réduite (rapide) ; l'original reste archivé.
            tmp_path = downscaled_copy(filepath)
            try:
                ai_json = analyze_image(tmp_path)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            result = {
                "image_filename": filename,
                "name": ai_json.get('name', 'Inconnue'),
                "confidence": ai_json.get('confidence', '?'),
                "strengths": ai_json.get('strengths', []),
                "weaknesses": ai_json.get('weaknesses', []),
                "advice": ai_json.get('advice', ''),
                "details": ai_json.get('details', {}) # Les nouvelles infos
            }
            flash('✅ Analyse approfondie terminée !')

        except Exception as e:
            msg = str(e)
            if 'timeout' in msg.lower() or 'deadline' in msg.lower():
                flash("⏳ L'analyse prend trop de temps. Réessayez (photo plus légère, ou dans un moment).")
            else:
                flash(f"Erreur IA : {msg}")
            print(e)

    # Récupérer l'historique
    monitored = db.execute('SELECT * FROM monitored_plants WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
            
    return render_template('maplante.html', result=result, monitored=monitored,
                           analysis_enabled=is_analysis_enabled())




@bp.route('/monitor_save', methods=['POST'])
@login_required
def monitor_save():
    db = get_db()
    # On récupère le gros JSON caché dans le formulaire
    full_data_str = request.form['full_data']
    full_data = json.loads(full_data_str) # On vérifie que c'est du JSON valide
    
    image_filename = full_data['image_filename']
    plant_name = full_data['name']
    summary = f"{full_data.get('details', {}).get('sun', '')} - {full_data['advice'][:50]}..."

    db.execute('''INSERT INTO monitored_plants (user_id, plant_name, image_path, diagnosis_summary, full_json, date_added) 
                  VALUES (?, ?, ?, ?, ?, ?)''',
               (session['user_id'], plant_name, image_filename, summary, full_data_str, datetime.now().strftime('%Y-%m-%d')))
    db.commit()
    flash('✅ Rapport complet sauvegardé !')
    return redirect(url_for('garden.maplante'))

@bp.route('/monitor/view/<int:id>')
@login_required
def monitor_view(id):
    db = get_db()
    # On récupère la plante seulement si elle appartient à l'utilisateur
    entry = db.execute('SELECT * FROM monitored_plants WHERE id = ? AND user_id = ?', (id, session['user_id'])).fetchone()
    
    if entry is None:
        flash("Ce rapport n'existe pas ou ne vous appartient pas.")
        return redirect(url_for('garden.maplante'))
    
    # On convertit le texte JSON stocké en objet Python utilisable
    import json
    try:
        data = json.loads(entry['full_json'])
    except:
        data = {} # Cas où l'ancien format n'a pas de JSON
        
    # On ajoute l'URL de l'image au dictionnaire pour l'affichage
    data['image_url'] = url_for('static', filename='img/' + entry['image_path'])
    
    return render_template('monitor_detail.html', result=data, entry_id=entry['id'])

@bp.route('/monitor/delete/<int:id>')
@login_required
def monitor_delete(id):
    db = get_db()
    db.execute('DELETE FROM monitored_plants WHERE id = ? AND user_id = ?', (id, session['user_id']))
    db.commit()
    flash('🗑️ Rapport supprimé.')
    return redirect(url_for('garden.maplante'))






