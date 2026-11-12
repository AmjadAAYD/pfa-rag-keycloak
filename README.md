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

Depuis la racine du dépôt, vérifier la répartition, les droits et la reproductibilité du corpus avec `python -m unittest discover -s tests`. Pour régénérer le fichier à l’identique, utiliser la commande suivante, qui conserve les octets UTF-8 sur Windows.

```powershell
python -c "from pathlib import Path; import subprocess, sys; Path('data/corpus.jsonl').write_bytes(subprocess.check_output([sys.executable, 'generate_corpus.py']))"
```

Le [brouillon de cadrage](docs/note-de-cadrage.md) reprend l’architecture et le protocole d’évaluation à valider.
