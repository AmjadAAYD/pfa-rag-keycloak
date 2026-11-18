"""Build the calibration and held-out questions from the published corpus."""

import json
from pathlib import Path

from pfa_rag.corpus import load_corpus
from pfa_rag.generation import document_passages


DEPARTMENTS = ("rh", "finance", "informatique", "operations")
ROLES = (*DEPARTMENTS, "direction")
CORPUS = Path("data/corpus.jsonl")
QUESTIONS = {
    ("rh", "interne"): (
        ("Combien de référents faut-il former avant le démarrage de {p} ?",
         "Quel nombre de référents les RH prévoient-elles de former pour {p} ?"),
        ("Que comprend le parcours de formation des référents du projet {p} ?",
         "Quelles activités sont prévues dans la formation des référents de {p} ?"),
    ),
    ("rh", "commun"): (
        ("À qui s’adresse la présentation du projet {p} ?",
         "Quelles équipes peuvent assister à la présentation de {p} ?"),
        ("Que décrit le support de présentation de {p} ?",
         "Quelles informations trouve-t-on dans le support présenté aux équipes pour {p} ?"),
    ),
    ("rh", "confidentiel"): (
        ("Combien de demi-journées de renfort sont proposées pour le pilote {p} ?",
         "Quel volume de renfort en demi-journées est envisagé pour {p} ?"),
    ),
    ("finance", "interne"): (
        ("Quel plafond la Finance fixe-t-elle pour les dépenses du pilote {p} ?",
         "Sous quel montant doit rester la dépense du pilote {p} ?"),
        ("Quelles catégories le suivi budgétaire du pilote {p} distingue-t-il ?",
         "Quels achats et frais distingue le plan budgétaire de {p} ?"),
    ),
    ("finance", "commun"): (
        ("À quelle fréquence les dépenses du projet {p} sont-elles regroupées dans un bilan ?",
         "Comment et à quel rythme sont regroupées les dépenses de {p} ?"),
        ("Quand les équipes doivent-elles transmettre leurs justificatifs pour {p} ?",
         "Avant quelle étape faut-il envoyer les justificatifs du projet {p} ?"),
    ),
    ("finance", "confidentiel"): (
        ("Quel est le montant de la réserve budgétaire proposée pour le projet {p} ?",
         "À combien s’élève la réserve proposée pour {p} ?"),
        ("Quand la Direction décide-t-elle de l’utilisation de la réserve de {p} ?",
         "Qu’examine la Direction avant de décider d’utiliser la réserve de {p} ?"),
    ),
    ("informatique", "interne"): (
        ("Combien de scénarios l’Informatique doit-elle valider en environnement de test pour {p} ?",
         "Quel nombre de scénarios doit être validé avant la mise en service du pilote {p} ?"),
        ("Où l’équipe informatique relève-t-elle les écarts constatés pour {p} ?",
         "Dans quel document technique sont notés les écarts pour {p} ?"),
    ),
    ("informatique", "commun"): (
        ("À quel service les équipes signalent-elles les problèmes rencontrés sur {p} ?",
         "Vers qui se tourner pour signaler un problème sur le projet {p} ?"),
        ("Quelles informations faut-il inclure dans un signalement d’assistance pour {p} ?",
         "Que doit préciser un signalement concernant {p} ?"),
    ),
    ("informatique", "confidentiel"): (
        ("Combien de semaines est-il envisagé de conserver l’ancien outil pendant le pilote {p} ?",
         "Sur quelle durée porte l’arbitrage concernant le maintien de l’ancien outil de {p} ?"),
    ),
    ("operations", "interne"): (
        ("Pendant combien de semaines les Opérations doivent-elles tester la procédure pour {p} ?",
         "Quelle est la durée du test de la procédure du pilote {p} prévue par les Opérations ?"),
        ("Quels éléments l’équipe Opérations examine-t-elle en fin de semaine pour {p} ?",
         "Que vérifient les Opérations chaque fin de semaine pendant le pilote {p} ?"),
    ),
    ("operations", "commun"): (
        ("Avec quel type de groupe démarre le pilote {p} ?",
         "Le pilote {p} commence avec quel groupe de travail ?"),
        ("Que faut-il examiner avant d’étendre la procédure {p} aux autres équipes ?",
         "Quelle étape précède l’extension du pilote {p} à d’autres équipes ?"),
    ),
    ("operations", "confidentiel"): (
        ("Combien de dossiers par semaine le pilote {p} peut-il prendre en charge selon le plafond proposé ?",
         "Quel plafond hebdomadaire de dossiers est proposé pour {p} ?"),
        ("Que doit décider la Direction si le plafond de capacité de {p} est atteint ?",
         "Quel choix la Direction doit-elle faire si {p} atteint son plafond de dossiers ?"),
    ),
}
ABSENT = (
    "Quelle est la date de signature du contrat de {p} ?",
    "Quel est le numéro de la facture du fournisseur de {p} ?",
    "Qui a signé le procès-verbal de recette de {p} ?",
    "À quelle adresse se trouve le siège du fournisseur de {p} ?",
    "Quel est le numéro de marché public attribué au projet {p} ?",
    "Quel jour exact aura lieu la remise des clés de {p} ?",
    "Quel taux de TVA a été appliqué à la facture de {p} ?",
    "Quel prestataire a audité la conformité du projet {p} ?",
    "Quel numéro de téléphone figure sur le contrat de maintenance de {p} ?",
    "Quel est le numéro de série du matériel acquis pour {p} ?",
)


def make_case(corpus, role, number, department, level, fact=0):
    document = corpus[f"{department}-{number:02d}-{level}"]
    phrases = QUESTIONS[department, level][fact]
    question = phrases[number % len(phrases)].format(p=document.project)
    allowed = document.can_read({role})
    return {
        "role": role, "project": document.project, "question": question,
        "category": level if allowed else f"{level}_refuse",
        "expected": "answered" if allowed else "insufficient_evidence",
        "target_id": document.id, "target_text": document_passages(document)[fact + 1],
    }


def absent_case(corpus, role, number, variation):
    project = corpus[f"rh-{number:02d}-commun"].project
    return {
        "role": role, "project": project, "question": ABSENT[variation].format(p=project),
        "category": "absent", "expected": "insufficient_evidence",
        "target_id": None, "target_text": None,
    }


def calibration(corpus, role):
    department = role if role in DEPARTMENTS else "finance"
    return [
        make_case(corpus, role, 1, department, "interne"),
        make_case(corpus, role, 2, "informatique", "commun", 1),
        make_case(corpus, role, 1, "finance", "confidentiel"),
        absent_case(corpus, role, 3, 0),
    ]


def evaluation(corpus, role):
    numbers = range(6, 26)
    rows = []
    if role == "direction":
        for i, number in enumerate(numbers):
            rows.extend([
                make_case(corpus, role, number, DEPARTMENTS[i % 4], "interne"),
                make_case(corpus, role, number, DEPARTMENTS[i % 4], "interne", 1),
                make_case(corpus, role, number, DEPARTMENTS[i % 4], "commun"),
                make_case(corpus, role, number, DEPARTMENTS[i % 4], "confidentiel"),
            ])
            if i < 5:
                rows.extend([
                    make_case(corpus, role, number, DEPARTMENTS[(i + 1) % 4], "interne"),
                    make_case(corpus, role, number, DEPARTMENTS[i % 4], "commun", 1),
                ])
    else:
        outside = [department for department in DEPARTMENTS if department != role]
        for i, number in enumerate(numbers):
            rows.extend([
                make_case(corpus, role, number, role, "interne"),
                make_case(corpus, role, number, DEPARTMENTS[i % 4], "commun", i % 2),
                make_case(corpus, role, number, outside[i % 3], "interne"),
            ])
            if i < 10:
                rows.append(make_case(corpus, role, number, role, "interne", 1))
            if i < 5:
                rows.append(make_case(corpus, role, number, outside[(i + 1) % 3], "interne", 1))
            if i < 15:
                rows.append(make_case(corpus, role, number, DEPARTMENTS[i % 4], "confidentiel"))
    rows.extend(absent_case(corpus, role, number, i) for i, number in enumerate(range(6, 16)))
    return rows


def build():
    corpus = load_corpus(CORPUS)
    for name, make, count in (("calibration", calibration, 4), ("questions", evaluation, 100)):
        rows = []
        for role in ROLES:
            questions = make(corpus, role)
            if len(questions) != count or len({row["question"] for row in questions}) != count:
                raise ValueError(f"Unexpected question count for {role} in {name}")
            rows.extend(
                {"case_id": f"{role}-{i:03}", **row} for i, row in enumerate(questions, start=1)
            )
        yield name, rows


def main():
    for name, rows in build():
        path = Path(__file__).with_name(name + ".jsonl")
        path.write_bytes("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8"))
        print(f"{path.name}: {len(rows)}")


if __name__ == "__main__":
    main()
