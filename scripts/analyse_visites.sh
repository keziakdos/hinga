#!/usr/bin/env bash
# Analyse des visites Hinga depuis les logs nginx : humains vs robots, frequence.
# Lecture seule, zero dependance (awk/grep).
# Usage : ./scripts/analyse_visites.sh [/var/log/nginx/hinga.access.log] [7]
# (tableau de bord temps reel : prevu V2, voir docs/V2-proposition.md)
set -u
LOG="${1:-/var/log/nginx/access.log}"
DAYS="${2:-7}"

if [ ! -f "$LOG" ]; then
    echo "Log introuvable : $LOG"
    echo "Usage : $0 /chemin/vers/hinga.access.log [jours]"
    echo "Astuce : ls /var/log/nginx/ | grep -i hinga"
    exit 1
fi

BOT='bot|crawl|spider|slurp|mediapartners|baidu|yandex|sogou|exabot|facebot|ia_archiver|gptbot|claudebot|ccbot|anthropic|semrush|ahrefs|mj12|dotbot|petal|bytespider|python-requests|curl|wget|httpclient|axios|go-http|java/|libwww|zgrab|masscan|nmap|shodan|censys'

echo "== Visites Hinga ($LOG, $DAYS derniers jours) =="
SINCE=$(date -d "$DAYS days ago" +%d/%b/%Y 2>/dev/null || echo "")
RECENT=$(awk -v s="[$SINCE" '$0 ~ s,0' "$LOG" 2>/dev/null | tail -n +1)
[ -z "$RECENT" ] && RECENT=$(cat "$LOG")
TOTAL=$(echo "$RECENT" | wc -l)
BOTS=$(echo "$RECENT" | grep -ciE "$BOT")
HUMANS=$((TOTAL - BOTS))
echo "Requetes : $TOTAL | Humains (est.) : $HUMANS | Robots : $BOTS"

echo "--- Par jour ---"
echo "$RECENT" | awk '{print $4}' | tr -d '[' | cut -d: -f1 | sort | uniq -c | sort -r | head -15

echo "--- Bots : top signatures ---"
echo "$RECENT" | grep -oiE "[A-Za-z0-9_.-]*(bot|crawler|spider|crawl)[A-Za-z0-9_./-]*" | sort | uniq -c | sort -rn | head -10

echo "--- Pages les plus vues (humains) ---"
echo "$RECENT" | grep -viE "$BOT" | awk -F'"' '{print $2}' | awk '{print $2}' | grep -E '^/' | sort | uniq -c | sort -rn | head -15

echo "--- Top IP humaines (nb requetes) ---"
echo "$RECENT" | grep -viE "$BOT" | awk '{print $1}' | sort | uniq -c | sort -rn | head -10
