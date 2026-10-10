# Hinga V2 — Audit + Plan d'architecture (à valider avant code)

Triple casquette : impact social non lucratif, résilience (marche sur RPi, hors ligne),
dév senior sobre. La V1 reste intacte et fonctionnelle à chaque étape.

## 1. Audit de l'existant (vérifié le 09/10/2026)

- **Code** : `app.py` monolithique (~1000 lignes), 27 routes, pas de blueprints ;
  `helpers.py`, `services/images.py`, `services/plant_analysis.py` (déjà modulaires).
- **Base SQLite** : `users(id,username,password,role,first_name,last_name,email,notes,is_active)`,
  `plants` (18 col.), `tips+tip_categories`, `harvests`, `monitored_plants`.
  Auth par session, rôles = simples chaînes `admin/user`, **pas de CSRF**,
  **pas de limite de tentatives**, pas de reset mot de passe.
- **Dépendances externes à l'exécution (bloquant pour la résilience)** : Tailwind CDN,
  Phosphor Icons CDN, Google Fonts, Chart.js CDN, images `pollinations.ai` en repli.
  → À rapatrier en local (étape 0) : CSS/JS/polices/icônes auto-hébergés,
  placeholder local, graphiques en CSS/SVG ou Chart.js local.
- **À réutiliser tel quel** : `migrate.py` (migrations rétrocompatibles),
  `services/images.py` (validation + resize, parfait pour annonces/avatars),
  `scripts/backup_hinga.sh`, garde `is_active`, design glass + classes.

## 2. Architecture cible (sans refonte V1)

- Découpage en **blueprints** dans un paquet `hinga/` : `garden` (V1 existante, inchangée),
  `auth` (inscription/approbation/login), `exchange` (annonces), `social` (profils,
  messagerie, journal), `admin` (modération, audit, impact), `pwa` (manifeste, service worker).
- **Fédération future sans complexité** : `id` locaux + `uuid` global par objet partageable,
  `created_at/updated_at`, `instance_id` en config ; synchro = hors périmètre, schéma prêt.
- **Zéro cloud obligatoire** : SQLite par défaut, IA plante déjà désactivable,
  notifications **dans le site** (email optionnel externe uniquement).

## 3. Schéma de données (ajouts, `migrate.py`, rien de supprimé)

- `users +=` `status` (pending/approved/refused/suspended), `motif` (refus),
  `zone` (ville/région), `presentation`, `cherche`, `offre`, `avatar`, `jardin`,
  `rules_accepted_at`, `email_verified`, `last_login`, `uuid`.
- `roles` : garder la colonne `role` (`membre/moderateur/admin`), garde-fou dernier admin en code.
- `audit_log(id, actor_id, action, target_kind, target_id, details, created_at)`.
- `listing_categories(id, name, parent_id NULL, position, active, uuid)`.
- `listings(id, uuid, user_id, kind[don|echange|recherche], category_id, title, description,
  quantity, unit, zone, available_from, available_until, status[disponible|reserve|termine],
  views, created_at, updated_at)` + `listing_photos(id, listing_id, filename, position)`.
- `conversations(id, uuid, listing_id NULL, user_a, user_b, created_at)` +
  `messages(id, conversation_id, author_id, body, created_at, read_at)`.
- `journal_posts(id, uuid, user_id, text, photo, created_at)` +
  `post_comments(id, post_id, author_id, body, created_at, hidden)`.
- `ratings(id, request_or_listing, author_id, target_id, score 1-5, comment, created_at)`
  → badge fiabilité = moyenne + nb échanges terminés (pas de points).
- `reports(id, reporter_id, target_kind, target_id, reason, details, status, created_at)`.
- `notifications(id, user_id, kind, title, link, read_at, created_at)`.
- `password_resets(id, user_id, token_hash, expires_at, used)` (email si dispo,
  sinon reset manuel admin = mise à jour mot de passe tracée en audit).
- Annonces périmées : statut auto `termine` par date + tâche au démarrage (pas de cron requis).

## 4. Étapes testables (petites, V1 toujours verte)

- **Étape 0 — Socle** : blueprints (déplacement à code constant), CSRF (Flask-WTF),
  rate-limit login (Flask-Limiter), sessions (`Secure` si HTTPS, `HttpOnly`,publique
  `SameSite=Lax`), assets 100 % locaux, placeholder local, suppression des CDN.
  Test : V1 identique visuellement + hors ligne (câble débranché, tout sauf IA marche).
- **Étape 1 — Comptes & rôles** : inscription (charte + zone, sans adresse),
  statuts pending/approved/refused/suspended, login limité si pending,
  multi-admin + garde dernier admin, `audit_log`, reset manuel admin.
  Test : cycle complet d'approbation, dernier admin insuppressible.
- **Étape 2 — Catégories & annonces** : CRUD catégories (ordre, actif, sous-catégories),
  jeu de départ (Plantes, Semis/graines dont anciennes, Récoltes, Nourriture,
  Matériel/outils, Autres), CRUD annonces + photos (pipeline existant), recherche/
  filtres/tri, « Mes annonces », `termine`, signalement.
  Test : jeu de démo + parcours visiteur complet.
- **Étape 3 — Messagerie & profils** : profil public (avatar, zone, jardin, historique),
  conversations liées ou libres, limite anti-spam, notifications internes.
- **Étape 4 — Journal & confiance** : posts photo+texte, commentaires (masquables),
  notation mutuelle post-échange → badge, indicateurs d'impact admin
  (échanges, kg partagés, variétés préservées).
- **Étape 5 — Modération** : file signalements, masquer/supprimer, avertissements
  (rencontres, hygiène alimentaire, invasives), charte affichée.
- **Étape 6 — PWA/hors ligne** : manifeste, service worker (cache annonces+fiches),
  page imprimable / export PDF (print CSS), test LAN sans internet.
- **Étape 7 — Sauvegarde/RPi** : export/import USB (base + images, script unique),
  guide RPi (OS, systemd, autotest), guide VPS, jeu de démo, charte, guide admin.

## 5. Gouvernance & amorçage (associatif, non lucratif)

- **Gouvernance** : 2+ admins, charte votée simplement, conflits = médiation par un
  admin tiers puis vote admins, traçabilité via `audit_log`, pas de publicité ni revente.
- **Amorçage** : parrainage (badge parrain), défi de saison (ex. « 10 dons en octobre »),
  bourse aux graines annuelle (catégorie + date mises en avant).
- **Financement** : dons libres, hébergement mutualisé/RPi communautaire, partenariats
  (associations, grainothèques) ; coûts quasi nuls (SQLite, pas de cloud).

## 6. Risques & garde-fous

- Dérive périmètre → étapes petites, V1 verte exigée à chaque fusion.
- Photos lourdes → pipeline existant + limite stricte (déjà validé en V1).
- Abus/spam → approbation manuelle + limites + signalements dès l'étape 1-2.
- Données perso → zone seulement, IP hachée si journalisée, export/effacement RGPD.
- Perf RPi → requêtes paginées (20/page), pas de JS lourd, images compressées.

**En attente de validation** : périmètre des 8 étapes, jeu de catégories de départ,
et confirmation que l'étape 0 (assets locaux + sécurité) passe en premier.
