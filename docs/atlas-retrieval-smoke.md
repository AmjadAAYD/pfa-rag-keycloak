# Vérification Atlas avec Ollama

Recherche exacte sur les 300 documents synthétiques dans Qdrant local. Les commandes ont évalué les résultats de recherche autorisés. Les rôles ont été fournis à la ligne de commande.

- Modèle `bge-m3:latest`, dimensions `1024`.
- Digest du modèle `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`.
- SHA-256 du corpus `b3e348b928863824ec78748aea2e03d6f8867645f8c87ea7ca7406f41f7acc75`.
- Entrée d’embedding `title-newline-text-v1`, similarité cosinus et cinq résultats visés.

## Questions

- Priorité — « Quelle est la priorité de mon département pour le projet Atlas ? »
- Réserve — « Quel est le montant de la réserve budgétaire du projet Atlas ? »

## Résultats

| Cas | Candidats B | Rang attendu A / B | Résultats A / B | Candidats B écartés |
|---|---:|---:|---:|---:|
| Priorité · Finance | 20 | 1 / 1 | 5 / 5 | 12 |
| Priorité · Informatique | 20 | 1 / 1 | 5 / 5 | 12 |
| Priorité · Direction | 20 | — | 5 / 5 | 0 |
| Réserve · Finance | 20 | — | 5 / 3 | 17 |
| Réserve · Direction | 20 | 1 / 1 | 5 / 5 | 0 |
| Priorité · Informatique, budget réduit | 5 | 1 / 1 | 5 / 2 | 3 |

Les deux stratégies ont placé `finance-01-interne` et `informatique-01-interne` au premier rang pour leurs rôles respectifs. Pour la réserve, `finance-01-confidentiel` est arrivé au premier rang pour Direction. Finance a reçu cinq résultats autorisés avec A et trois avec B. Le document confidentiel est absent des deux listes Finance.

Sur la priorité Informatique, réduire le budget B de vingt à cinq candidats réduit le nombre de sources renvoyées de cinq à deux. La source attendue reste au premier rang.

## Sources classées

### Priorité · Finance

- A — `finance-01-interne`, `operations-01-commun`, `informatique-01-commun`, `finance-01-commun`, `rh-01-commun`
- B — `finance-01-interne`, `operations-01-commun`, `informatique-01-commun`, `finance-01-commun`, `rh-01-commun`

### Priorité · Informatique

- A — `informatique-01-interne`, `operations-01-commun`, `informatique-01-commun`, `finance-01-commun`, `rh-01-commun`
- B — `informatique-01-interne`, `operations-01-commun`, `informatique-01-commun`, `finance-01-commun`, `rh-01-commun`

### Priorité · Direction

- A — `rh-01-interne`, `informatique-01-interne`, `finance-01-interne`, `operations-01-interne`, `operations-01-commun`
- B — `rh-01-interne`, `informatique-01-interne`, `finance-01-interne`, `operations-01-interne`, `operations-01-commun`

### Réserve · Finance

- A — `finance-01-interne`, `finance-01-commun`, `operations-01-commun`, `rh-01-commun`, `informatique-01-commun`
- B — `finance-01-interne`, `finance-01-commun`, `operations-01-commun`

### Réserve · Direction

- A — `finance-01-confidentiel`, `finance-01-interne`, `operations-01-confidentiel`, `rh-01-confidentiel`, `finance-25-confidentiel`
- B — `finance-01-confidentiel`, `finance-01-interne`, `operations-01-confidentiel`, `rh-01-confidentiel`, `finance-25-confidentiel`

### Priorité · Informatique, budget réduit

- A — `informatique-01-interne`, `operations-01-commun`, `informatique-01-commun`, `finance-01-commun`, `rh-01-commun`
- B — `informatique-01-interne`, `operations-01-commun`
