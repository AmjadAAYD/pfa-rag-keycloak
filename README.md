# PFA I1 — RAG à droits d’accès avec Keycloak

Projet encadré S9 · IA & Data · EMSI · 2026–2027

## Binôme

- Amjad AAYD (`AmjadAAYD`)
- Kenza CHOUNI (`kenzachouni`)

Encadrement — Pr. Lalla Amina Charaf

## Objectif

Construire un RAG qui répond et cite des documents autorisés pour l’utilisateur connecté via Keycloak (OIDC). Comparer le filtrage des droits pendant la recherche vectorielle et après la recherche, avant l’envoi du contexte au modèle. Mesurer les fuites, le Recall@5, la fidélité et la latence.

## Modèle local

Ollama · `qwen3.5:9b` · identifiant local affiché `56671c2ab938`.

## Premier jalon

Préparer le corpus fictif (au moins 300 documents, 4 départements et 3 niveaux de confidentialité), la matrice de droits, l’architecture et la note de cadrage de deux pages pour la séance 2.

## Contrôle d’accès

Le projet retient le RBAC. Keycloak fournit les rôles de l’utilisateur dans le jeton OIDC. Chaque document porte la liste des rôles autorisés à le lire. Les deux stratégies appliquent la même règle d’accès, l’une pendant la recherche vectorielle et l’autre après la recherche, avant l’envoi des fragments à Ollama.

### Matrice proposée pour validation en binôme

| Rôle | Commun | Interne au département | Confidentiel |
|---|---|---|---|
| `rh` | Tous les départements | Ressources humaines | Aucun |
| `finance` | Tous les départements | Finance | Aucun |
| `informatique` | Tous les départements | Informatique | Aucun |
| `operations` | Tous les départements | Opérations | Aucun |
| `direction` | Tous les départements | Tous les départements | Tous les départements |

La Direction est un rôle transversal. Le corpus est réparti entre les quatre départements du tableau. Les droits s’appliquent au document entier et à chacun de ses fragments.

## Corpus fictif

Le [corpus JSON Lines](data/corpus.jsonl) contient 300 documents sur 25 projets fictifs communs aux quatre départements. Chaque ligne contient un document, son identifiant, son projet, son département, son niveau de confidentialité, ses rôles autorisés, son titre et son texte.

Depuis la racine du dépôt, installer la dépendance de recherche avec `python -m pip install -r requirements.txt`. Exécuter `python -m unittest discover -s tests -v` pour vérifier le corpus, les droits et les deux stratégies de recherche sur les cas Atlas. Pour régénérer le fichier à l’identique, utiliser la commande suivante, qui conserve les octets UTF-8 sur Windows.

```powershell
python -c "from pathlib import Path; import subprocess, sys; Path('data/corpus.jsonl').write_bytes(subprocess.check_output([sys.executable, 'generate_corpus.py']))"
```

Le [brouillon de cadrage](docs/note-de-cadrage.md) reprend l’architecture et le protocole d’évaluation à valider.

## Prototype de recherche

`pre_filter` applique les rôles dans Qdrant. `post_filter` recherche les candidats, puis vérifie leurs droits. Les deux chemins vérifient les autorisations du corpus avant de renvoyer les documents. Les tests utilisent des vecteurs fixes pour reproduire les priorités Finance et Informatique, l’accès Direction et l’effet du nombre de candidats.

### Recherche avec Ollama

Depuis la racine du dépôt, avec Ollama démarré et les dépendances Python installées, indexer le corpus puis lancer la même question sous les deux rôles.

```powershell
ollama pull bge-m3
python -m pfa_rag index
python -m pfa_rag search --role finance "Quelle est la priorité de mon département pour le projet Atlas ?"
python -m pfa_rag search --role informatique "Quelle est la priorité de mon département pour le projet Atlas ?"
```

Chaque commande de recherche affiche les deux stratégies, les sources autorisées et le nombre de candidats écartés. Le budget par défaut est de cinq résultats et de vingt candidats pour le post-filtrage. Utiliser `--candidate-limit 5` sur la commande `search` pour observer un budget plus petit.

L’index Qdrant local est conservé dans `.pfa-index/`. Son manifeste enregistre l’empreinte du corpus, le digest du modèle, la dimension et le nombre de documents. La commande `index` réutilise un index valide et crée un nouvel index après une modification du corpus ou du modèle.

Les [résultats Atlas](docs/atlas-retrieval-smoke.md) donnent les sources et les rangs observés avec le modèle réel.

## Connexion Keycloak et recherche dans le navigateur

Prérequis locaux — Python 3.12, Node.js, Docker Compose et Ollama. Depuis la racine du dépôt, créer `.env` à partir de `.env.example` si nécessaire. Choisir deux mots de passe locaux distincts pour `PFA_KEYCLOAK_ADMIN_PASSWORD` et `PFA_DEMO_PASSWORD` avant le premier démarrage de Keycloak. Le second est partagé par les comptes fictifs du realm de développement.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Renseigner .env avant de démarrer Keycloak.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci --prefix pfa_rag/web
docker compose up -d keycloak
ollama pull bge-m3
.\.venv\Scripts\python.exe -m pfa_rag index
.\.venv\Scripts\python.exe -m uvicorn pfa_rag.api:app --host 127.0.0.1 --port 8000
```

Ouvrir [l’application locale](http://localhost:8000/) avec l’hôte `localhost` prévu dans les redirections OIDC. Se connecter avec `demo-finance`, `demo-informatique` ou `demo-direction` et le mot de passe `PFA_DEMO_PASSWORD`. Sélectionner A ou B, lancer la recherche Atlas et ouvrir une source. Se déconnecter pour changer de compte. Les comptes `demo-rh`, `demo-operations`, `demo-multi` et `demo-sans-role` complètent les tests.

Pour tester la confidentialité, poser « Quel est le montant de la réserve budgétaire du projet Atlas ? » sous Finance puis Direction. Le document `finance-01-confidentiel` est réservé à Direction. Le même contrôle s’applique à l’ouverture d’une source. L’interface affiche les sources ordonnées des deux stratégies de recherche, selon la stratégie sélectionnée.

L’API accepte le jeton d’accès Keycloak sur `GET /api/v1/me`, `POST /api/v1/retrievals` et `GET /api/v1/documents/{document_id}`. Les rôles proviennent du jeton vérifié. Tester `/readyz` pour contrôler Keycloak, Ollama et l’index. Les contrats sont disponibles sur [Swagger UI](http://localhost:8000/docs).

Le volume de développement conserve le realm et ses utilisateurs. Pour modifier un mot de passe après import, utiliser les identifiants du compte dans la console d’administration Keycloak.
