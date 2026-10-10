#!/usr/bin/env bash
# Restauration Hinga depuis un export USB. Sauvegarde l'existant AVANT d'écraser.
# Usage : ./scripts/import_usb.sh /media/$USER/CLE/hinga_export_AAAAMMJJ_HHMMSS [/var/www/html/hinga.rwazap.com]
# Après : migrate.py + restart du service, puis vérifications (voir docs/VPS.md).
set -u
SRC="${1:?usage : $0 <dossier_export> [dossier_app]}"
APP_DIR="${2:-/var/www/html/hinga.rwazap.com}"

[ -f "$SRC/hinga.db" ] || { echo "Export invalide : $SRC/hinga.db absent"; exit 1; }
[ -f "$SRC/medias.tgz" ] || { echo "Export invalide : medias.tgz absent"; exit 1; }

BAK="$APP_DIR/pre-restauration_$(date +%Y%m%d_%H%M%S).db"
cp "$APP_DIR/hinga.db" "$BAK" && echo "Sauvegarde existant : $BAK"
cp "$SRC/hinga.db" "$APP_DIR/hinga.db" && echo "OK base restauree"
tar -xzf "$SRC/medias.tgz" -C "$APP_DIR" && echo "OK medias restaures"
echo "Version exportee : $(cat "$SRC/VERSION.txt" 2>/dev/null || echo inconnue)"
echo "SUITE : python3 $APP_DIR/migrate.py && restart hinga.service (docs/VPS.md)."
