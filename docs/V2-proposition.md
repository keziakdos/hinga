# Hinga V2 — Espace partage / échange / don : proposition professionnelle

**Contexte.** Hinga V1 (calendrier, fiches plantes, conseils, récoltes, stats, analyse photo)
est conçue en modules (`app.py` + `helpers.py` + `services/`, SQLite via `migrate.py`
rétrocompatible) pour accueillir la V2 **sans refonte** : la V2 ajoute un espace
d'échange entre utilisateurs inscrits (dons, échanges, surplus de récoltes,
semences anciennes). Ce document cadre le périmètre, les règles et le plan.

---

## 1. Objectifs et périmètre V2

- Permettre aux jardiniers inscrits de proposer : **dons**, **échanges**, **semences
  anciennes**, **plants/semis**, **surplus de récoltes**.
- Mise en relation locale (retrait en main propre, par zone), **sans paiement en ligne**
  dans un premier temps (échange/don ; la monétisation éventuelle est hors périmètre).
- Préserver la simplicité V1 : un nouveau **module isolé** (`services/exchange/`,
  blueprint `exchange`), aucune modification du design global.

## 2. Comptes, profils publics, inscription / connexion

- Inscription : pseudo unique, email vérifié (lien de confirmation), mot de passe
  robuste (politique + hash `werkzeug`, réutiliser le socle V1), case RGPD obligatoire.
- Connexion existante conservée ; ajouter : mot de passe oublié (token email),
  désactivation par l'utilisateur, suppression de compte (droit à l'effacement,
  anonymisation des annonces clôturées).
- Profil public : pseudo, **commune ou région** (jamais d'adresse exacte), bio courte,
  photo d'avatar (via `services/images.py`, mêmes règles : 10 Mo, resize), ancienneté,
  note moyenne, nombre d'échanges terminés.
- Page profil visitable : « ce que cet utilisateur propose » (annonces actives
  uniquement), historique d'avis reçus.

## 3. Annonces

- Types : `don`, `echange`, `semence_ancienne`, `plant`, `semis`, `surplus_recolte`.
- Champs : plante liée (référentiel `plants` V1 + champ libre si absente), quantité
  + unité (g, kg, sachet, godet…), photos (1–4, pipeline `services/images.py`),
  disponibilité (dates / « jusqu'à épuisement »), **zone de retrait** (commune/rayon,
  pas d'adresse exacte), message du donneur, statut (`active`, `réservée`, `terminée`,
  `retirée`), horodatage, compteur de vues (anti-abus : pas de bump automatique).
- Règles : 1 annonce = 1 plante + 1 type ; durée de vie limitée (ex. 30 jours,
  renouvelable 1 fois) pour garder un catalogue frais ; interdiction de vente
  déguisée (CGU + signalement).

## 4. Messagerie / demandes d'échange avec statuts

- Demande d'échange **structurée** (pas de messagerie libre au départ) : bouton
  « Proposer » → message prédéfini + créneau de retrait proposé → statuts
  `proposé / accepté / refusé / terminé / annulé`, visibles des deux côtés.
- Étape 2 (optionnelle) : messagerie interne minimale liée à la demande (fil unique,
  anti-spam : limite de messages/jour, blocage utilisateur, pas de pièces jointes
  exécutables, purge auto des fils clôturés après 90 jours).
- Notifications : email (opt-in) + badge interne ; jamais de SMS (coût).

## 5. Recherche et filtres

- Recherche plein texte (titre/plante), filtres : type d'annonce, plante, région/
  commune, rayon (sans géoloc précise : zones déclaratives + liste de communes),
  disponibilité, tri (récent, proximité déclarée).
- Index SQLite FTS5 pour la recherche ; pagination (20/page) ; URLs partageables
  avec filtres en query string.

## 6. Avis / réputation, signalement, modération admin

- Après échange `terminé` : avis 1–5 + commentaire (1 par échange, modifiable 7 jours,
  pas de suppression unilatérale) ; note moyenne + badge « échangeur vérifié » (≥3).
- Signalement (spam, vente, contenu inapproprié, no-show répété) → file de modération.
- Admin : valider/suspendre annonces et comptes, journaliser les actions, tableau de
  bord (annonces actives, signalements ouverts, nouveaux inscrits) ; réutiliser le
  socle admin V1 (rôles, activer/désactiver déjà en place).

## 7. Vie privée, anti-spam, RGPD

- **Jamais d'adresse exacte publique** : zone (commune/rayon) + échange du lieu précis
  uniquement après acceptation, dans le fil privé.
- Emails masqués (formulaire de contact interne, pas d'affichage) ; avatars et photos
  servis sans métadonnées EXIF GPS (le pipeline Pillow les retire au resize).
- Anti-spam : confirmation email, limite d'annonces (ex. 10 actives), limite de
  demandes/jour, honeypot + limitation de débit à l'inscription, bannissement.
- RGPD : registre des traitements, consentement traçé, export des données
  personnelles (profil + annonces + messages), effacement sous 30 jours, mentions
  légales + CGU versionnées, hébergement UE (continuité VPS actuel).

## 8. Règles semences (variétés anciennes, traçabilité)

- Catégorie `semence_ancienne` : variété (nom + origine : région/année de récolte),
  **traçabilité de l'origine** (champs : producteur, année, lot, mode de culture
  — bio/conventionnel), germination indicative si connue.
- Avertissements : usage **amateur et échange non commercial** (contexte UE : pas de
  mise sur le marché de semences non inscrites au catalogue ; l'échange entre
  amateurs de petites quantités est toléré mais doit rester non commercial),
  interdiction des espèces invasives et des semences traitées (case à cocher +
  modération), fiche rappel des bonnes pratiques jointes à chaque annonce.
- Validation : proposer une relecture associative (partenaires grainothèques) en
  étape 2, sans bloquer la V2.

## 9. Schéma de base de données proposé (ajouts, via `migrate.py`)

```sql
-- Profils (étend users V1, colonnes ajoutées, jamais de casse)
-- users += display_name, commune, region, bio, avatar, email_verified,
--          created_at, exchange_count, rating_avg, rating_count

CREATE TABLE listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,            -- don|echange|semence_ancienne|plant|semis|surplus_recolte
    plant_id INTEGER REFERENCES plants(id),
    plant_free TEXT DEFAULT '',    -- si plante hors référentiel
    title TEXT NOT NULL, quantity REAL, unit TEXT DEFAULT '',
    description TEXT DEFAULT '', commune TEXT NOT NULL, region TEXT DEFAULT '',
    available_from TEXT, available_until TEXT,
    status TEXT DEFAULT 'active',  -- active|reserved|done|removed
    views INTEGER DEFAULT 0, created_at TEXT, expires_at TEXT
);
CREATE TABLE listing_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    filename TEXT NOT NULL, position INTEGER DEFAULT 0
);
CREATE TABLE exchange_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    from_user INTEGER NOT NULL REFERENCES users(id),
    to_user INTEGER NOT NULL REFERENCES users(id),
    message TEXT DEFAULT '', slot TEXT DEFAULT '',
    status TEXT DEFAULT 'proposed', -- proposed|accepted|declined|done|cancelled
    created_at TEXT, updated_at TEXT
);
CREATE TABLE request_messages (   -- étape 2
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES exchange_requests(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL, created_at TEXT
);
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER UNIQUE NOT NULL REFERENCES exchange_requests(id),
    author_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
    score INTEGER CHECK (score BETWEEN 1 AND 5),
    comment TEXT DEFAULT '', created_at TEXT
);
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER REFERENCES users(id),
    target_kind TEXT NOT NULL,     -- listing|user|request
    target_id INTEGER NOT NULL, reason TEXT NOT NULL,
    details TEXT DEFAULT '', status TEXT DEFAULT 'open', -- open|closed
    created_at TEXT
);
```

Index : `listings(status, kind, commune)`, FTS5 sur `listings(title, description,
plant_free)`, `exchange_requests(listing_id, status)`.

## 10. Estimation par étapes (ordre de livraison)

| Étape | Contenu | Charge indicative |
|---|---|---|
| V2.1 | Comptes enrichis + profils publics + vérification email | 1–2 sem. |
| V2.2 | Annonces CRUD + photos + recherche/filtres + expiration | 2–3 sem. |
| V2.3 | Demandes d'échange + statuts + notifications email | 1–2 sem. |
| V2.4 | Avis/réputation + signalements + modération admin | 1–2 sem. |
| V2.5 | Messagerie minimale + traçabilité semences + pages légales | 2 sem. |
| V2.6 | Durcissement (débit, abus, perfs, sauvegardes) + recette | 1 sem. |

Pré-requis : rotation des secrets (V1), sauvegardes automatisées testées,
montée en charge évaluée (le VPS actuel ~1,5 Go libres suffit pour V2.1–V2.3 ;
réévaluer ensuite). Chaque étape : migration rétrocompatible + déploiement guidé
`webmaster` + rollback, comme en V1.
