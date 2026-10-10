# Guide admin Hinga (V2)

## Comptes et approbation (Membres)
- **Demandes en attente** : fiche complète (nom, email, zone, profil, cherche/offre,
  date, charte). Approuver / refuser (motif visible par le membre).
- Chaque membre affiche **qui l'a approuvé et quand**.
- Rôles : `membre` (jardine, publie), `moderateur` (modère : masque, classe),
  `admin` (tout + suppressions + membres). **Dernier admin insuppressible**
  (ni suppression, ni suspension, ni rétrogradation).
- Suspendre = bannir temporairement (réactivable). Mot de passe oublié :
  redéfinir via le crayon (l'utilisateur ne peut pas le faire seul, pas d'emails).

## Échanges (Annonces)
- Catégories : créer, sous-catégories, ordre ▲▼, activer/désactiver.
  Suppression impossible si utilisée (désactiver à la place).
- Annonce problématique : **Modération** → masquer (invisible, réversible) ou
  supprimer (admin seul, définitif). Péremption automatique par date.

## Journal et confiance
- Billets : supprimer ; commentaires : masquer. Signalements traités en Modération.
- Avis 1–5 post-échange → badge fiabilité sur les profils.

## Pilotage
- **Impact** : membres, annonces par type, messages, note moyenne, signalements.
- **Journal d'audit** : qui a fait quoi (approbations, rôles, suppressions…).
- **Visites** : `./scripts/analyse_visites.sh /var/log/nginx/hinga.access.log 7`.

## Sécurité
- Compte `admin` d'origine : à renommer/désactiver après création de vos comptes.
- Clés API uniquement dans le `.env` du serveur. Backups testés régulièrement.
- Charte : `docs/CHARTE.md` (affichée à l'inscription).
