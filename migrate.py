"""Migration Hinga V1 rétrocompatible (Lot 0).

Usage local :
    python3 migrate.py            # applique sur hinga.db (avec sauvegarde auto)
    python3 migrate.py --db PATH  # autre base

Ne supprime rien. Ajoute uniquement :
- users : first_name, last_name, email, notes, is_active (défaut 1)
- tip_categories(id, name UNIQUE) + tips.category_id (+ 4 catégories de base)
Sauvegarde auto dans backup/ avant toute écriture.
"""
import argparse
import os
import shutil
import sqlite3
from datetime import datetime

BASEDIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_DB = os.path.join(BASEDIR, "hinga.db")
BACKUP_DIR = os.path.join(BASEDIR, "backup")

BASE_CATEGORIES = ["Sol", "Eau", "Plantation", "Entretien"]


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
