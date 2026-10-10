#!/usr/bin/env bash
# Export Hinga vers clé USB (ou dossier) : base + images + version. Lecture seule côté app.
# Usage : ./scripts/export_usb.sh /media/$USER/CLE [/var/www/html/hinga.rwazap.com]
set -u
DEST_BASE="${1:?usage : $0 /media/utilisateur/CLE [dossier_app]}"
APP_DIR="${2:-/var/www/html/hinga.rwazap.com}"
STAMP=$(date +%Y%m%d_%H%M%S)
DEST="$DEST_BASE/hinga_export_$STAMP"
mkdir -p "$DEST" || exit 1

echo "== Export Hinga -> $DEST"
if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$APP_DIR/hinga.db" ".backup '$DEST/hinga.db'"
else
    python3 -c "import sqlite3; sqlite3.connect('$APP_DIR/hinga.db').backup(sqlite3.connect('$DEST/hinga.db'))"
fi
echo "OK base"
tar -czf "$DEST/medias.tgz" -C "$APP_DIR" static/img uploads 2>/dev/null && echo "OK medias"
git -C "$APP_DIR" rev-parse HEAD > "$DEST/VERSION.txt" 2>/dev/null
cat > "$DEST/LISEZMOI.txt" <<EOF
Export Hinga du $STAMP (version : $(cat "$DEST/VERSION.txt" 2>/dev/null || echo inconnue)).
Restauration : ./scripts/import_usb.sh $DEST <dossier_app>
Ne contient JAMAIS le .env (clés API) : à reconfigurer à la main.
EOF
echo "== Termine. Retirez la clé proprement (ejecter)."
ls -la "$DEST"
