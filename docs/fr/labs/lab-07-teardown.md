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
./scripts/run-lab-workflow.ps1 -Mode teardown-plan
```

Le script cible la génération active, ouvre la page de l'exécution pour l'approbation (**Review deployments** > **lab** > **Approve and deploy**), attend le résultat et affiche le plan tiré du journal de la tâche. La commande brute équivalente est :

```powershell
gh workflow run teardown.yml -f confirm_resource_group=<groupe-de-ressources> -f generation=<generation>
```

Résultat attendu : la tâche charge l'enregistrement de manifeste valide le plus récent pour la génération, vérifie son empreinte et liste les cibles exactes prévues en distinguant les ressources actives des ressources supprimées de manière réversible. Rien n'est supprimé.

```text
cleanup: target microsoft.cognitiveservices/accounts/deployments chat: would_delete
cleanup: target microsoft.apimanagement/service apim-aigov-lab-g05-001-<suffixe>: would_delete
...
cleanup: status=dry_run action=dry_run active=7 failures=0 tombstones=0 exposure=continuing
```

Une incohérence de locataire, d'abonnement ou de groupe de ressources, une ressource inattendue, une propriété ambiguë ou un verrou arrête l'exécution. Les verrous ne sont jamais retirés automatiquement.

### Exercice 7.2 (pratique) : Exécuter le démantèlement

Exécutez d'abord le nettoyage interactif de l'[exercice 7.5](#exercice-75--nettoyer-les-artefacts-des-carnets-interactifs) si vous voulez le voir fonctionner; le démantèlement supprime l'instance APIM dans tous les cas.

```powershell
./scripts/run-lab-workflow.ps1 -Mode teardown
```

La commande brute équivalente est :

```powershell
gh workflow run teardown.yml -f confirm_resource_group=<groupe-de-ressources> -f generation=<generation> -f execute=true
```

Résultat attendu : les déploiements de modèle sont supprimés en premier pour libérer le quota, puis les autres ressources détenues dans l'ordre des dépendances. Le groupe de ressources du laboratoire, vide, le groupe de ressources d'identité avec l'identité attribuée par l'utilisateur d'APIM et les enregistrements de manifeste sont conservés. Ensuite, le script liste les générations, où celle qui a été démantelée affiche `torn down`, et `./scripts/sync-lab-env.ps1` indique `No active generation` jusqu'au prochain déploiement.

Chaque cible est traitée indépendamment avec un nombre borné de nouvelles tentatives. Un `404` confirmé signifie que la ressource est absente; un `403`, un délai dépassé ou un échec de découverte est une erreur, et non une réussite.

### Exercice 7.3 : Lire le rapport résiduel

La tâche de démantèlement écrit le rapport résiduel dans `outputs/residual/<session_id>/report.json` sur l'exécuteur et journalise une ligne par cible, une par ressource supprimée de manière réversible et un résumé. `run-lab-workflow.ps1` affiche ces lignes; pour les afficher de nouveau pour n'importe quelle exécution de démantèlement :

```powershell
gh run view <id-execution> --log | Select-String 'cleanup: '
```

```text
cleanup: target microsoft.apimanagement/service apim-aigov-lab-g05-001-<suffixe>: deleted
cleanup: tombstone apim apim-aigov-lab-g05-001-<suffixe> scheduled purge 2026-10-05T...
cleanup: status=clean action=deleted active=0 failures=0 tombstones=4 exposure=none_known
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

### Exercice 7.7 : Mettre le laboratoire hors service (administration seulement)

Le démontage conserve les groupes de ressources vides et l'identité afin que la session suivante puisse déployer sans nouveaux droits d'administration. Pour retirer complètement le laboratoire, une personne administratrice exécute l'inverse de l'amorçage depuis un terminal interactif, après un démontage exécuté :

```powershell
./scripts/decommission-lab.ps1 -SubscriptionId <subscription-id>
./scripts/decommission-lab.ps1 -SubscriptionId <subscription-id> -Execute
```

Résultat attendu : l'exécution à blanc liste les deux groupes de ressources, les enregistrements de manifeste à exporter et les ressources supprimées de manière réversible restantes. Avec `-Execute`, le script exporte les enregistrements de manifeste dans `outputs/decommission/<timestamp>/`, puis supprime le groupe de ressources du laboratoire (avec ses attributions de rôles) et le groupe de ressources d'identité (avec l'identité attribuée par l'utilisateur d'APIM). Utilisez `-KeepIdentity` pour conserver l'identité. Le script refuse un groupe qui n'a pas l'étiquette de propriété de l'amorçage, qui porte un verrou ou qui contient autre chose que ce que l'amorçage a créé, et il refuse de s'exécuter dans GitHub Actions.

La purge lit les enregistrements de manifeste du groupe de ressources du laboratoire; exécutez donc toute purge nécessaire d'abord. Sinon, les ressources supprimées de manière réversible expirent d'elles-mêmes. Les inscriptions d'applications, les rôles personnalisés ainsi que l'environnement et les variables GitHub demeurent. Exécutez de nouveau `scripts/bootstrap-lab.ps1 -Execute` pour rétablir le laboratoire, puis lancez la session suivante avec une nouvelle valeur `AIGOV_GENERATION`.

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
