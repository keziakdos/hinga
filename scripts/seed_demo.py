"""Jeu de démonstration Hinga V2 (préfixe DEMO_). JAMAIS en production.

Usage : python3 scripts/seed_demo.py [--db hinga.db]
Suppression : python3 scripts/seed_demo.py --db hinga.db --remove
"""
import argparse
import os
import sqlite3
import sys
import uuid as uuidlib
from datetime import datetime
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from migrate import migrate  # noqa: E402 (garantit le schéma)


def seed(db_path):
    migrate(db_path)
    db = sqlite3.connect(db_path)
    if db.execute("SELECT id FROM users WHERE username='DEMO_marie'").fetchone():
        print('Démo déjà présente, rien à faire.')
        return
    today = datetime.now().strftime('%Y-%m-%d')
    users = [
        ('DEMO_marie', 'Marie', 'Dupont', 'DEMO_marie@exemple.rw', 'Musanze',
         'Jardinière bio depuis 10 ans.', 'des graines anciennes', 'des plants de tomates'),
        ('DEMO_paul', 'Paul', 'Kamanzi', 'DEMO_paul@exemple.rw', 'Huye',
         'Balcon fertile au 3e étage.', 'des outils', 'du compost'),
    ]
    ids = {}
    for u, fn, ln, mail, zone, pres, ch, off in users:
        cur = db.execute("""INSERT INTO users (username, password, role, first_name, last_name, email,
                          notes, is_active, status, zone, presentation, cherche, offre,
                          rules_accepted_at, created_at, uuid)
                          VALUES (?,?, 'membre',?,?,?, '', 1, 'approved', ?,?,?,?,?,?,?)""",
                         (u, generate_password_hash('demo123456'), fn, ln, mail,
                          zone, pres, ch, off, today, today, uuidlib.uuid4().hex))
        ids[u] = cur.lastrowid
    cat = db.execute("SELECT id FROM listing_categories WHERE active=1 ORDER BY position LIMIT 1").fetchone()[0]
    db.execute("""INSERT INTO listings (uuid, user_id, kind, category_id, title, description, quantity,
                  zone, status, views, created_at, updated_at)
                  VALUES (?,?,?,?,?,?,?,?, 'disponible', 0,?,?)""",
               (uuidlib.uuid4().hex, ids['DEMO_marie'], 'don', cat, 'DEMO – Plants de tomates',
                'Une vingtaine de plants en trop, à venir chercher.', '20 plants', 'Musanze',
                today, today))
    lid = db.execute("SELECT id FROM listings WHERE title LIKE 'DEMO%'").fetchone()[0]
    db.execute("INSERT INTO journal_posts (uuid, user_id, text, created_at) VALUES (?,?,?,?)",
               (uuidlib.uuid4().hex, ids['DEMO_paul'], 'DEMO – Mes semis lèvent bien cette semaine !', today))
    db.execute("""INSERT INTO conversations (listing_id, user_a, user_b, created_at, updated_at)
                  VALUES (?,?,?,?,?)""", (lid, ids['DEMO_paul'], ids['DEMO_marie'], today, today))
    cid = db.execute('SELECT id FROM conversations').fetchone()[0]
    db.execute("INSERT INTO messages (conversation_id, author_id, body, created_at) VALUES (?,?,?,?)",
               (cid, ids['DEMO_paul'], 'DEMO – Bonjour, vos plants m’intéressent !', today))
    db.commit()
    print('Démo créée : DEMO_marie / DEMO_paul (mot de passe demo123456).')


DEMO_LIKE = "username LIKE 'DEMO\\_%' ESCAPE '\\'"


def remove(db_path):
    db = sqlite3.connect(db_path)
    demo_ids = f"SELECT id FROM users WHERE {DEMO_LIKE}"
    db.execute(f"DELETE FROM messages WHERE author_id IN ({demo_ids})")
    db.execute(f"DELETE FROM conversations WHERE user_a IN ({demo_ids}) OR user_b IN ({demo_ids})")
    db.execute("DELETE FROM messages WHERE conversation_id NOT IN (SELECT id FROM conversations)")
    db.execute(f"DELETE FROM journal_posts WHERE user_id IN ({demo_ids})")
    db.execute(f"DELETE FROM post_comments WHERE author_id IN ({demo_ids})")
    db.execute(f"DELETE FROM listings WHERE user_id IN ({demo_ids})")
    db.execute(f"DELETE FROM reports WHERE reporter_id IN ({demo_ids})")
    db.execute(f"DELETE FROM notifications WHERE user_id IN ({demo_ids})")
    db.execute(f"DELETE FROM audit_log WHERE actor_id IN ({demo_ids})")
    db.execute(f"DELETE FROM users WHERE {DEMO_LIKE}")
    db.commit()
    print('Démo supprimée.')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', default=os.path.join(os.path.dirname(__file__), '..', 'hinga.db'))
    p.add_argument('--remove', action='store_true')
    a = p.parse_args()
    (remove if a.remove else seed)(a.db)
