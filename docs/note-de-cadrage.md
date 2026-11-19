# Note de cadrage — I1 · RAG à droits d’accès avec Keycloak

Projet encadré S9 · IA & Data · EMSI · 2026–2027 · Amjad AAYD (`AmjadAAYD`) et Kenza CHOUNI (`kenzachouni`) · Encadrement : Pr. Lalla Amina Charaf

## 1. Objectif

Construire un système RAG (*Retrieval-Augmented Generation*) qui répond uniquement à partir de documents que l’utilisateur connecté est autorisé à lire et qui cite ces documents de manière vérifiable. Le projet compare expérimentalement deux stratégies d’application du contrôle d’accès — le filtrage pendant la recherche vectorielle (**stratégie A**) et le filtrage après la récupération des candidats (**stratégie B**) — sur la prévention des fuites, la qualité des réponses et la latence, face à une référence hors ligne sans filtre.

## 2. Périmètre et contrôle d’accès

Le [corpus synthétique](../data/corpus.jsonl) contient **300 documents** en français répartis sur **25 projets fictifs**, **4 départements** (`rh`, `finance`, `informatique`, `operations`) et **3 niveaux de confidentialité** (`commun`, `interne`, `confidentiel`), à raison de 25 documents par couple `(département, niveau)`.

Le modèle d’autorisation retenu est le **RBAC** à **5 rôles applicatifs** (`rh`, `finance`, `informatique`, `operations`, `direction`), défini dans la [matrice RBAC retenue](../README.md#matrice-rbac-retenue) :

- **Commun** : lisible par les 5 rôles.
- **Interne au département** : lisible par le rôle du département concerné et par `direction`.
- **Confidentiel** : lisible uniquement par `direction`.

Les droits s’appliquent au **document entier** et sont vérifiés côté serveur à partir des métadonnées de référence du corpus (`data/corpus.jsonl`) à chaque étape : lors de la recherche (`pre_filter` et `post_filter`), avant la préparation du contexte transmis au modèle de langage, et lors de l’ouverture directe d’une source via `GET /api/v1/documents/{document_id}` (qui renvoie HTTP `404` pour un document non autorisé ou inexistant afin d’éviter l’énumération d’identifiants). Le périmètre exclut la synchronisation avec un annuaire d’entreprise réel, les droits au niveau du paragraphe et la conception d’un nouveau modèle de contrôle d’accès.

## 3. Architecture retenue

1. **Identité et authentification (Keycloak 26.8.2)**
   Le royaume `pfa-rag` ([`infra/keycloak/pfa-rag-realm.json`](../infra/keycloak/pfa-rag-realm.json)) authentifie l’interface web (`pfa-web`) via OIDC *Authorization Code* avec PKCE (`S256`). L’API FastAPI vérifie les jetons d’accès `RS256` (émetteur, signature JWKS, durée de vie, `typ=Bearer`, audience `pfa-api`) et lit les rôles applicatifs exclusivement depuis la revendication `resource_access["pfa-api"]["roles"]`. Les rôles inconnus sont ignorés ; un compte sans rôle reconnu reçoit HTTP `403` ; toute tentative de surcharge des rôles dans le corps de requête est rejetée par validation stricte (`HTTP 422`).
2. **Vectorisation et base vectorielle (Ollama `bge-m3` + Qdrant)**
   Les documents sont vectorisés avec `bge-m3:latest` (1024 dimensions, format d’entrée `title-newline-text-v1`) et indexés avec la similarité cosinus en recherche exacte (`exact=True`) dans Qdrant (`1.18.3`).
   - *API et CLI en direct* (`pfa_rag/api.py`, `python -m pfa_rag index`) : utilisent une instance Qdrant locale embarquée sur disque sous `.pfa-index/`, identifiée par l’empreinte SHA-256 du corpus et du digest du modèle Ollama.
   - *Benchmark reproductible* (`benchmarks/run.py`) : utilise le conteneur Docker Qdrant de [`compose.yml`](../compose.yml) sur `127.0.0.1:6333` avec un index de métadonnées `KEYWORD` sur `allowed_roles`.
   En **stratégie A** (`pre_filter`), Qdrant filtre sur `allowed_roles` pendant la recherche et retourne jusqu’à 5 documents. En **stratégie B** (`post_filter`), Qdrant récupère un budget de candidats sans filtre (20 par défaut), puis le serveur écarte les documents non autorisés d’après le corpus et conserve au plus 5 sources.
3. **Génération extractive et journalisation (FastAPI + Ollama `qwen3.5:9b` + SQLite)**
   L’interface web légère (`pfa_rag/web`, `keycloak-js` 26.2.5) permet de changer de compte de démonstration, de basculer entre A et B et de consulter les citations. Le serveur découpe uniquement les documents autorisés en passages numérotés et appelle `qwen3.5:9b` (`temperature=0`, `seed=17`, `num_ctx=2048`, `num_predict=48`, `think=false`) avec un schéma JSON imposant `{"passages":[numéros]}` (0 à 3 indices). Le serveur rejette tout indice hors contexte (`HTTP 502`), restitue le texte exact issu du corpus et renvoie une abstention explicite lorsqu’aucun passage ne répond. Le journal SQLite local (`.pfa-state/access.sqlite3`) enregistre `context_ids` avant l’appel au modèle, puis `citation_ids`, le statut et les latences (`total_ms`, `model_ms`).
4. **Reproductibilité et sécurité des secrets**
   L’environnement est figé via `compose.yml`, `requirements.lock.txt`, `pfa_rag/web/package-lock.json`, une graine fixe (`17`) et les empreintes SHA-256 (`corpus_sha256`, `cases_sha256`, `source_digest`, digests des modèles) consignées dans [`benchmarks/results/manifest.json`](../benchmarks/results/manifest.json). Les secrets et mots de passe locaux restent dans `.env` (exclu par `.gitignore`).

## 4. Protocole et synthèse d’évaluation

- **Jeux de questions** : [`benchmarks/build_cases.py`](../benchmarks/build_cases.py) génère **500 questions** (100 par rôle : **290 répondables** — 165 `interne`, 105 `commun`, 20 `confidentiel` — et **210 abstentions attendues** — 100 `interne_refuse`, 60 `confidentiel_refuse`, 50 `absent`) ainsi que 20 questions de calibration.
- **Critères et mesure de fidélité** :
  - *Sécurité / fuites* : nombre de documents non autorisés présents dans le contexte (`context_leaks`), dans les citations (`citation_leaks`) et divulgations de faits restreints (`restricted_fact_disclosures`).
  - *Qualité et fidélité* : Recall@5 autorisé sur les questions répondables ; fidélité assurée par extraction vérifiée côté serveur (`passage_support_rate` : correspondance exacte des passages retournés avec le texte du document cité) combinée à l’exactitude par rapport aux passages et abstentions attendus (`exact_answer_accuracy`), complétée par une revue manuelle stratifiée de 30 sorties ([`benchmarks/results/sample_review.csv`](../benchmarks/results/sample_review.csv)).
  - *Latence et sensibilité* : médiane (`p50`) et 95e centile (`p95`) de la recherche et du pipeline complet, plus un balayage du budget de candidats de B sur `{5, 10, 20, 50, 300}`.
- **Résultats mesurés** ([`summary.csv`](../benchmarks/results/summary.csv), [`candidate_sweep.csv`](../benchmarks/results/candidate_sweep.csv), [`atlas_http.csv`](../benchmarks/results/atlas_http.csv)) :
  - **Zéro fuite** pour A et B (`0` contexte non autorisé, `0` citation non autorisée, `0` fait restreint divulgué), contre **398** contextes non autorisés, **172** citations non autorisées et **160** divulgations restreintes pour la référence hors ligne sans filtre.
  - **100 % de Recall@5 autorisé** sur tous les bras protégés et sur tous les budgets de B (5 à 300), mais une perte de complétude du contexte en post-filtrage : la proportion de requêtes recevant 5 sources autorisées (`five_sources_rate`) chute pour B à **20,4 %** à 5 candidats et **70,4 %** à 20 candidats (contre **100 %** pour A).
  - **Exactitude globale** de **97,6 %** pour A (198/210 abstentions correctes) et **98,0 %** pour B (200/210 abstentions correctes), contre **68,0 %** sans filtre. Les 12 erreurs de A et 10 erreurs de B sont uniquement des passages autorisés hors sujet sélectionnés sur des abstentions attendues (principalement sur `operations` : 7 pour A, 5 pour B), avec `passage_support_rate = 100 %`.
  - **Latence p95 du pipeline** : **1,78 s** pour A, **1,72 s** pour B (budget 20) et **1,77 s** sans filtre.
  - **Vérification de bout en bout (soutenance)** : les 24 requêtes HTTP signées via Keycloak et Chrome/Playwright sur le projet *Atlas* confirment que Finance retrouve le plafond de **10 800 MAD** (`finance-01-interne`), Informatique les **quatre scénarios** (`informatique-01-interne`), et que seule la Direction accède à la réserve confidentielle de **1 150 MAD** (`finance-01-confidentiel`) tandis que Finance s’abstient.

## 5. Répartition du binôme et suivi

- **Amjad AAYD (`AmjadAAYD`)** : générateur du corpus synthétique, intégration Keycloak OIDC/PKCE, pipeline RAG FastAPI + Qdrant + Ollama, journalisation SQLite, suite d’évaluation automatisée et tests unitaires / Playwright.
- **Kenza CHOUNI (`kenzachouni`)** : co-validation de la matrice RBAC et du cadrage, revue des cas d’évaluation et d’analyse d’erreurs, préparation du support de soutenance et contributions documentaires/techniques associées.
- **Suivi Git avant remise finale** : l’implémentation et les résultats expérimentaux sont actuellement portés par des commits d’`AmjadAAYD` sur la branche `pfa-results` ; avant la soutenance et la remise finale, les branches doivent être consolidées sur `main` et inclure des commits réalisés et poussés par `kenzachouni` afin de satisfaire l’exigence de contribution du binôme.
