"""Helpers partagés Hinga (V1 modulaire, prépare la V2)."""

import os
import uuid
from werkzeug.utils import secure_filename

MOIS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]

MOIS_FR_ABBR = [
    "Jan", "Fév", "Mar", "Avr", "Mai", "Juin",
    "Juil", "Août", "Sep", "Oct", "Nov", "Déc",
]

# Types de plantes proposés (Lot 2 : liste élargie, compatible avec l'existant)
PLANT_TYPES = [
    "Légume", "Fruit", "Aromatique", "Fleur",
    "Plante médicinale", "Légumineuse", "Racine", "Herbe",
]


def mois_nom(mois: int, abbr: bool = False) -> str:
    """Retourne le nom français du mois (1-12). Hors borne -> chaîne vide."""
    try:
        m = int(mois)
    except (TypeError, ValueError):
        return ""
    if 1 <= m <= 12:
        return (MOIS_FR_ABBR if abbr else MOIS_FR)[m - 1]
    return ""


def month_in_range(mois: int, debut: int, fin: int) -> bool:
    """Vrai si `mois` est dans [debut, fin], en gérant le chevauchement fin d'année.

    Ex: debut=11, fin=2 -> Nov, Déc, Jan, Fév.
    Valeurs invalides -> False.
    """
    try:
        mois, debut, fin = int(mois), int(debut), int(fin)
    except (TypeError, ValueError):
        return False
    if not (1 <= mois <= 12 and 1 <= debut <= 12 and 1 <= fin <= 12):
        return False
    if debut <= fin:
        return debut <= mois <= fin
    return mois >= debut or mois <= fin


def periode_label(debut: int, fin: int) -> str:
    """Libellé français 'Février - Avril', gère Nov -> Fév et mois unique."""
    nom_debut = mois_nom(debut)
    nom_fin = mois_nom(fin)
    if not nom_debut or not nom_fin:
        return ""
    if debut == fin:
        return nom_debut
    return f"{nom_debut} - {nom_fin}"


def plants_for_month(plants, mois: int):
    """Sépare les plantes à semer / récolter pour un mois donné.

    Retourne (à_semis, à_récolter). Chaque plante peut être dans les deux.
    """
    a_semis, a_recolter = [], []
    for p in plants:
        try:
            sow_start = p["sow_start"]
            sow_end = p["sow_end"]
            har_start = p["harvest_start"]
            har_end = p["harvest_end"]
        except (TypeError, KeyError):
            continue
        if month_in_range(mois, sow_start, sow_end):
            a_semis.append(p)
        if month_in_range(mois, har_start, har_end):
            a_recolter.append(p)
    return a_semis, a_recolter


def unique_filename(original: str) -> str:
    """Nom de fichier sûr et unique (garde l'extension, évite les collisions)."""
    base = secure_filename(original or "image")
    _, ext = os.path.splitext(base)
    ext = ext.lower()[:6] or ".jpg"
    return f"{uuid.uuid4().hex}{ext}"
