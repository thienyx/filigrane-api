# Filigrane API

API REST **Filigrane** : annotations sur le web (sources canoniques, threads, réactions, inbox, recherche), pour extension, site web et serveur MCP. Même logique métier, une seule API sous `/v1`.

Ce dépôt cible **Python 3.11+**, **FastAPI**, **PostgreSQL** (Railway), **Alembic** pour les migrations.

---

## Démarrage rapide (local)

### 1. Prérequis

- Python **3.11** ou **3.12**
- (Plus tard) PostgreSQL 15+ pour les routes qui touchent la base

### 2. Environnement virtuel et dépendances

```bash
cd filigrane-api
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -e ".[dev]"
```

La commande `pip install -e ".[dev]"` suppose un `pyproject.toml` à la racine du dépôt (package installable en mode éditable).

### 3. Variables d’environnement

```bash
cp .env.example .env
```

| Variable | Obligatoire | Rôle |
|----------|-------------|------|
| `FILIGRANE_ENV` | non | `development` par défaut |
| `FILIGRANE_LOG_LEVEL` | non | Niveau de log (`info`, `debug`, …) |
| `FILIGRANE_DATABASE_URL` | pour DB / Alembic | URL async Postgres, ex. `postgresql+asyncpg://…` |
| `FILIGRANE_ADMIN_TOKEN` | schéma interne `/internal/schema` | Bearer ou `x-admin-token` |
| `FILIGRANE_CORS_ORIGINS` | non | CSV d’origines web (`https://…`) |
| `FILIGRANE_CHROME_EXTENSION_IDS` | non | IDs d’extensions (comma), origin `chrome-extension://…` |
| `FILIGRANE_PUBLIC_APP_URL` | magick link redirect | Origin du front (page `/magic`) |
| `FILIGRANE_EMAIL_FROM`, `FILIGRANE_RESEND_API_KEY` | envoi mail prod | Vide = emails loggés en console |
| `FILIGRANE_OPENAPI_ENABLED` | non | `development` défaut oui hors env explicite |

Les clés lues par l’app ont le préfixe **`FILIGRANE_`**.

### 4. Lancer le serveur

Après `pip install -e .`, le package est en général importable sans `PYTHONPATH`.

```bash
uvicorn filigrane_api.main:app --reload
```

Si vous lancez sans installation éditable (rare), ajoutez le dossier `src` au chemin Python, par exemple : `export PYTHONPATH=src`.

- **Santé** : `GET http://127.0.0.1:8000/health` et `GET http://127.0.0.1:8000/health/ready`
- **OpenAPI** : si `FILIGRANE_OPENAPI_ENABLED` (ou défaut dev) : `/openapi.json`, `/docs`
- **Contrat fermé prod** : `GET /internal/schema` avec header `Authorization: Bearer <FILIGRANE_ADMIN_TOKEN>` ou `x-admin-token`

Port par défaut **8000**. Sur Railway, la plateforme injecte souvent **`PORT`** ; le conteneur doit écouter sur cette variable.

---

## Qualité et tests

```bash
ruff check src tests
pytest
```

CI GitHub Actions (si présente) : lint + tests sur push / PR vers `main` ou `master`.

---

## Migrations (Alembic)

Les migrations tournent en **sync** avec **psycopg** ; l’API en runtime peut rester en **asyncpg**. Convertir l’URL si besoin : `postgresql+asyncpg://…` vers `postgresql+psycopg://…` pour la CLI Alembic (souvent géré dans `alembic/env.py`).

```bash
export FILIGRANE_DATABASE_URL=postgresql+asyncpg://…
alembic upgrade head
```

Chaque changement de schéma doit avoir **une migration dédiée** dans `alembic/versions/`.

---

## Docker (déploiement type Railway)

Si un `Dockerfile` est présent à la racine :

```bash
docker build -t filigrane-api .
docker run --rm -p 8000:8000 -e PORT=8000 filigrane-api
```

Le `PYTHONPATH` doit inclure `src` pour que `filigrane_api` soit importable.

---

## Structure du code (cible)

```
filigrane-api/
├── src/filigrane_api/     # Application FastAPI (routes, services, modèles)
├── tests/                 # pytest + httpx (ASGI)
├── alembic/               # Migrations
├── alembic.ini
├── pyproject.toml
├── Dockerfile             # optionnel
└── .env.example
```

---

## Grain de données fermé (~10 membres)

Après migrations :

```bash
export PYTHONPATH=src FILIGRANE_DATABASE_URL=postgresql+asyncpg://…
python -m filigrane_api.scripts.bootstrap_seed
```

---

## Spécification produit

Le détail fonctionnel (entités, endpoints `/v1`, perf, MCP, canonicalisation des URLs) vit dans le **brief technique Filigrane v1.1** (document produit, hors de ce README). Implémenter dans l’ordre des phases du brief (bootstrap, auth, sources, annotations, etc.).

---

## Dépannage

| Symptôme | Piste |
|----------|--------|
| `ModuleNotFoundError: filigrane_api` | `export PYTHONPATH=src` ou réinstaller avec `pip install -e .` depuis la racine |
| Alembic ne trouve pas la DB | `FILIGRANE_DATABASE_URL` défini dans l’environnement du shell qui lance `alembic` |
| Port déjà pris | `uvicorn … --port 8001` ou variable `PORT` sur l’hôte |

---

## Licence

À définir selon votre choix de distribution.
