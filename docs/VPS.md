# Hinga sur VPS — guide opérateur (V2.7)

Public : la personne qui déploie (utilisateur `webmaster`, jamais en root sauf mention).
Ne jamais toucher aux autres sites/services du serveur.

## 1. Rituel de mise à jour (chaque lot)

```bash
cp /var/www/html/hinga.rwazap.com/hinga.db /var/www/html/hinga.rwazap.com/hinga_$(date +%Y%m%d_%H%M%S).db.bak
git -C /var/www/html/hinga.rwazap.com pull --ff-only
git -C /var/www/html/hinga.rwazap.com log --oneline -3
python3 /var/www/html/hinga.rwazap.com/migrate.py
# si requirements.txt a changé :
/var/www/html/hinga.rwazap.com/venv/bin/pip install -r /var/www/html/hinga.rwazap.com/requirements.txt
sudo systemctl restart hinga.service
sleep 3
curl -s -o /dev/null -w "accueil: %{http_code}\n" https://hinga.rwazap.com/
```

## 2. Retour arrière

```bash
git -C /var/www/html/hinga.rwazap.com reset --hard <commit_precedent>
cp /var/www/html/hinga.rwazap.com/hinga_<date>.db.bak /var/www/html/hinga.rwazap.com/hinga.db
sudo systemctl restart hinga.service
```

## 3. Variables du `.env` (jamais dans git)

`SECRET_KEY` (obligatoire), `GEMINI_API_KEY` + `PLANT_ANALYSIS_PROVIDER=gemini` +
`PLANT_ANALYSIS_ENABLED=1` (analyse photo), `GEMINI_MODEL` (si Google change de modèle),
`SESSION_COOKIE_SECURE=1` (HTTPS). Sauvegardé par `backup_hinga.sh` (droits 600).

## 4. Logs utiles

```bash
sudo systemctl status hinga.service --no-pager | head -30   # workers, erreurs
./scripts/analyse_visites.sh /var/log/nginx/hinga.access.log 7   # humains vs robots
```

## 5. Utilisateur `webmaster` (création root, une fois)

Voir l'historique du projet : `adduser webmaster`, clé SSH, propriété du seul dossier
Hinga, `/etc/sudoers.d/webmaster-hinga` (`nginx -t`, `reload nginx`,
`restart/status hinga.service`, validé par `visudo -c`).
