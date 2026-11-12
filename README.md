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
