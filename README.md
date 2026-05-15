# Filigrane API

API REST **Filigrane** : annotations sur le web (sources canoniques, threads, réactions, inbox, recherche), pour extension, site web et serveur MCP. Même logique métier, une seule API sous `/v1`.

Ce dépôt cible **Python 3.11+**, **FastAPI**, **PostgreSQL** (Railway), **Alembic** pour les migrations.

## Hébergement (production)

L’API déployée répond sur **`https://api.filigrane.link`** (même contrat qu’en local, préfixe **`/v1`**). Le domaine **`filigrane.link`** sert de socle DNS ; le sous-domaine **`api`** pointe vers ce serveur.

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
| `DATABASE_URL` | secours Railway | Si défini sans `FILIGRANE_DATABASE_URL`, l’app et Alembic l’utilisent (converti en `+asyncpg` côté API) |
| `SKIP_DB_MIGRATIONS` | Docker uniquement | `1` ou `true` : ne pas lancer `alembic upgrade head` au démarrage du conteneur |
| `FILIGRANE_ADMIN_TOKEN` | schéma interne `/internal/schema` | Bearer ou `x-admin-token` |
| `FILIGRANE_CORS_ORIGINS` | non | CSV d’origines web (`https://…`) |
| `FILIGRANE_CHROME_EXTENSION_IDS` | non | IDs d’extensions (comma), origin `chrome-extension://…` |
| `FILIGRANE_PUBLIC_APP_URL` | magick link redirect | Origin du front (page `/magic`) |
| `FILIGRANE_EMAIL_FROM`, `FILIGRANE_RESEND_API_KEY` | envoi mail prod | Vide = emails loggés en console |
| `FILIGRANE_OPENAPI_ENABLED` | non | `development` défaut oui hors env explicite |

Les clés lues par l’app ont le préfixe **`FILIGRANE_`**.

### Email transactionnel (Resend)

1. Créer un compte [Resend](https://resend.com), ajouter le domaine **`filigrane.link`** (ou autre) et appliquer les enregistrements DNS demandés jusqu’à ce que le domaine soit **vérifié**.
2. Définir **`FILIGRANE_RESEND_API_KEY`** avec une clé API (header `Authorization: Bearer …` côté [API Emails](https://resend.com/docs/api-reference/emails/send-email)).
3. Définir **`FILIGRANE_EMAIL_FROM`** avec une adresse **sur ce domaine vérifié** (ex. `hello@filigrane.link`). Tant que ce n’est pas fait, la valeur par défaut du code est `noreply@example.com`, que Resend rejette (domaine non vérifié).
4. En production, l’envoi des magic links passe par `ResendEmailSender` dans `src/filigrane_api/services/email_dispatch.py`. Sans clé, `ConsoleEmailSender` journalise le lien (pratique en local).

**Test rapide** (depuis la racine du dépôt, Python 3.11+, dépendances installées) :

```bash
PYTHONPATH=src python3.11 <<'PY'
import asyncio
import httpx
from filigrane_api.core.config import get_settings

async def main() -> None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {s.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": s.email_from,
                "to": ["vous@example.com"],
                "subject": "Test Resend",
                "html": "<p>ok</p>",
            },
        )
    print(r.status_code, r.text)

asyncio.run(main())
PY
```

Les corps HTML restent **minimaux** pour l’instant (un lien pour le magic link). Des **templates** plus soignés (sujets, layout, i18n) pourront remplacer ces chaînes plus tard, sans changer le transport Resend.

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

**Déploiement Docker (Railway)** : au démarrage du conteneur, `docker-entrypoint.sh` exécute `alembic upgrade head`, puis lance uvicorn. Il suffit donc de pousser une migration dans le dépôt et de redéployer. Variables acceptées : **`FILIGRANE_DATABASE_URL`** ou **`DATABASE_URL`** (référence Railway vers Postgres). Pour désactiver les migrations au boot : **`SKIP_DB_MIGRATIONS=1`**.

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

Exemple avec Postgres local et migrations :

```bash
docker run --rm -p 8000:8000 \
  -e PORT=8000 \
  -e DATABASE_URL=postgresql://user:pass@host.docker.internal:5432/filigrane \
  filigrane-api
```

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
├── docker-entrypoint.sh   # migrations puis uvicorn (production Docker)
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
