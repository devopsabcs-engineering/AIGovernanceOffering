---
permalink: /fr/labs/lab-07-teardown
lang: fr
title: "Atelier 07 - Démantèlement et exposition résiduelle aux coûts"
description: "Retirer uniquement les ressources détenues par une session, en commençant par une exécution à blanc, puis lire le rapport résiduel des ressources actives, des ressources supprimées de manière réversible, des échecs et de l'exposition continue."
nav_order: 17
---

**[English version]({{ "/labs/lab-07-teardown" | relative_url }})**

> [!IMPORTANT]
> Utilisez uniquement des invites synthétiques. La journalisation des messages LLM reste désactivée sur chaque API : le laboratoire n'enregistre jamais les invites ni les réponses dans la télémétrie; seuls les nombres de jetons et des dimensions bornées quittent la passerelle. Les images de session apparaissent sur ce site seulement après qu'une personne responsable a examiné les preuves expurgées.

## Aperçu

{% assign prerequisite_url = "/fr/labs/lab-00-environment" | relative_url %}

| Élément | Valeur |
| --- | --- |
| **Durée** | 30 minutes, plus le temps d'approbation et de suppression |
| **Niveau** | Intermédiaire |
| **Prérequis** | [Atelier 00]({{ prerequisite_url }}) terminé et droits de révision sur l'environnement GitHub `lab` |

Deux chemins suppriment des ressources. Dans `lab-session.yml`, `cleanup --auto` applique la règle de nettoyage du mode aux ressources consignées dans le manifeste propre à la session en cours. Le flux de travail manuel `teardown.yml` est le seul autre chemin. Les deux valident le locataire, l'abonnement, le groupe de ressources et la propriété inscrite au manifeste, et les deux refusent les ressources inattendues et les verrous de ressources au lieu d'élargir leur portée.

> [!CAUTION]
> Le démantèlement s'exécute à blanc par défaut; la suppression exige `execute=true` et une confirmation saisie du groupe de ressources. Une suppression ordinaire laisse des ressources supprimées de manière réversible : APIM et Cognitive Services restent récupérables pendant 48 heures et l'espace de travail Log Analytics pendant 14 jours; les noms restent donc réservés et l'exposition est signalée plutôt que présumée nulle. La purge est irréversible et réservée à une personne. Aucun flux de travail ne purge jamais.

## Objectifs d'apprentissage

À la fin de cet atelier, vous serez capable de :

* Nommer les deux chemins de suppression et la portée que chacun peut toucher
* Lire un plan d'exécution à blanc qui distingue les ressources actives des ressources récupérables
* Exécuter un démantèlement validé par la propriété qui conserve le groupe de ressources et les ressources créées par l'amorçage
* Interpréter le rapport résiduel et ses conditions d'échec
* Expliquer pourquoi la purge est une opération distincte réservée à une personne

## Exercices

### Exercice 7.1 (pratique) : Lancer un démantèlement à blanc

```powershell
gh workflow run teardown.yml -f confirm_resource_group=<groupe-de-ressources> -f generation=<generation>
```

Résultat attendu : après l'approbation de l'environnement, la tâche charge l'enregistrement de manifeste valide le plus récent pour la génération, vérifie son empreinte et liste les cibles exactes prévues en distinguant les ressources actives des ressources supprimées de manière réversible. Rien n'est supprimé.

Une incohérence de locataire, d'abonnement ou de groupe de ressources, une ressource inattendue, une propriété ambiguë ou un verrou arrête l'exécution. Les verrous ne sont jamais retirés automatiquement.

### Exercice 7.2 (pratique) : Exécuter le démantèlement

```powershell
gh workflow run teardown.yml -f confirm_resource_group=<groupe-de-ressources> -f generation=<generation> -f execute=true
```

Résultat attendu : les déploiements de modèle sont supprimés en premier pour libérer le quota, puis les autres ressources détenues dans l'ordre des dépendances. Le groupe de ressources du laboratoire, vide, le groupe de ressources d'identité avec l'identité attribuée par l'utilisateur d'APIM et les enregistrements de manifeste sont conservés.

Chaque cible est traitée indépendamment avec un nombre borné de nouvelles tentatives. Un `404` confirmé signifie que la ressource est absente; un `403`, un délai dépassé ou un échec de découverte est une erreur, et non une réussite.

### Exercice 7.3 : Lire le rapport résiduel

```powershell
Get-Content outputs/residual/<session_id>/report.json
```

Résultat attendu : le rapport liste les ressources actives, les ressources supprimées de manière réversible, les actions en échec, l'état de libération du quota et l'exposition continue connue ou inconnue. Les ressources détenues attendues en suppression réversible sont listées séparément et ne font pas échouer l'exécution; toute ressource détenue encore active, toute ressource inattendue ou toute suppression en échec produit un code de sortie d'échec.

Un groupe de ressources absent ou une suppression demandée ne prouve pas une dépense nulle. Le rapport résiduel et l'état de chaque fournisseur déterminent l'exposition restante.

### Exercice 7.4 : Comprendre la purge réservée à une personne

```powershell
python scripts/lab_session.py purge --help
```

Résultat attendu : l'aide décrit `purge --execute`, qui liste les ressources exactes supprimées de manière réversible consignées dans le manifeste, exige la confirmation saisie de chaque nom et refuse tout ce qui n'est pas inventorié.

Seule une personne opératrice approuvée lance la purge, et seulement lorsqu'un nom doit être réutilisé avant la fin de sa période de récupération. Ce n'est jamais une mesure d'économie courante, et elle ne s'exécute jamais dans un flux de travail.

### Exercice 7.5 : Nettoyer les artefacts des carnets interactifs

La dernière section de `notebooks/demo4-resilient-pool.ipynb` propose une cellule facultative et protégée qui retire les API, produits, abonnements, back-ends, valeurs nommées, enregistreurs et diagnostics des démos 1 à 4. Définissez `REMOVE_WORKSHOP_ARTIFACTS = True` seulement après l'atelier.

Résultat attendu : les artefacts de démonstration sont retirés et l'instance APIM demeure. Les sessions automatisées consignent cette cellule comme exclue volontairement, jamais comme un nettoyage terminé.

### Exercice 7.6 : Examiner les preuves de la session

> [!NOTE]
> Preuves en attente d'examen. Les images `lab07-teardown-summary.png` (réussite) ou `lab07-teardown-status.png` (tout autre état) sont produites à partir de l'état du rapport résiduel et n'apparaissent ici qu'après qu'une personne responsable a examiné les preuves expurgées de la session. Un état d'exposition résiduelle est publié sous forme de carte d'état, jamais sous forme d'image de réussite.

## Liste de vérification

* [ ] Une exécution à blanc a listé les cibles exactes avant toute suppression
* [ ] Les déploiements de modèle ont été supprimés avant leurs comptes
* [ ] Le groupe de ressources, l'identité et les enregistrements de manifeste demeurent
* [ ] Le rapport résiduel existe et son code de sortie correspond à son contenu
* [ ] Aucune purge n'a eu lieu sans qu'une personne opératrice approuvée confirme chaque nom

## Vérification des connaissances

* Quelles ressources le démantèlement conserve-t-il volontairement, et pourquoi?
* Pourquoi un `403` pendant la suppression est-il une erreur plutôt qu'une preuve qu'une ressource a disparu?
* Pendant combien de temps les ressources APIM, Cognitive Services et Log Analytics supprimées restent-elles récupérables?
* Pourquoi aucun flux de travail n'a-t-il l'autorité de purger?

## Étapes suivantes

Revenez à l'[aperçu des ateliers]({{ "/fr/labs/" | relative_url }}) ou lancez une nouvelle session à partir de l'[Atelier 00 : Déployer l'environnement du laboratoire]({{ "/fr/labs/lab-00-environment" | relative_url }}).
