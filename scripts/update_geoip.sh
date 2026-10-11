#!/usr/bin/env bash
# Met à jour la base GeoIP locale (pays, hors-ligne, sans compte si DB-IP).
# Option 1 (sans compte) : DB-IP Lite (noms FR inclus), ~1 min.
# Option 2 (noms FR complets + précision) : GeoLite2 (compte MaxMind gratuit),
#   exportez MAXMIND_LICENSE_KEY puis relancez avec --geolite.
# La base n'est JAMAIS commitée (data/*.mmdb ignoré).
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)/data"
mkdir -p "$DIR"

if [ "${1:-}" = "--geolite" ]; then
  [ -n "${MAXMIND_LICENSE_KEY:-}" ] || { echo "Exportez MAXMIND_LICENSE_KEY (compte gratuit : https://www.maxmind.com/en/geolite2/signup)"; exit 1; }
  curl -sL -o "$DIR/GeoLite2-Country.tar.gz" "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-Country&license_key=$MAXMIND_LICENSE_KEY&suffix=tar.gz"
  tar -xzf "$DIR/GeoLite2-Country.tar.gz" -C "$DIR" --wildcards '*/GeoLite2-Country.mmdb' --strip-components=1
  rm -f "$DIR/GeoLite2-Country.tar.gz"
  echo "OK : $DIR/GeoLite2-Country.mmdb"
  exit 0
fi

STAMP=$(date +%Y-%m)
curl -sL -o "$DIR/DbIp-country.mmdb.gz" "https://download.db-ip.com/free/dbip-country-lite-$STAMP.mmdb.gz" \
  || curl -sL -o "$DIR/DbIp-country.mmdb.gz" "https://download.db-ip.com/free/dbip-country-lite-$(date -d 'last month' +%Y-%m).mmdb.gz"
gunzip -kf "$DIR/DbIp-country.mmdb.gz" && rm -f "$DIR/DbIp-country.mmdb.gz"
echo "OK : $DIR/DbIp-country.mmdb (relancez mensuellement, ex. cron le 5 du mois)"
