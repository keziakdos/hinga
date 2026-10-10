"""Blueprint social : profils, messagerie, notifications (V2.3)."""
import sqlite3
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from hinga.auth import login_required
from hinga.db import get_db
from hinga.services.images import save_tip_image
from hinga.utils import _tip_thumb, notify

bp = Blueprint('social', __name__)

MAX_NEW_CONV_DAY = 5
MAX_MSG_DAY = 50
MAX_BODY = 2000


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def _today():
    return datetime.now().strftime('%Y-%m-%d')


@bp.route('/membres/<username>')
def profile(username):
    db = get_db()
    try:
        user = db.execute("SELECT * FROM users WHERE username=? AND status='approved'",
                          (username,)).fetchone()
    except sqlite3.OperationalError:
        user = None
    if user is None:
        flash("Membre introuvable.")
        return redirect(url_for('garden.index'))
    active = db.execute("SELECT COUNT(*) FROM listings WHERE user_id=? AND status='disponible'",
                        (user['id'],)).fetchone()[0]
    done = db.execute("SELECT COUNT(*) FROM listings WHERE user_id=? AND status='termine'",
                      (user['id'],)).fetchone()[0]
    annonces = db.execute("""SELECT l.id, l.title, l.kind, l.status FROM listings l
                             WHERE l.user_id=? AND l.status IN ('disponible','reserve')
                             ORDER BY l.created_at DESC LIMIT 6""", (user['id'],)).fetchall()
    avatar = None
    try:
        if user['avatar']:
            avatar = _tip_thumb(user['avatar'])
    except (KeyError, IndexError):
        pass
    return render_template('social/profile.html', user=user, avatar=avatar,
                           active=active, done=done, annonces=annonces)


@bp.route('/mon-profil', methods=['GET', 'POST'])
@login_required
def my_profile():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if request.method == 'POST':
        zone = request.form.get('zone', '').strip()[:80]
        presentation = request.form.get('presentation', '').strip()[:500]
        jardin = request.form.get('jardin', '').strip()[:500]
        cherche = request.form.get('cherche', '').strip()[:300]
        offre = request.form.get('offre', '').strip()[:300]
        avatar = user['avatar']
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename:
                page, error = save_tip_image(file, current_app.config['UPLOAD_FOLDER'] + '/img')
                if error:
                    flash(error)
                    return redirect(url_for('social.my_profile'))
                avatar = page
        db.execute("""UPDATE users SET zone=?, presentation=?, jardin=?, cherche=?, offre=?, avatar=?
                      WHERE id=?""",
                   (zone, presentation, jardin, cherche, offre, avatar, session['user_id']))
        db.commit()
        flash('Profil mis à jour.')
        return redirect(url_for('social.profile', username=user['username']))
    return render_template('social/my_profile.html', user=user)


def _inbox(db, user_id):
    try:
        rows = db.execute("""SELECT c.*, u.username AS other_name,
                             (SELECT body FROM messages WHERE conversation_id=c.id ORDER BY id DESC LIMIT 1) AS last_body,
                             (SELECT COUNT(*) FROM messages WHERE conversation_id=c.id AND author_id!=? AND (read_at IS NULL OR read_at='')) AS unread
                             FROM conversations c
                             JOIN users u ON u.id = CASE WHEN c.user_a=? THEN c.user_b ELSE c.user_a END
                             WHERE c.user_a=? OR c.user_b=? ORDER BY c.updated_at DESC""",
                          (user_id, user_id, user_id, user_id)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


@bp.route('/messages')
@login_required
def inbox():
    return render_template('social/inbox.html', convs=_inbox(get_db(), session['user_id']))


@bp.route('/messages/nouveau', methods=['GET', 'POST'])
@login_required
def new_conversation():
    db = get_db()
    me = session['user_id']
    listing = None
    listing_id = request.values.get('annonce', '') or request.values.get('annonce_id', '')
    if listing_id.isdigit():
        listing = db.execute('SELECT l.id, l.title, l.user_id, u.username AS owner FROM listings l '
                             'JOIN users u ON l.user_id=u.id WHERE l.id=?', (int(listing_id),)).fetchone()
    if request.method == 'POST':
        to_name = request.form.get('vers', '').strip()
        body = request.form.get('message', '').strip()[:MAX_BODY]
        other = db.execute("SELECT id, username FROM users WHERE username=? AND status='approved'",
                           (to_name,)).fetchone()
        if other is None:
            flash('Destinataire introuvable.')
            return redirect(url_for('social.new_conversation'))
        if other['id'] == me:
            flash('Vous ne pouvez pas vous écrire à vous-même.')
            return redirect(url_for('social.new_conversation'))
        if not body:
            flash('Message vide.')
            return redirect(url_for('social.new_conversation'))
        today = _today()
        n = db.execute("SELECT COUNT(*) FROM conversations WHERE (user_a=? OR user_b=?) "
                       "AND substr(created_at,1,10)=?", (me, me, today)).fetchone()[0]
        if n >= MAX_NEW_CONV_DAY:
            flash(f'Limite anti-spam : {MAX_NEW_CONV_DAY} conversations par jour.')
            return redirect(url_for('social.inbox'))
        lid = listing['id'] if listing and request.form.get('annonce_id', '').isdigit() \
            and int(request.form.get('annonce_id')) == listing['id'] else None
        conv = None
        if lid:
            conv = db.execute("""SELECT id FROM conversations WHERE listing_id=?
                                 AND ((user_a=? AND user_b=?) OR (user_a=? AND user_b=?))""",
                              (lid, me, other['id'], other['id'], me)).fetchone()
        if conv is None:
            cur = db.execute("""INSERT INTO conversations (listing_id, user_a, user_b, created_at, updated_at)
                                VALUES (?,?,?,?,?)""", (lid, me, other['id'], _now(), _now()))
            conv_id = cur.lastrowid
        else:
            conv_id = conv['id']
        db.execute("INSERT INTO messages (conversation_id, author_id, body, created_at) VALUES (?,?,?,?)",
                   (conv_id, me, body, _now()))
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), conv_id))
        db.commit()
        notify(other['id'], 'message', f"Nouveau message de {session.get('username')}",
               f'/messages/{conv_id}')
        return redirect(url_for('social.thread', conv_id=conv_id))
    return render_template('social/new.html', listing=listing,
                           vers=request.values.get('vers', ''))


@bp.route('/messages/<int:conv_id>', methods=['GET', 'POST'])
@login_required
def thread(conv_id):
    db = get_db()
    me = session['user_id']
    conv = db.execute('SELECT * FROM conversations WHERE id=?', (conv_id,)).fetchone()
    if conv is None or me not in (conv['user_a'], conv['user_b']):
        flash("Conversation introuvable.")
        return redirect(url_for('social.inbox'))
    if request.method == 'POST':
        body = request.form.get('message', '').strip()[:MAX_BODY]
        if not body:
            flash('Message vide.')
        else:
            today = _today()
            n = db.execute("SELECT COUNT(*) FROM messages WHERE author_id=? AND substr(created_at,1,10)=?",
                           (me, today)).fetchone()[0]
            if n >= MAX_MSG_DAY:
                flash(f'Limite anti-spam : {MAX_MSG_DAY} messages par jour.')
            else:
                db.execute("INSERT INTO messages (conversation_id, author_id, body, created_at) "
                           "VALUES (?,?,?,?)", (conv_id, me, body, _now()))
                db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), conv_id))
                db.commit()
                other = conv['user_b'] if me == conv['user_a'] else conv['user_a']
                notify(other, 'message', f"Nouveau message de {session.get('username')}",
                       f'/messages/{conv_id}')
        return redirect(url_for('social.thread', conv_id=conv_id))
    db.execute("UPDATE messages SET read_at=? WHERE conversation_id=? AND author_id!=? "
               "AND (read_at IS NULL OR read_at='')", (_now(), conv_id, me))
    db.commit()
    msgs = db.execute("""SELECT m.*, u.username AS author FROM messages m
                         JOIN users u ON m.author_id=u.id
                         WHERE m.conversation_id=? ORDER BY m.id""", (conv_id,)).fetchall()
    other_id = conv['user_b'] if me == conv['user_a'] else conv['user_a']
    other = db.execute('SELECT username FROM users WHERE id=?', (other_id,)).fetchone()
    listing = None
    if conv['listing_id']:
        listing = db.execute('SELECT id, title FROM listings WHERE id=?', (conv['listing_id'],)).fetchone()
    return render_template('social/thread.html', conv=conv, messages=msgs,
                           other=other['username'] if other else '?', listing=listing)


@bp.route('/notifications')
@login_required
def notifications():
    db = get_db()
    try:
        notes = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50",
                           (session['user_id'],)).fetchall()
    except sqlite3.OperationalError:
        notes = []
    return render_template('social/notifications.html', notes=notes)


@bp.route('/notifications/lues', methods=['POST'])
@login_required
def notifications_read():
    db = get_db()
    try:
        db.execute("UPDATE notifications SET read_at=? WHERE user_id=?", (_now(), session['user_id']))
        db.commit()
    except sqlite3.OperationalError:
        pass
    return redirect(url_for('social.notifications'))
