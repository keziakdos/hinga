#!/usr/bin/env bash
# Purge RGPD : supprime les logs nginx rotatés plus vieux que N jours (défaut 90).
# Le log courant n'est JAMAIS touché. L'app ne stocke aucune IP en base
# (sauf labels saisis par l'admin dans known_ips).
# Usage : ./scripts/purge_visits.sh [90] [/var/log/nginx]
set -u
DAYS="${1:-90}"
LOGDIR="${2:-/var/log/nginx}"
find "$LOGDIR" -maxdepth 1 -name "*.log.*.gz" -mtime "+$DAYS" -print -delete
find "$LOGDIR" -maxdepth 1 -name "*.log.[0-9]*" -mtime "+$DAYS" -print -delete
echo "Purge > $DAYS jours terminee dans $LOGDIR."
