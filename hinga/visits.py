"""Audience Hinga : parsing logs, IP connues, CIDR, reverse DNS, GeoIP, UA (V2).

Aucun service externe payant. Base GeoIP lue en local si présente
(GEOIP_DB, voir scripts/update_geoip.sh), sinon pays = Inconnu.
"""
import hashlib
import ipaddress
import json
import os
import re
import socket

BASEDIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
RANGES_FILE = os.path.join(BASEDIR, 'data', 'cloud_ranges.json')

BOT_RE = re.compile(r'bot|crawl|spider|slurp|mediapartners|baidu|yandex|sogou|exabot|facebot|'
                    r'ia_archiver|gptbot|claudebot|ccbot|anthropic|semrush|ahrefs|mj12|dotbot|petal|'
                    r'bytespider|python-requests|curl|wget|httpclient|axios|go-http|java/|libwww|'
                    r'zgrab|masscan|nmap|shodan|censys', re.I)
PROBE_RE = re.compile(r'/\.env|wp-admin|wp-login|phpmyadmin|\.git/|\.svn|xmlrpc\.php|shell\.php|'
                      r'admin\.php|config\.php|\.bak$|\.sql$|console\.php', re.I)
ATTACK_RE = re.compile(r'union\s+select|sleep\s*\(|benchmark\s*\(|\.\./|%2e%2e|etc/passwd|'
                       r'<script|base64_decode|_query\[|GLOBALS\[', re.I)
COMBINED_RE = re.compile(r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>[A-Z]+) '
                         r'(?P<path>\S+)[^"]*" (?P<status>\d{3}) (?P<size>\S+) "(?P<ref>[^"]*)" "(?P<ua>[^"]*)"')
RES_RE = re.compile(r'\.(css|js|mjs|woff2?|ttf|png|jpe?g|gif|svg|ico|map)(\?|$)', re.I)
MOB_RE = re.compile(r'Mobile|Android|iPhone|iPad|iPod|Phone', re.I)
TAB_RE = re.compile(r'iPad|Tablet|SM-T|Lenovo TB', re.I)
LOCAL_RE = re.compile(r'^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1$)')

RDNS_PATTERNS = [
    ('googlebot.com', 'Googlebot', 'moteur'),
    ('google.com', 'Google', 'cloud'),
    ('googleusercontent.com', 'Google Cloud', 'cloud'),
    ('bing.com', 'Bingbot', 'moteur'),
    ('msn.com', 'Bing (Microsoft)', 'moteur'),
    ('amazonaws.com', 'AWS (Amazon)', 'cloud'),
    ('cloudapp.azure.com', 'Azure (Microsoft)', 'cloud'),
    ('azure.com', 'Azure (Microsoft)', 'cloud'),
    ('ovh.net', 'OVH', 'cloud'),
    ('hetzner', 'Hetzner', 'cloud'),
    ('digitalocean', 'DigitalOcean', 'cloud'),
    ('hostinger', 'Hostinger', 'cloud'),
    ('cloudflare', 'Cloudflare', 'service'),
    ('online.net', 'Online/Scaleway', 'cloud'),
    ('contabo', 'Contabo', 'cloud'),
    ('vultr', 'Vultr', 'cloud'),
    ('linode', 'Linode (Akamai)', 'cloud'),
    ('ovhcloud', 'OVHcloud', 'cloud'),
]

CATEGORIES = ('moi', 'vps', 'moteur', 'cloud', 'service', 'inconnu')
ROBOT_CATS = ('moteur', 'cloud')

_rdn_cache = {}
_ranges_cache = None
_geo_instance = None
_geo_tried = False


def _log_day(time_str):
    from datetime import datetime as _dt
    try:
        return _dt.strptime(time_str.split()[0], '%d/%b/%Y:%H:%M:%S').date()
    except (ValueError, IndexError):
        return None


def _brussels(naive_utc):
    from datetime import timezone as _tz
    try:
        from zoneinfo import ZoneInfo
        return naive_utc.replace(tzinfo=_tz.utc).astimezone(ZoneInfo('Europe/Brussels'))
    except Exception:
        return naive_utc


def load_ranges():
    global _ranges_cache
    if _ranges_cache is None:
        _ranges_cache = []
        try:
            with open(RANGES_FILE, encoding='utf-8') as fh:
                data = json.load(fh)
            for entry in data.get('ranges', []):
                try:
                    net = ipaddress.ip_network(entry['cidr'], strict=False)
                except ValueError:
                    continue
                _ranges_cache.append((net, entry.get('label', entry['cidr']),
                                      entry.get('categorie', 'cloud')))
        except (OSError, ValueError):
            pass
    return _ranges_cache


def match_range(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    for net, label, cat in load_ranges():
        try:
            if addr in net:
                return label, cat
        except TypeError:
            continue
    return None


def reverse_dns(ip, budget=25):
    if ip in _rdn_cache or budget <= 0:
        return _rdn_cache.get(ip)
    host = None
    old = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(2)
        host = socket.gethostbyaddr(ip)[0]
    except (OSError, ValueError):
        host = None
    finally:
        try:
            socket.setdefaulttimeout(old)
        except OSError:
            pass
    _rdn_cache[ip] = host
    return host


def rdns_label(host):
    h = (host or '').lower().rstrip('.')
    for suffix, label, cat in RDNS_PATTERNS:
        if h == suffix or h.endswith('.' + suffix):
            return label, cat
    return None


def resolve_ip(ip, db=None, vps_ip='', rdns_budget=25):
    """(label, categorie, source, host). Précédence : connue > CIDR > VPS > rDNS > local."""
    if db is not None:
        try:
            rows = db.execute('SELECT cidr, label, categorie, exclude FROM known_ips').fetchall()
            best = None
            for r in rows:
                spec = (r[0] or '').strip()
                if not spec:
                    continue
                if '/' not in spec:
                    if spec == ip:
                        return r[1] or ip, r[2], 'manuelle', None
                else:
                    try:
                        if ipaddress.ip_address(ip) in ipaddress.ip_network(spec, strict=False):
                            if best is None or len(spec) > len(best[0]):
                                best = (spec, r)
                    except ValueError:
                        continue
            if best:
                r = best[1]
                return r[1] or ip, r[2], 'manuelle', None
        except Exception:
            pass
    hit = match_range(ip)
    if hit:
        return hit[0], hit[1], 'plages CIDR', None
    if vps_ip and ip == vps_ip:
        return 'Mon VPS (Hostinger)', 'vps', 'config', None
    host = reverse_dns(ip, budget=rdns_budget)
    if host:
        labelled = rdns_label(host)
        if labelled:
            return labelled[0], labelled[1], 'reverse DNS', host
        return host, 'inconnu', 'reverse DNS', host
    if LOCAL_RE.match(ip):
        return 'Réseau local', 'moi', 'privée', None
    return ip, 'inconnu', '—', None


def excluded_ips(db):
    try:
        return {r[0] for r in
                db.execute("SELECT cidr FROM known_ips WHERE exclude=1").fetchall() if r[0]}
    except Exception:
        return set()


def is_excluded(ip, excluded):
    for spec in excluded:
        if '/' not in spec:
            if spec == ip:
                return True
        else:
            try:
                if ipaddress.ip_address(ip) in ipaddress.ip_network(spec, strict=False):
                    return True
            except ValueError:
                continue
    return False


def _geo_reader():
    global _geo_instance, _geo_tried
    if not _geo_tried:
        _geo_tried = True
        paths = [os.environ.get('GEOIP_DB', ''),
                 os.path.join(BASEDIR, 'data', 'GeoLite2-Country.mmdb'),
                 os.path.join(BASEDIR, 'data', 'DbIp-country.mmdb'),
                 os.path.join(BASEDIR, 'data', 'dbip-country.mmdb')]
        for path in paths:
            if path and os.path.exists(path):
                try:
                    import maxminddb
                    _geo_instance = maxminddb.open_database(path)
                    break
                except Exception:
                    continue
    return _geo_instance


def flag_emoji(iso):
    if not iso or len(iso) != 2:
        return '🌍'
    base = ord('🇦') - ord('A')
    return chr(base + ord(iso[0].upper())) + chr(base + ord(iso[1].upper()))


def geo_lookup(ip):
    """(drapeau, pays FR, iso). Jamais d'appel réseau."""
    if LOCAL_RE.match(ip or ''):
        return '🏠', 'Réseau local', None
    reader = _geo_reader()
    if reader is None:
        return '🌍', 'Inconnu', None
    try:
        data = reader.get(ip)
    except Exception:
        return '🌍', 'Inconnu', None
    if not data:
        return '🌍', 'Inconnu', None
    country = data.get('country', {}) or {}
    iso = country.get('iso_code')
    names = country.get('names', {}) or {}
    name = names.get('fr') or names.get('en') or iso or 'Inconnu'
    return flag_emoji(iso), name, iso


def parse_ua(ua):
    ua = ua or ''
    low = ua.lower()
    if re.search(r'bot|crawl|spider|slurp|mediapartners|gptbot|claudebot|curl|wget|python|java/|go-http', low):
        browser = 'Robot'
    elif 'edg/' in low or 'edge/' in low:
        browser = 'Edge'
    elif 'opr/' in low or 'opera' in low:
        browser = 'Opera'
    elif 'samsungbrowser' in low:
        browser = 'Samsung Internet'
    elif 'firefox/' in low:
        browser = 'Firefox'
    elif 'chrome/' in low:
        browser = 'Chrome'
    elif 'safari/' in low:
        browser = 'Safari'
    else:
        browser = 'Autre'
    if 'windows' in low:
        os_name = 'Windows'
    elif 'android' in low:
        os_name = 'Android'
    elif 'iphone' in low or 'ipad' in low or 'ios' in low:
        os_name = 'iOS'
    elif 'mac os' in low or 'macintosh' in low:
        os_name = 'macOS'
    elif 'linux' in low:
        os_name = 'Linux'
    else:
        os_name = '?'
    if TAB_RE.search(ua):
        device = 'Tablette'
    elif MOB_RE.search(ua):
        device = 'Mobile'
    else:
        device = 'Desktop'
    return browser, os_name, device


PAGE_NAMES = [
    ('/', 'Accueil'), ('/calendar', 'Calendrier'), ('/login', 'Connexion'),
    ('/register', 'Inscription'), ('/tips', 'Conseils'), ('/echanges', 'Échanges'),
    ('/journal', 'Journal'), ('/messages', 'Messages'), ('/mon-profil', 'Mon profil'),
    ('/stats', 'Statistiques'), ('/harvests', 'Récoltes'), ('/maplante', 'Ma Plante'),
    ('/charte', 'Charte'), ('/confidentialite', 'Confidentialité'),
    ('/mot-de-passe-oublie', 'Mot de passe oublié'), ('/hors-ligne', 'Hors-ligne'),
    ('/admin/visites', 'Admin – visites'), ('/admin/moderation', 'Admin – modération'),
    ('/admin/impact', 'Admin – impact'), ('/admin/audit', 'Admin – audit'),
    ('/admin/users', 'Admin – membres'), ('/admin/plants', 'Admin – plantes'),
    ('/admin/tips', 'Admin – conseils'), ('/admin', 'Admin'),
]


def page_name(path):
    clean = (path or '/').split('?')[0]
    for prefix, label in PAGE_NAMES:
        if prefix == '/':
            if clean == '/':
                return label
        elif clean == prefix:
            return label
    m = re.match(r'^/plant/(\d+)$', clean)
    if m:
        return f"Fiche plante n°{m.group(1)}"
    m = re.match(r'^/tip/(\d+)$', clean)
    if m:
        return f"Conseil n°{m.group(1)}"
    m = re.match(r'^/echanges/(\d+)$', clean)
    if m:
        return f"Annonce n°{m.group(1)}"
    m = re.match(r'^/membres/(.+)$', clean)
    if m:
        return f"Profil {m.group(1)}"
    m = re.match(r'^/journal/(\d+)$', clean)
    if m:
        return f"Billet n°{m.group(1)}"
    m = re.match(r'^/messages/(\d+)$', clean)
    if m:
        return f"Conversation n°{m.group(1)}"
    m = re.match(r'^/stats/plant/(\d+)$', clean)
    if m:
        return f"Stats plante n°{m.group(1)}"
    if clean in ('/sw.js', '/manifest.json', '/favicon.ico', '/robots.txt'):
        return 'Technique (' + clean + ')'
    return clean or '/'


def status_info(code):
    try:
        code = int(code)
    except (TypeError, ValueError):
        return '—', 'bg-gray-200 text-gray-600', ''
    if 200 <= code <= 299:
        return f"{code}", 'bg-green-600 text-white', 'OK'
    if code == 304:
        return f"{code}", 'bg-blue-100 text-blue-800', 'Non modifié (cache)'
    if 300 <= code <= 399:
        return f"{code}", 'bg-blue-100 text-blue-800', 'Redirection'
    if code == 403:
        return f"{code}", 'bg-red-200 text-red-800', 'Accès refusé'
    if code == 404:
        return f"{code}", 'bg-orange-100 text-orange-800', 'Page introuvable'
    if 400 <= code <= 499:
        return f"{code}", 'bg-orange-100 text-orange-800', 'Erreur client'
    if code >= 500:
        return f"{code}", 'bg-red-600 text-white', 'Erreur serveur'
    return f"{code}", 'bg-gray-200 text-gray-600', ''


def ref_label(ref, host=''):
    r = (ref or '').strip()
    if not r or r == '-':
        return 'Direct'
    low = r.lower()
    m = re.match(r'https?://([^/]+)', low)
    domain = m.group(1) if m else low
    if host and domain == host.lower():
        return 'Interne'
    if 'hinga.rwazap.com' in domain:
        return 'Interne'
    parts = domain.split('.')
    short = '.'.join(parts[-2:]) if len(parts) >= 2 else domain
    names = {'google.com': 'Google', 'bing.com': 'Bing', 'duckduckgo.com': 'DuckDuckGo',
             'facebook.com': 'Facebook', 'instagram.com': 'Instagram'}
    for key, label in names.items():
        if key in domain:
            return label
    return short


def ua_hash(ua):
    return hashlib.sha1((ua or '').encode('utf-8', 'replace')).hexdigest()[:12]


def _source(ref):
    r = (ref or '').lower()
    if not r or r == '-':
        return 'Direct'
    if any(d in r for d in ['google.', 'bing.com', 'duckduckgo', 'yahoo.', 'ecosia.', 'brave.com',
                            'qwant.', 'mojeek.', 'startpage.', 'yandex.']):
        return 'Recherche'
    if any(d in r for d in ['facebook.', 'instagram.', 'twitter.', 'x.com', 'linkedin.', 'tiktok.',
                            'pinterest.', 'reddit.', 'whatsapp', 'telegram.', 'youtube.']):
        return 'Réseaux sociaux'
    return 'Autres sites'


def _log_day(time_str):
    from datetime import datetime as _dt
    try:
        return _dt.strptime(time_str.split()[0], '%d/%b/%Y:%H:%M:%S').date()
    except (ValueError, IndexError):
        return None
