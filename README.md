# 🌱 Hinga — Mon Potager assisté

Application web de jardinage : **calendrier de semis/récoltes**, **fiches plantes**,
**conseils**, **suivi des récoltes + statistiques**, **analyse photo d'une plante**
(IA, optionnelle). Page d'accueil avec les tâches du moment.

Public, installable en local, sur **Raspberry Pi** ou sur VPS. Conçue pour accueillir
une V2 communautaire (partage/échange/don) — voir `docs/V2-proposition.md`.

---

## 1. Fonctionnalités (V1)

- **Accueil** : plantes enregistrées, à semer / récolter ce mois-ci et le mois prochain.
- **Calendrier** : mois cliquables → plantes à semer vs récolter (gère Nov→Fév).
- **Fiches plantes** : périodes en français, conseils détaillés (soleil, sol, eau…).
- **Conseils** : catégories, photos redimensionnées (page + miniature).
- **Récoltes + Stats** : historique avec photos, production par année/mois/semaine/plante,
  fiche par culture (meilleure période), estimations des récoltes à venir.
- **Ma Plante** : upload photo → analyse IA (Gemini gratuit ou OpenAI, désactivée par défaut).
- **Admin** : plantes, conseils + catégories, membres (approbation des inscriptions,
  rôles membre/modérateur/admin, suspension, journal d'audit).
- **Comptes (V2.1)** : inscription publique (pseudo, email, zone sans adresse exacte,
  charte acceptée) → validation admin ; compte en attente limité au message d'attente.
- **Échanges (V2.2)** : annonces don/échange/recherche + photos, recherche et filtres,
  catégories gérables, signalements.
- **Social (V2.3)** : profils publics, messagerie privée anti-spam, notifications internes.

## 2. Installation en local (essai)

Prérequis : Python 3.10+.

```bash
git clone https://github.com/keziakdos/hinga.git
cd hinga
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 migrate.py          # prépare la base (hinga.db, rétrocompatible)
python3 app.py              # http://127.0.0.1:5000
```

Premier compte : `admin` / `admin123` (créé au premier lancement).
**Changez ce mot de passe aussitôt** (connectez-vous → si besoin, utilisez la page
admin Utilisateurs, ou recréez un compte).

## 3. Configurer l'analyse photo (optionnel)

1. Clé gratuite : https://aistudio.google.com/apikey (ne la commitez jamais).
2. Dans `.env` :
   ```
   GEMINI_API_KEY=votre_cle
   PLANT_ANALYSIS_PROVIDER=gemini
   PLANT_ANALYSIS_ENABLED=1
   ```
3. Relancez. Sans config, les photos sont conservées en « Analyse en attente ».
   (Repli payant possible : `PLANT_ANALYSIS_PROVIDER=openai` + `OPENAI_API_KEY`.)

Autres variables (voir `.env.example`) : `SECRET_KEY` (**obligatoire en production**,
`FLASK_ENV=production` refuse de démarrer sans), `GEMINI_MODEL` (si Google change de modèle).

## 4. Raspberry Pi (maison)

```bash
# Même installation qu'en local (§2), puis service auto au démarrage :
sudo tee /etc/systemd/system/hinga.service >/dev/null <<'EOF'
[Unit]
Description=Hinga
After=network.target
[Service]
User=pi
WorkingDirectory=/home/pi/hinga
Environment="PATH=/home/pi/hinga/venv/bin"
ExecStart=/home/pi/hinga/venv/bin/gunicorn --workers 2 --timeout 90 --bind 127.0.0.1:5000 app:app
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now hinga.service
```

Adaptez `User`/`WorkingDirectory` à votre installation.

## 5. Production VPS (résumé opérateur)

- Dépôt tiré dans le dossier servi (ex. `/var/www/html/hinga.rwazap.com`), nginx en
  frontal (`proxy_pass 127.0.0.1:5000`, `/static` et `/uploads` en alias, 20 Mo max),
  service systemd `hinga.service` comme au §4 (3 workers côté VPS).
- Rituel de mise à jour : **backup → `git pull --ff-only` → `migrate.py` → restart →
  `curl` → rollback possible** (base `.bak` + `git reset --hard`). Ne jamais toucher
  aux autres sites/services.
- Utilisateur dédié recommandé (`webmaster`, sudo limité : `nginx -t`, `reload nginx`,
  `restart/status hinga.service`).

## 6. Sauvegarde / restauration

```bash
./scripts/backup_hinga.sh /var/www/html/hinga.rwazap.com ~/hinga_backups
# => dossier daté : hinga.db (copie à chaud), medias.tgz, .env (600), VERSION.txt
```

Restauration : stoppez le service, recopiez `hinga.db` + `medias.tgz` (+ `.env` si besoin),
redémarrez, vérifiez au `curl`.

## 7. Visites : robots vs humains (V1)

```bash
./scripts/analyse_visites.sh /var/log/nginx/hinga.access.log 30
# => requêtes, part robots/humains, répartition par jour, top pages, top IP
```

Lecture seule, sans dépendance. Un tableau de bord temps réel est prévu en V2.

## 8. Sécurité

- Requêtes SQL paramétrées ; échappement HTML auto (Jinja) ; uploads validés
  (type réel, 10 Mo, noms uniques, miniatures) ; mots de passe hashés ;
  protection **CSRF** sur tous les formulaires ; **rate-limit** anti-brute-force
  sur la connexion (20/min, page 429) ; cookies `HttpOnly` + `SameSite=Lax`
  (`Secure` activable via `SESSION_COOKIE_SECURE=1` en HTTPS) ;
  `SECRET_KEY` via `.env` (démarrage prod refusé sans) ; `.env`/`*.db` jamais dans git
  (vérifié sur tout l'historique) ; pages 404/429/500 dédiées.
- **À faire côté opérateur** : `SECRET_KEY` longue et unique, HTTPS forcé, compte
  `admin` par défaut renommé/désactivé après création de vos comptes, backups testés.
- **Prévu V2** : politique de mot de passe, en-têtes de sécurité (CSP/HSTS) côté frontal,
  stockage persistant du rate-limit (au lieu de la mémoire par worker).

## 9. Structure

```
app.py                 # point d'entrée (gunicorn app:app)
hinga/                 # paquet applicatif (blueprints)
  __init__.py          # config, sessions, erreurs
  auth.py              # connexion / déconnexion
  garden.py            # accueil, calendrier, récoltes, stats, Ma Plante
  admin.py             # plantes, conseils, utilisateurs
  db.py                # SQLite + init/seed
  helpers.py           # mois FR, périodes à cheval, noms uniques
  utils.py             # uploads, miniatures
  services/images.py   # upload conseils (validation + resize)
  services/plant_analysis.py  # IA interchangeable (gemini/openai/inactif)
migrate.py             # migrations rétrocompatibles + backup auto
scripts/backup_hinga.sh / analyse_visites.sh
templates/ (+ admin/)  # Tailwind local, style glass existant
docs/V2-proposition.md # espace échange/don de la V2
docs/V2-architecture.md# audit + plan V2
```

Licence : MIT (voir `LICENSE`). V2 : `docs/V2-proposition.md`.
