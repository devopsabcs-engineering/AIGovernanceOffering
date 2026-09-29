---
permalink: /fr/labs/lab-04-content-safety
lang: fr
title: "Atelier 04 - Sécurité du contenu"
description: "Appliquer llm-content-safety en entrée et en sortie, exécuter une matrice de tests versionnée et classer chaque résultat comme blocage confirmé, non déclenché, erreur de transport ou non concluant."
nav_order: 14
---

**[English version]({{ "/labs/lab-04-content-safety" | relative_url }})**

> [!IMPORTANT]
> Utilisez uniquement des invites synthétiques. La journalisation des messages LLM reste désactivée sur chaque API : le laboratoire n'enregistre jamais les invites ni les réponses dans la télémétrie; seuls les nombres de jetons et des dimensions bornées quittent la passerelle. Les images de session apparaissent sur ce site seulement après qu'une personne responsable a examiné les preuves expurgées.

## Aperçu

{% assign prerequisite_url = "/fr/labs/lab-03-token-metrics" | relative_url %}

| Élément | Valeur |
| --- | --- |
| **Durée** | 35 minutes |
| **Niveau** | Intermédiaire |
| **Prérequis** | [Atelier 03]({{ prerequisite_url }}) terminé et ressource Azure AI Content Safety configurée dans `.env` |

`notebooks/demo3-content-safety.ipynb` applique une seule stratégie dans deux directions. L'instance entrante de `llm-content-safety` vérifie les invites avec le bouclier d'invite et quatre catégories de préjudice (`Hate`, `SelfHarm`, `Sexual` et `Violence`) sur l'échelle de 0 à 7. L'instance sortante revérifie les réponses avec une fenêtre glissante, car un modèle peut produire du contenu dangereux à partir d'invites anodines.

Le choix d'un seuil est une décision d'affaires qui revient à vos responsables de l'IA responsable, et non une valeur par défaut d'ingénierie. Les valeurs livrées sont `4` pour chaque catégorie.

> [!WARNING]
> Les résultats de sécurité du contenu peuvent être non concluants. Chaque réponse est classée `policy_block_confirmed`, `not_tripped`, `transport_error` ou `inconclusive`. Un blocage ne compte qu'avec une preuve propre à la stratégie, comme le corps d'erreur ou les en-têtes de sécurité du contenu; un `403` sans cette provenance fait échouer l'objectif de sécurité. En diffusion en continu, l'absence du seul événement `[DONE]` est `inconclusive`. Un objectif requis non concluant empêche d'affirmer que tous les ateliers ont réussi, et la base de confidentialité n'est jamais affaiblie pour obtenir un résultat.

## Objectifs d'apprentissage

À la fin de cet atelier, vous serez capable de :

* Expliquer pourquoi des vérifications en entrée seules ne protègent pas les réponses
* Exécuter une matrice de données de test versionnée plutôt que d'improviser des exemples préjudiciables
* Classer chaque résultat selon sa provenance plutôt que selon le seul code d'état
* Interpréter un résultat `not_tripped` et choisir une prochaine étape approuvée
* Expliquer en quoi une intervention en diffusion en continu diffère d'un `403`

## Exercices

### Exercice 4.1 : Lire la stratégie

```powershell
Get-Content policies/demo3-content-safety.xml
```

Résultat attendu : deux éléments `llm-content-safety`. L'élément entrant définit `shield-prompt="true"`, les seuils de catégories tirés de valeurs nommées et `enforce-on-completions="true"`; l'élément sortant définit `window-size` et `window-overlap-size`.

En cas de blocage, la section `<on-error>` renvoie un corps JSON ainsi que les en-têtes `x-content-safety-decision` et `x-content-safety-reason` comme preuves.

### Exercice 4.2 : Revoir la règle des données de test

```powershell
Select-String -Path shared/fixtures.py -Pattern "FIXTURE_SET_VERSION"
```

Résultat attendu : l'ensemble de données de test porte un numéro de version.

Les données livrées pour l'attaque d'invite, le seuil de préjudice et la diffusion en continu sont des substituts modérés et non explicites qui exercent uniquement le mécanisme. Remplacez-les par l'ensemble d'évaluation préapprouvé de votre organisation avant de présenter l'atelier à un public. N'improvisez jamais d'exemples préjudiciables en direct.

### Exercice 4.3 (pratique) : Exécuter la matrice de tests

Ouvrez `notebooks/demo3-content-safety.ipynb` et exécutez la matrice de tests.

Résultat attendu : l'invite d'affaires sûre renvoie `200` et consigne `demo3.safe_prompt`. L'attaque d'invite renvoie `403` avec une provenance de sécurité du contenu et consigne `demo3.prompt_shield_block`. La ligne du seuil de préjudice est présentée pour discussion et peut indiquer **NOT TRIPPED**.

Une ligne **NOT TRIPPED** signifie que la donnée de test a obtenu un score inférieur au seuil. Les réponses approuvées consistent à utiliser une donnée d'évaluation préapprouvée ou à abaisser la valeur `CONTENT_SAFETY_THRESHOLD_*` concernée pour la démonstration seulement.

La session d'atelier automatisée lit les variables de dépôt facultatives `AIGOV_CONTENT_SAFETY_THRESHOLD_*`, fixe chacune à `4` par défaut et les applique comme valeurs nommées des seuils de la démo 3. L'abaissement d'un seuil sert uniquement à la démonstration; les seuils de production demeurent une décision d'affaires en matière d'IA responsable. Un seuil plus bas ne garantit pas une intervention en continu, car le modèle peut maintenir sa réponse sous tous les seuils de catégorie.

### Exercice 4.4 (pratique) : Observer le cas de diffusion en continu

Exécutez la section de diffusion en continu.

Résultat attendu : le carnet vérifie l'état HTTP, exige `text/event-stream` et analyse les événements envoyés par le serveur. Une intervention confirmée exige une preuve propre à la stratégie et consigne `demo3.stream_intervention` comme réussi; un flux qui se termine tôt sans cette preuve est `inconclusive`; un flux qui se termine avec `[DONE]` est `not_tripped`.

L'objectif de diffusion en continu est observationnel : le fait que la réponse du modèle dépasse un seuil de catégorie n'est pas déterministe. Un résultat `inconclusive` est donc signalé comme non vérifié et ne fait pas échouer le verdict de la session. Un résultat `failed`, comme une erreur de transport ou de protocole, le fait toujours échouer.

Lorsque la stratégie sortante détecte une violation dans un flux, APIM cesse de transmettre les événements suivants au lieu de renvoyer `403`.

### Exercice 4.5 : Examiner les preuves de la session

> [!NOTE]
> Preuves examinées de la session `36608221120-1` ([exécution du flux de travail](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), produites le 2026-09-29 uniquement à partir de résultats expurgés. La vérification en continu est observationnelle : `inconclusive (not verified)` signifie que la réponse du modèle est restée sous tous les seuils de catégorie, ce qui ne prouve pas une intervention.

![Résultats des objectifs de l'atelier 04 pour la session examinée]({{ '/assets/images/lab04-content-safety-summary.png' | relative_url }})

## Liste de vérification

* [ ] Les éléments `llm-content-safety` entrant et sortant sont présents
* [ ] La version de l'ensemble de données de test est consignée avec les résultats
* [ ] Chaque ligne de la matrice a une classification, et pas seulement un code d'état
* [ ] Tout `403` compté comme blocage portait une provenance de sécurité du contenu
* [ ] Les trois objectifs de la démo 3 ont un état consigné

## Vérification des connaissances

* Pourquoi l'absence du seul événement `[DONE]` ne prouve-t-elle pas une intervention de sécurité?
* Pourquoi un `403` d'autorisation sans lien fait-il échouer l'objectif de sécurité?
* Qui décide des seuils de catégories, et pourquoi?
* Quelles sont les deux réponses approuvées à un résultat **NOT TRIPPED**?

## Étapes suivantes

Passez à l'[Atelier 05 : Pool de back-ends résilient simulé]({{ "/fr/labs/lab-05-resilient-pool" | relative_url }}).
