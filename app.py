"""Point d'entrée Hinga (conservé pour gunicorn `app:app` et systemd).

Tout le code vit dans le paquet `hinga/` (blueprints auth/garden/admin).
"""
from hinga import app  # noqa: F401
from hinga.db import init_db

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)
