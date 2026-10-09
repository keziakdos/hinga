#!/usr/bin/env bash
# Backup Hinga : base SQLite + images + .env + version git.
# Usage : ./scripts/backup_hinga.sh [/var/www/html/hinga.rwazap.com] [~/hinga_backups]
# Ne touche à rien d'autre. Restauration : voir README (section Sauvegarde).
set -u
APP_DIR="${1:-/var/www/html/hinga.rwazap.com}"
BACKUP_BASE="${2:-$HOME/hinga_backups}"
KEEP=14

STAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_BASE/hinga_$STAMP"
mkdir -p "$DEST" || { echo "Echec creation $DEST"; exit 1; }

echo "== Backup Hinga -> $DEST"

# 1. Base SQLite (copie à chaud sûre si sqlite3 dispo, sinon cp + avertissement)
if [ -f "$APP_DIR/hinga.db" ]; then
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$APP_DIR/hinga.db" ".backup '$DEST/hinga.db'" && echo "OK base (.backup sqlite3)"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import sqlite3; sqlite3.connect('$APP_DIR/hinga.db').backup(sqlite3.connect('$DEST/hinga.db'))" \
            && echo "OK base (.backup python)"
    else
        cp "$APP_DIR/hinga.db" "$DEST/hinga.db" && echo "AVERTISSEMENT: copie cp (arretez le service pour une garantie totale)"
    fi
else
    echo "Base introuvable : $APP_DIR/hinga.db"
fi

# 2. Images + uploads
tar -czf "$DEST/medias.tgz" -C "$APP_DIR" static/img uploads 2>/dev/null && echo "OK medias"

# 3. Config (droits stricts, contient les cles !)
if [ -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env" "$DEST/env.bak" && chmod 600 "$DEST/env.bak" && echo "OK .env (600)"
fi

# 4. Version du code
git -C "$APP_DIR" rev-parse HEAD > "$DEST/VERSION.txt" 2>/dev/null && echo "OK version $(cat "$DEST/VERSION.txt")"

# 5. Rotation : garde les KEEP plus recents
ls -1dt "$BACKUP_BASE"/hinga_* 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf
echo "== Termine : $DEST"
ls -la "$DEST"
