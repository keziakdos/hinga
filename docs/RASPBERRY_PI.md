# Hinga sur Raspberry Pi — guide pas à pas (V2.7)

Objectif : un Hinga de quartier, sobre, qui tourne même sans internet
(boîte de partage locale). Testé sur Raspberry Pi OS (Debian) avec Python 3.11+.

## 1. Préparer le Pi

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
```

## 2. Installer Hinga

```bash
git clone https://github.com/keziakdos/hinga.git
cd hinga
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Renseignez SECRET_KEY (obligatoire) : une longue chaîne aléatoire.
# Laissez PLANT_ANALYSIS_ENABLED=0 (pas d'IA sans internet).
python3 - <<'EOF'
import secrets
print(secrets.token_hex(32))
EOF
python3 migrate.py
python3 app.py   # essai : http://IP-DU-PI:5000
```

Premier compte : `admin` / `admin123` → changez-le aussitôt.

## 3. Démarrage automatique (systemd)

```bash
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

Adaptez `User`/`WorkingDirectory`. 2 workers suffisent (faible RAM).

## 4. Accès local sans internet (« boîte de quartier »)

- Le Pi crée (ou rejoint) le Wi-Fi local ; les voisins ouvrent `http://IP-DU-PI:5000`.
- Tout fonctionne sauf l'analyse photo IA (désactivée par défaut, les photos restent
  en « Analyse en attente »).
- Astuce : la PWA met en cache les fiches déjà visitées (mode avion OK après 1re visite).

## 5. Sauvegardes (clé USB)

```bash
./scripts/backup_hinga.sh /home/pi/hinga ~/hinga_backups          # local
./scripts/export_usb.sh /media/pi/CLE /home/pi/hinga              # vers clé USB
./scripts/import_usb.sh /media/pi/CLE/hinga_export_AAAAMMJJ_HHMMSS /home/pi/hinga
sudo systemctl restart hinga.service
```

Testez la restauration une fois avant d'en avoir besoin.

## 6. Sobriété

SQLite par défaut, aucun cloud obligatoire, images compressées côté serveur,
pages légères : confortable dès 1 Go de RAM.
