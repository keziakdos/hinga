"""Point d'intégration : analyse de plante à partir d'une photo (Lot 5).

État V1 : STRUCTURE UNIQUEMENT, aucun service externe branché par défaut.
- `is_analysis_enabled()` : vrai uniquement si PLANT_ANALYSIS_ENABLED=1
  ET OPENAI_API_KEY renseignée. À activer à la fin du projet.
- `analyze_image()` : implémentation OpenAI actuelle, isolée ici pour
  pouvoir brancher un autre service (V2) sans toucher aux routes.
- Service désactivé -> la route /maplante enregistre la photo en
  "Analyse en attente" (visible dans l'historique, analysable plus tard).
"""
import base64
import json
import os


def is_analysis_enabled() -> bool:
    return os.environ.get("PLANT_ANALYSIS_ENABLED", "0") == "1" \
        and bool(os.environ.get("OPENAI_API_KEY"))


PROMPT = """
Tu es un expert botaniste. Analyse cette image.
Réponds UNIQUEMENT au format JSON strict avec cette structure :
{
    "name": "Nom commun (Nom latin)",
    "confidence": "XX%",
    "strengths": ["Point fort 1", "Point fort 2"],
    "weaknesses": ["Maladie ou problème 1", "Problème 2"],
    "advice": "Conseil principal pour le soin.",
    "details": {
        "sun": "Exposition idéale (ex: Plein soleil)",
        "water": "Besoins en eau (ex: 2x par semaine)",
        "soil": "Type de sol idéal",
        "hardiness": "Résistance au froid/Climat"
    }
}
Si ce n'est pas une plante, mets "Non identifié" dans le name. En Français.
"""


def analyze_image(image_path: str) -> dict:
    """Analyse l'image via le service externe configuré.

    Retourne le diagnostic (dict). Lève RuntimeError si le service
    n'est pas configuré, ou l'exception du service en cas d'échec.
    """
    if not is_analysis_enabled():
        raise RuntimeError("Service d'analyse non configuré.")
    from openai import OpenAI

    with open(image_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("utf-8")
    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        response_format={"type": "json_object"},
        max_tokens=700,
    )
    return json.loads(response.choices[0].message.content)
