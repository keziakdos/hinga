"""Point d'intégration : analyse de plante à partir d'une photo (Lot 5/6).

Fournisseurs interchangeables, sélection via l'environnement :
- PLANT_ANALYSIS_ENABLED=1 (interrupteur général, défaut 0 = inactif)
- PLANT_ANALYSIS_PROVIDER=gemini|openai (défaut : openai, historique)
- GEMINI_API_KEY (quota gratuit, https://aistudio.google.com/apikey)
- OPENAI_API_KEY (payant, repli)

Acte 1 : aucun appel réseau sans configuration complète.
"""
import json
import os


def active_provider():
    """Retourne 'gemini', 'openai' ou None (service inactif)."""
    if os.environ.get("PLANT_ANALYSIS_ENABLED", "0") != "1":
        return None
    provider = os.environ.get("PLANT_ANALYSIS_PROVIDER", "openai").lower()
    if provider == "gemini" and os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def is_analysis_enabled() -> bool:
    return active_provider() is not None


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


def parse_json_response(text: str) -> dict:
    """Parse la réponse IA, en tolérant les clôtures ```json ... ```."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip().strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return json.loads(text)


def _analyze_gemini(image_path: str) -> dict:
    import google.generativeai as genai
    from PIL import Image

    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-2.0-flash")
    with Image.open(image_path) as img:
        response = model.generate_content([PROMPT, img])
    return parse_json_response(getattr(response, "text", ""))


def _analyze_openai(image_path: str) -> dict:
    import base64
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


def analyze_image(image_path: str) -> dict:
    """Analyse l'image via le fournisseur actif.

    Retourne le diagnostic (dict). Lève RuntimeError si le service
    n'est pas configuré, ou l'exception du service en cas d'échec.
    """
    provider = active_provider()
    if provider == "gemini":
        return _analyze_gemini(image_path)
    if provider == "openai":
        return _analyze_openai(image_path)
    raise RuntimeError("Service d'analyse non configuré.")
