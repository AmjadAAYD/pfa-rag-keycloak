# Note de cadrage — I1 · RAG à droits d’accès avec Keycloak

Brouillon pour la séance 2 · Amjad AAYD et Kenza CHOUNI · Pr. Lalla Amina Charaf

## 1. Objectif

Construire un RAG qui répond à partir de documents que l’utilisateur connecté est autorisé à lire et qui cite ces documents. Comparer le filtrage pendant la recherche vectorielle au filtrage après la recherche sur les fuites, la qualité et la latence.

## 2. Périmètre

Le corpus contient 300 documents fictifs, répartis entre les Ressources humaines, la Finance, l’Informatique et les Opérations. Les trois niveaux proposés sont Commun, Interne au département et Confidentiel. Le RBAC est retenu. La [matrice proposée](../README.md#matrice-proposée-pour-validation-en-binôme) définit les droits au niveau du document.

Le projet comprend Keycloak avec OIDC, les deux stratégies de filtrage, le journal des accès et une interface web simple qui permet de changer d’utilisateur. Le périmètre exclut la synchronisation avec un annuaire réel, les droits au niveau du paragraphe et la création d’un nouveau modèle de droits.

## 3. Architecture

1. Indexer les documents et conserver sur leurs fragments l’identifiant du document et les métadonnées de droits.
2. Authentifier l’utilisateur avec Keycloak et lire les rôles et attributs du jeton OIDC. Appliquer la matrice à partir des rôles.
3. En stratégie A, filtrer par métadonnées pendant la recherche vectorielle. En stratégie B, rechercher sans filtre, puis écarter les documents non autorisés avant de préparer le contexte.
4. Envoyer le contexte autorisé à `qwen3.5:9b` via Ollama et limiter les citations aux documents autorisés. Enregistrer l’utilisateur, la question, les documents utilisés et la décision d’accès dans le journal.

GitHub héberge le dépôt. La base vectorielle, l’orchestration Python et le mode d’installation restent à choisir en binôme. L’installation devra être reproductible via Docker Compose ou un script unique, avec versions et graines fixées. Les secrets et `.env` restent hors du dépôt. Le projet reste à coût nul. Toute action à effet réel est simulée ou soumise à validation humaine.

## 4. Protocole d’évaluation

- Préparer au moins 100 questions par rôle, avec réponses attendues et documents pertinents, dont des questions portant sur des informations auxquelles le rôle ne devrait pas accéder.
- Vérifier qu’aucun fragment non autorisé ne parvient au modèle pour les stratégies A et B. Mesurer le Recall@5 et la fidélité de leurs réponses et les comparer à une référence sans filtre. Choisir la méthode de mesure de la fidélité en binôme.
- Mesurer le surcoût de latence de A et B, à la médiane et au 95e centile. Enregistrer pour chaque exécution la date, la version du code, le modèle et les paramètres. Présenter les résultats dans un tableau comparatif.
- À la soutenance, poser une même question sous deux rôles. Par exemple, pour « Quelle est la priorité de mon département pour le projet Atlas ? », le rôle Informatique doit retrouver la validation de quatre scénarios en environnement de test (`informatique-01-interne`) et le rôle Finance le plafond de dépense de 10 800 MAD (`finance-01-interne`). Ces réponses sont des attentes à vérifier lors de l’évaluation.

## 5. Rôles dans le binôme

Amjad AAYD (`AmjadAAYD`) et Kenza CHOUNI (`kenzachouni`) fixent la répartition du corpus, de l’intégration Keycloak, du RAG et de l’évaluation avant la validation du cadrage. Le dépôt final doit contenir des commits des deux membres.
