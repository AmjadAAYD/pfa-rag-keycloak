"""Écrit le corpus fictif au format JSON Lines, encodé en UTF-8."""

import json
import sys


# Chaque projet est traité par les quatre départements.
PROJECTS = (
    ("Atlas", "centraliser les demandes d’assistance"),
    ("Argan", "réduire les délais de préparation des commandes"),
    ("Mosaïque", "uniformiser les comptes rendus des sites"),
    ("Phare", "ouvrir un espace de formation interne"),
    ("Nacre", "suivre les stocks de consommables"),
    ("Passerelle", "simplifier le transfert des dossiers entre équipes"),
    ("Sillage", "recenser les équipements à entretenir"),
    ("Cèdre", "organiser la réservation des salles"),
    ("Équinoxe", "réviser le calendrier des interventions"),
    ("Boussole", "documenter les procédures d’accueil"),
    ("Oasis", "réduire le gaspillage de fournitures"),
    ("Horizon", "préparer l’ouverture d’un site pilote"),
    ("Rivage", "regrouper les informations de livraison"),
    ("Épure", "simplifier les formulaires de suivi"),
    ("Clairière", "répartir la charge des permanences"),
    ("Élan", "mettre à jour le catalogue des services"),
    ("Tissage", "améliorer les échanges entre les sites"),
    ("Balise", "améliorer le suivi des demandes urgentes"),
    ("Virage", "organiser le remplacement des postes partagés"),
    ("Écho", "recueillir les retours sur les procédures"),
    ("Canopée", "préparer un exercice de continuité d’activité"),
    ("Saphir", "améliorer le suivi des engagements fournisseurs"),
    ("Rosace", "regrouper les guides de prise en main"),
    ("Cadran", "mesurer le temps passé sur les demandes récurrentes"),
    ("Delta", "harmoniser le classement des dossiers clôturés"),
)

DOCUMENT_TYPES = {
    "rh": (
        ("commun", "Information aux équipes",
         "Une présentation du projet est ouverte à toutes les équipes. "
         "Le support décrit les changements de procédures et la façon de demander un accompagnement."),
        ("interne", "Plan de formation",
         "La priorité RH est de former {group} référents avant le démarrage. "
         "Leur parcours comprend une mise en situation et une séance de questions."),
        ("confidentiel", "Arbitrage sur les renforts",
         "L’arbitrage proposé est de réserver {group} demi-journées de renfort "
         "pour l’accompagnement des équipes pendant le pilote."),
    ),
    "finance": (
        ("commun", "Règles de suivi des dépenses",
         "Les dépenses du projet sont regroupées par catégorie dans un bilan mensuel. "
         "Chaque équipe transmet ses justificatifs avant la clôture."),
        ("interne", "Plan budgétaire",
         "La priorité Finance est de maintenir la dépense du pilote sous {budget} MAD. "
         "Le suivi distingue les achats ponctuels et les frais de fonctionnement."),
        ("confidentiel", "Réserve budgétaire",
         "La réserve proposée est de {reserve} MAD. "
         "La Direction décide de son utilisation après examen des écarts du pilote."),
    ),
    "informatique": (
        ("commun", "Guide d’assistance",
         "Les équipes signalent les problèmes du projet au service d’assistance. "
         "Un signalement doit indiquer l’étape concernée et le résultat attendu."),
        ("interne", "Plan technique",
         "La priorité Informatique est de valider {group} scénarios en environnement de test "
         "avant la mise en service du pilote. L’équipe relève les écarts dans le compte rendu technique."),
        ("confidentiel", "Arbitrage technique",
         "La Direction doit décider s’il faut conserver l’ancien outil pendant {weeks} semaines "
         "pour permettre un retour à la procédure précédente pendant le pilote."),
    ),
    "operations": (
        ("commun", "Annonce de déploiement",
         "Le pilote commence par un groupe de travail limité. "
         "Les observations seront examinées avant d’étendre la procédure aux autres équipes."),
        ("interne", "Organisation du pilote",
         "La priorité Opérations est de tester la procédure pendant {weeks} semaines. "
         "L’équipe examine les délais et les reprises de dossiers en fin de semaine."),
        ("confidentiel", "Capacité du pilote",
         "Le plafond proposé est de {capacity} dossiers par semaine. "
         "La Direction doit décider de reporter l’extension si le plafond est atteint."),
    ),
}


def build_corpus():
    all_roles = [*DOCUMENT_TYPES, "direction"]
    for index, (project, objective) in enumerate(PROJECTS, start=1):
        facts = {
            "group": index + 3,
            "budget": 10_000 + 800 * index,
            "reserve": 1_000 + 150 * index,
            "weeks": 2 + index % 5,
            "capacity": 15 + 3 * index,
        }
        for department, types in DOCUMENT_TYPES.items():
            access = {
                "commun": all_roles,
                "interne": [department, "direction"],
                "confidentiel": ["direction"],
            }
            for level, title, paragraph in types:
                yield {
                    "id": f"{department}-{index:02d}-{level}",
                    "project": project,
                    "department": department,
                    "confidentiality": level,
                    "allowed_roles": access[level],
                    "title": f"{project} — {title}",
                    "text": f"Le projet {project} vise à {objective}. {paragraph.format(**facts)}",
                }


if __name__ == "__main__":
    for document in build_corpus():
        line = json.dumps(document, ensure_ascii=False) + "\n"
        sys.stdout.buffer.write(line.encode("utf-8"))
