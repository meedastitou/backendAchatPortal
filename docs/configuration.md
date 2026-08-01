# Configuration Backend

## Variables d'environnement

Le backend utilise **pydantic-settings** pour gérer la configuration. Toutes les variables sont définies dans le fichier `.env` à la racine du dossier `backend/`.

### Fichier .env

```bash
# Application
APP_NAME=Flux Achat Portal API
APP_VERSION=1.0.0
DEBUG=True

# Base de données MySQL
DB_HOST=192.168.1.211
DB_PORT=3306
DB_NAME=flux_achat_portal
DB_USER=root
DB_PASSWORD=root123

# JWT Authentication
SECRET_KEY=votre-cle-secrete-tres-longue-et-complexe-a-changer
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480

# CORS - Origins autorisées
CORS_ORIGINS=["http://localhost:4200","http://localhost:3000"]

# RPA Service URL
RPA_API_URL=http://localhost:8001/api/bonne-commande/data
```

## Comment ça fonctionne

### Priorité des valeurs

1. **Variable dans `.env`** → Utilisée en priorité
2. **Valeur par défaut dans `config.py`** → Fallback si absente du `.env`

### Exemple

```python
# Dans config.py
RPA_API_URL: str = "http://localhost:8001/api/bonne-commande/data"
```

- Si `.env` contient `RPA_API_URL=http://production-server:8001/api` → cette valeur est utilisée
- Si `.env` ne contient pas `RPA_API_URL` → la valeur par défaut est utilisée

### Utilisation dans le code

```python
# Méthode 1 : Import direct
from app.config import RPA_API_URL
print(RPA_API_URL)

# Méthode 2 : Via l'objet settings
from app.config import settings
print(settings.RPA_API_URL)
print(settings.DB_HOST)
```

## Variables disponibles

| Variable | Type | Description | Défaut |
|----------|------|-------------|--------|
| `APP_NAME` | str | Nom de l'application | Flux Achat Portal API |
| `APP_VERSION` | str | Version | 1.0.0 |
| `DEBUG` | bool | Mode debug | True |
| `DB_HOST` | str | Hôte MySQL | localhost |
| `DB_PORT` | int | Port MySQL | 3306 |
| `DB_NAME` | str | Nom de la base | flux_achat_portal |
| `DB_USER` | str | Utilisateur MySQL | root |
| `DB_PASSWORD` | str | Mot de passe MySQL | (vide) |
| `SECRET_KEY` | str | Clé secrète JWT | (à changer) |
| `ALGORITHM` | str | Algorithme JWT | HS256 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | Durée token (minutes) | 480 (8h) |
| `CORS_ORIGINS` | list | Origins autorisées | localhost:4200, 3000 |
| `RPA_API_URL` | str | URL du service RPA | localhost:8001 |

## Notes importantes

- **Redémarrage requis** : Après modification du `.env`, redémarrer l'application FastAPI
- **Cache** : Les settings sont mis en cache avec `@lru_cache()` pour la performance
- **Sécurité** : Ne jamais commiter le fichier `.env` dans Git (ajouter dans `.gitignore`)
