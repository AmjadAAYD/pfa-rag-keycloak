# PFA I1 — RAG à droits d’accès avec Keycloak

Projet encadré S9 · IA & Data · EMSI · 2026–2027

## Binôme

- Amjad AAYD (`AmjadAAYD`)
- Kenza CHOUNI (`kenzachouni`)

Encadrement — Pr. Lalla Amina Charaf

## Objectif

Comparer le filtrage des droits pendant la recherche vectorielle (A) et après la récupération des candidats (B). L’application se connecte à Keycloak, recherche dans Qdrant et utilise Ollama pour sélectionner des extraits qui répondent à la question.

## Contrôle d’accès

Le projet retient le RBAC. Keycloak fournit les rôles de l’utilisateur dans le jeton OIDC. Chaque document porte la liste des rôles autorisés à le lire. Les deux stratégies appliquent la même règle d’accès, l’une pendant la recherche vectorielle et l’autre après la recherche, avant l’envoi des fragments à Ollama.

### Matrice RBAC retenue

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

Depuis la racine du dépôt, installer les dépendances avec `python -m pip install -r requirements.lock.txt`. Exécuter `python -m unittest discover -s tests -v` pour vérifier le corpus, les droits, l’API, les deux stratégies de recherche et l’intégrité des artefacts de benchmark. Pour régénérer le fichier à l’identique, utiliser la commande suivante, qui conserve les octets UTF-8 sur Windows.

```powershell
python -c "from pathlib import Path; import subprocess, sys; Path('data/corpus.jsonl').write_bytes(subprocess.check_output([sys.executable, 'generate_corpus.py']))"
```

La [note de cadrage](docs/note-de-cadrage.md) détaille l’architecture retenue, la matrice de droits et le protocole d’évaluation.

## Démarrage sous Windows

Prérequis — Python 3.12, Node.js, Docker Compose et Ollama. Démarrer Docker Desktop et Ollama. Créer `.env` à partir de `.env.example` et choisir les valeurs de `PFA_KEYCLOAK_ADMIN_PASSWORD` et `PFA_DEMO_PASSWORD` avant le premier démarrage de Keycloak.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Renseigner .env avant de lancer les services.
if (-not (Test-Path .venv/Scripts/python.exe)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
npm ci --prefix pfa_rag/web
docker compose up -d
ollama pull bge-m3
ollama pull qwen3.5:9b
.\.venv\Scripts\python.exe -m pfa_rag index
.\.venv\Scripts\python.exe -m uvicorn pfa_rag.api:app --host 127.0.0.1 --port 8000
```

Ouvrir [l’application](http://localhost:8000/) avec `localhost`. La commande `python -m pfa_rag index` et l’API FastAPI utilisent une base Qdrant locale embarquée dans `.pfa-index/`, tandis que le conteneur `qdrant` de `compose.yml` (`127.0.0.1:6333`) est utilisé par `benchmarks/run.py`. Les sept comptes de démonstration définis dans [le royaume Keycloak](infra/keycloak/pfa-rag-realm.json) (`demo-rh`, `demo-finance`, `demo-informatique`, `demo-operations`, `demo-direction`, `demo-multi` qui cumule `finance` et `informatique`, et `demo-sans-role` sans rôle applicatif, renvoyant HTTP 403) utilisent tous la valeur locale de `PFA_DEMO_PASSWORD`. Se déconnecter pour changer de rôle. Le volume Keycloak conserve les comptes après l’import initial.

La question « Quelle est la priorité de mon département pour le projet Atlas ? » renvoie le plafond de **10 800 MAD** sous Finance et la validation de **quatre scénarios** sous Informatique. Pour « Quel est le montant de la réserve budgétaire du projet Atlas ? », la Direction peut obtenir **1 150 MAD** avec la source confidentielle. Finance reçoit un message d’abstention. Essayer A et B et ouvrir les citations depuis l’interface.

## API et journal

- `GET /api/v1/me` renvoie les rôles du jeton d’accès vérifié.
- `POST /api/v1/retrievals` renvoie les sources autorisées dans l’ordre de recherche.
- `POST /api/v1/answers` renvoie une réponse extractive et ses citations, ou une abstention.
- `GET /api/v1/documents/{document_id}` vérifie les droits à chaque ouverture de source.

L’API transmet à Ollama les passages des seuls documents autorisés. Le modèle renvoie des numéros de passages. Le serveur vérifie ces numéros et restitue le texte depuis le corpus. Le journal SQLite local, `.pfa-state/access.sqlite3`, consigne les identifiants des sources envoyées au modèle avant l’appel et les citations après la réponse.

Consulter [l’état des services](http://localhost:8000/readyz) et [le contrat OpenAPI](http://localhost:8000/docs).

## Tests et mesures

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m benchmarks.build_cases
.\.venv\Scripts\python.exe -m benchmarks.run --output .pfa-state/evaluation
.\.venv\Scripts\python.exe -m benchmarks.summarize .pfa-state/evaluation
```

Les 23 tests unitaires — incluant [les vérifications d’artefacts](tests/test_benchmark_artifacts.py) (empreintes SHA-256 de `manifest.json`, reproductibilité des jeux de questions, cohérence des tableaux CSV et absence de fuite sur les méthodes protégées) — sont exécutés automatiquement sur `push` et `pull_request` via [le workflow GitHub Actions](.github/workflows/tests.yml) (`ubuntu-latest`, Python 3.12, `requirements.txt` ; `requirements.lock.txt` fige l’environnement Windows).

Le jeu d’évaluation contient **500 questions**, à raison de 100 par rôle, et le jeu de calibration en contient 20. Le benchmark exécute A, B et une référence sans filtre sur le corpus synthétique. La référence est exécutée par le script local. Le budget par défaut de B est de 20 candidats pour un maximum de 5 sources autorisées. La mesure de sensibilité utilise 5, 10, 20, 50 et 300 candidats sur Qdrant 1.18.3.

Le Recall@5 porte sur le document attendu des questions auxquelles le rôle peut répondre. L’exactitude compare le passage retourné à l’annotation, ou vérifie l’abstention attendue. Le taux de passages appuyés mesure la correspondance exacte avec le document cité. Les latences du pipeline additionnent les temps d’embedding, de recherche et de génération. Les appels HTTP signés de la démonstration sont mesurés séparément.

Pour reproduire la figure et le test de connexion sous Chrome, installer Matplotlib et Playwright dans l’environnement de développement.

```powershell
.\.venv\Scripts\python.exe -m pip install matplotlib==3.10.8 playwright==1.62.0
.\.venv\Scripts\python.exe -m benchmarks.plot .pfa-state/evaluation/candidate_sweep.csv .pfa-state/evaluation/candidate_sweep.svg
.\.venv\Scripts\python.exe -m benchmarks.demo --output .pfa-state/evaluation/atlas_http.csv
```

### Résultats mesurés

| Méthode | Recall@5 autorisé | Exactitude | Contextes non autorisés | Citations non autorisées | Latence p95 du pipeline |
|---|---:|---:|---:|---:|---:|
| A · Filtrage dans Qdrant | 100% | 97.6% | 0 | 0 | 1.78 s |
| B · 20 candidats | 100% | 98.0% | 0 | 0 | 1.72 s |
| Référence hors ligne | 100% | 68.0% | 398 | 172 | 1.77 s |

Les deux méthodes protégées ont retrouvé le document attendu pour les 290 questions répondables. Sur les 210 abstentions attendues, A en a produit 198 et B en a produit 200. Les réponses restantes ont utilisé des passages autorisés hors sujet. Sur ce corpus synthétique, le Recall@5 autorisé de B reste à 100 % dès 5 candidats, mais la part de requêtes recevant cinq sources autorisées (`five_sources_rate`) chute à 20,4 % pour 5 candidats et 70,4 % pour 20 candidats, contre 100 % pour A.

Le [tableau par rôle](benchmarks/results/summary.csv), les [sorties par question](benchmarks/results/answers.jsonl) et le [manifeste de l’exécution](benchmarks/results/manifest.json) accompagnent ces mesures. Le [balayage des budgets](benchmarks/results/candidate_sweep.csv) est également disponible sous forme de [figure](benchmarks/results/candidate_sweep.svg). Un [contrôle de 30 sorties](benchmarks/results/sample_review.csv) documente un échantillon stratifié par rôle et résultat attendu.

Les [24 appels Atlas signés](benchmarks/results/atlas_http.csv) vérifient les réponses, les citations et le journal dans le navigateur.
