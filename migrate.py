"""Migration Hinga (Lots 0 + V2 étape 1), rétrocompatible.

Usage local :
    python3 migrate.py            # applique sur hinga.db (avec sauvegarde auto)
    python3 migrate.py --db PATH  # autre base

Ne supprime rien. Ajoute uniquement :
- users (Lot 0) : first_name, last_name, email, notes, is_active (défaut 1)
- users (V2.1) : status (pending/approved/refused/suspended, défaut approved),
  zone, presentation, cherche, offre, motif, rules_accepted_at, created_at, uuid
- rôles : 'user' historique -> 'membre' (admin inchangé)
- audit_log(id, actor_id, action, target_kind, target_id, details, created_at)
- tip_categories(id, name UNIQUE) + tips.category_id (+ 4 catégories de base)
- V2.2 annonces : listing_categories(id, uuid, name, parent_id, position, active,
  created_at) + jeu de départ ; listings + listing_photos ; reports
- V2.3 social : users.avatar, users.jardin ; conversations, messages,
  notifications
- V2.4 confiance : journal_posts, post_comments, ratings
Sauvegarde auto dans backup/ avant toute écriture.
"""
import argparse
import os
import shutil
import sqlite3
import uuid as uuidlib
from datetime import datetime

BASEDIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_DB = os.path.join(BASEDIR, "hinga.db")
BACKUP_DIR = os.path.join(BASEDIR, "backup")

BASE_CATEGORIES = ["Sol", "Eau", "Plantation", "Entretien"]

LISTING_CATEGORIES = [
    "Plantes, boutures et plants",
    "Semis et graines",
    "Récoltes en surplus",
    "Nourriture et conserves",
    "Matériel et outils",
    "Autres",
]


def columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate(db_path: str) -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKUP_DIR, f"hinga_{stamp}.db")
    shutil.copy2(db_path, backup)
    print(f"Sauvegarde : {backup}")

    conn = sqlite3.connect(db_path)
    try:
        # --- users : enrichissement profil + activation ---
        ucols = columns(conn, "users")
        for coldef in [
            ("first_name", "TEXT DEFAULT ''"),
            ("last_name", "TEXT DEFAULT ''"),
            ("email", "TEXT DEFAULT ''"),
            ("notes", "TEXT DEFAULT ''"),
            ("is_active", "INTEGER DEFAULT 1"),
        ]:
            name, typedef = coldef
            if name not in ucols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {typedef}")
                print(f"+ users.{name}")

        # --- users V2.1 : approbation, zone, traçabilité ---
        ucols = columns(conn, "users")
        for coldef in [
            ("status", "TEXT DEFAULT 'approved'"),
            ("zone", "TEXT DEFAULT ''"),
            ("presentation", "TEXT DEFAULT ''"),
            ("cherche", "TEXT DEFAULT ''"),
            ("offre", "TEXT DEFAULT ''"),
            ("motif", "TEXT DEFAULT ''"),
            ("rules_accepted_at", "TEXT DEFAULT ''"),
            ("created_at", "TEXT DEFAULT ''"),
            ("uuid", "TEXT DEFAULT ''"),
        ]:
            name, typedef = coldef
            if name not in ucols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {typedef}")
                print(f"+ users.{name}")

        # Rôles historiques 'user' -> 'membre' (non destructif, documenté)
        n = conn.execute("UPDATE users SET role='membre' WHERE role='user'").rowcount
        if n:
            print(f"~ {n} rôle(s) 'user' -> 'membre'")

        # Remplissage uuid / created_at manquants
        today = datetime.now().strftime('%Y-%m-%d')
        for (uid,) in conn.execute("SELECT id FROM users WHERE uuid IS NULL OR uuid=''").fetchall():
            conn.execute("UPDATE users SET uuid=? WHERE id=?", (uuidlib.uuid4().hex, uid))
        conn.execute("UPDATE users SET created_at=? WHERE created_at IS NULL OR created_at=''",
                     (today,))

        # --- journal d'audit admin ---
        conn.execute(
            """CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER, action TEXT NOT NULL,
                target_kind TEXT DEFAULT '', target_id INTEGER,
                details TEXT DEFAULT '', created_at TEXT
            )"""
        )

        # --- V2.2 : catégories d'annonces + jeu de départ ---
        conn.execute(
            """CREATE TABLE IF NOT EXISTS listing_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT DEFAULT '', name TEXT NOT NULL,
                parent_id INTEGER, position INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1, created_at TEXT
            )"""
        )
        lcols = columns(conn, "listing_categories")
        if "uuid" not in lcols:
            conn.execute("ALTER TABLE listing_categories ADD COLUMN uuid TEXT DEFAULT ''")
        today = datetime.now().strftime('%Y-%m-%d')
        pos = conn.execute("SELECT COUNT(*) FROM listing_categories").fetchone()[0]
        for cat in LISTING_CATEGORIES:
            if not conn.execute("SELECT id FROM listing_categories WHERE name=? AND parent_id IS NULL",
                                (cat,)).fetchone():
                conn.execute("""INSERT INTO listing_categories (uuid, name, parent_id, position, active, created_at)
                                VALUES (?,?,?,?,1,?)""", (uuidlib.uuid4().hex, cat, None, pos, today))
                pos += 1
                print(f"+ catégorie annonce : {cat}")
        for (cid,) in conn.execute("SELECT id FROM listing_categories WHERE uuid IS NULL OR uuid=''").fetchall():
            conn.execute("UPDATE listing_categories SET uuid=? WHERE id=?", (uuidlib.uuid4().hex, cid))

        # --- V2.2 : annonces + photos + signalements ---
        conn.execute(
            """CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT DEFAULT '', user_id INTEGER NOT NULL,
                kind TEXT NOT NULL, category_id INTEGER,
                title TEXT NOT NULL, description TEXT DEFAULT '',
                quantity TEXT DEFAULT '', zone TEXT DEFAULT '',
                available_from TEXT DEFAULT '', available_until TEXT DEFAULT '',
                status TEXT DEFAULT 'disponible',
                views INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS listing_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                filename TEXT NOT NULL, position INTEGER DEFAULT 0
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER, target_kind TEXT NOT NULL,
                target_id INTEGER NOT NULL, reason TEXT NOT NULL,
                details TEXT DEFAULT '', status TEXT DEFAULT 'open',
                created_at TEXT
            )"""
        )

        # --- V2.3 : profils + messagerie + notifications ---
        ucols = columns(conn, "users")
        for coldef in [
            ("avatar", "TEXT DEFAULT ''"),
            ("jardin", "TEXT DEFAULT ''"),
        ]:
            name, typedef = coldef
            if name not in ucols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {typedef}")
                print(f"+ users.{name}")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT DEFAULT '', listing_id INTEGER,
                user_a INTEGER NOT NULL, user_b INTEGER NOT NULL,
                created_at TEXT, updated_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                author_id INTEGER NOT NULL, body TEXT NOT NULL,
                created_at TEXT, read_at TEXT DEFAULT ''
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, kind TEXT DEFAULT '',
                title TEXT NOT NULL, link TEXT DEFAULT '',
                read_at TEXT DEFAULT '', created_at TEXT
            )"""
        )

        # --- V2.4 : journal de jardin + confiance mutuelle ---
        conn.execute(
            """CREATE TABLE IF NOT EXISTS journal_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT DEFAULT '', user_id INTEGER NOT NULL,
                text TEXT NOT NULL, photo TEXT DEFAULT '',
                created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS post_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL REFERENCES journal_posts(id) ON DELETE CASCADE,
                author_id INTEGER NOT NULL, body TEXT NOT NULL,
                hidden INTEGER DEFAULT 0, created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL, author_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL, score INTEGER NOT NULL,
                comment TEXT DEFAULT '', created_at TEXT,
                UNIQUE(conversation_id, author_id)
            )"""
        )

        # --- tip_categories + tips.category_id ---
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tip_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )"""
        )
        for cat in BASE_CATEGORIES:
            conn.execute(
                "INSERT OR IGNORE INTO tip_categories (name) VALUES (?)", (cat,)
            )
        tcols = columns(conn, "tips")
        if "category_id" not in tcols:
            conn.execute("ALTER TABLE tips ADD COLUMN category_id INTEGER DEFAULT NULL")
            print("+ tips.category_id")
        conn.commit()
        print("Migration OK (rétrocompatible, aucune donnée supprimée).")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args()
    if not os.path.exists(args.db):
        raise SystemExit(f"Base introuvable : {args.db}")
    migrate(args.db)
