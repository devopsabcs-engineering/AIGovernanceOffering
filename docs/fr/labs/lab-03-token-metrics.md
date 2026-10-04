---
permalink: /fr/labs/lab-03-token-metrics
lang: fr
title: "Atelier 03 - Métriques de jetons"
description: "Émettre des métriques de jetons d'invite, de réponse et totaux avec des dimensions bornées par un enregistreur à identité managée, puis les rapprocher de l'utilisation rapportée sans capturer de messages."
nav_order: 13
---

**[English version]({{ "/labs/lab-03-token-metrics" | relative_url }})**

> [!IMPORTANT]
> Utilisez uniquement des invites synthétiques. La journalisation des messages LLM reste désactivée sur chaque API : le laboratoire n'enregistre jamais les invites ni les réponses dans la télémétrie; seuls les nombres de jetons et des dimensions bornées quittent la passerelle. Les images de session apparaissent sur ce site seulement après qu'une personne responsable a examiné les preuves expurgées.

## Aperçu

{% assign prerequisite_url = "/fr/labs/lab-02-token-limits" | relative_url %}

| Élément | Valeur |
| --- | --- |
| **Durée** | 40 minutes, délai d'ingestion compris |
| **Niveau** | Intermédiaire |
| **Prérequis** | [Atelier 02]({{ prerequisite_url }}) terminé et valeurs Application Insights présentes dans `.env` |

`notebooks/demo2-token-metrics.ipynb` mesure les jetons que l'atelier 02 a gouvernés. Une stratégie `llm-emit-token-metric` à la portée de l'API publie des métriques de jetons d'invite, de réponse et totaux, ventilées par `API ID`, `Subscription ID` et une valeur `ClientApp` bornée. Concevez les dimensions avant les tableaux de bord : le budget de cardinalité est de cinq dimensions personnalisées, d'environ 100 valeurs par dimension et de 1 000 séries actives.

L'authentification locale d'Application Insights est désactivée; l'enregistreur `demo2-application-insights` du carnet envoie donc les métriques avec les informations d'identification de l'identité managée d'APIM et le rôle Monitoring Metrics Publisher. Un enregistreur qui ne possède qu'une chaîne de connexion échoue de façon visible au lieu de réactiver silencieusement l'authentification locale. L'enregistreur de plateforme `apimlogger`, géré par Bicep, n'est jamais modifié par un carnet.

> [!IMPORTANT]
> Le diagnostic de l'API conserve `metrics: true` et ne capture aucun message de requête ni de réponse LLM. Le carnet relit le diagnostic après la configuration et échoue si une capture de messages apparaît. L'absence de télémétrie n'est jamais considérée comme une preuve de confidentialité ni comme une utilisation nulle.

## Objectifs d'apprentissage

À la fin de cet atelier, vous serez capable de :

* Expliquer pourquoi les dimensions métier comme `ClientApp` doivent rester bornées
* Configurer un enregistreur Application Insights à identité managée et le vérifier par relecture
* Confirmer que les métriques sont activées alors que la capture des messages reste désactivée
* Interroger les métriques de jetons ventilées par `ClientApp` en tenant compte du délai d'ingestion
* Rapprocher les sommes des métriques de l'utilisation rapportée par le modèle

## Exercices

### Exercice 3.1 : Lire la stratégie de métriques

```powershell
Get-Content policies/demo2-emit-token-metric.xml
```

Résultat attendu : un seul élément `llm-emit-token-metric` avec les dimensions `API ID`, `Subscription ID` et `ClientApp`, où `ClientApp` vaut `unknown` par défaut lorsque l'en-tête est absent.

L'assistant client refuse toute valeur `x-client-app` hors de sa liste autorisée (`claims-portal` et `analyst-copilot`); seules deux séries métier peuvent donc apparaître.

### Exercice 3.2 (pratique) : Exécuter les vérifications préalables

Ouvrez `notebooks/demo2-token-metrics.ipynb` et exécutez la section des vérifications préalables.

Résultat attendu : chaque prérequis indique un état. Lors d'une première exécution, seuls un enregistreur absent et un diagnostic absent sont acceptés comme états attendus, et les deux doivent être présents après la configuration.

### Exercice 3.3 (pratique) : Configurer et relire

Exécutez la section de configuration.

Résultat attendu : l'enregistreur, le diagnostic et la stratégie sont appliqués par des appels `PUT` idempotents, et la relecture confirme les informations d'identification à identité managée de l'enregistreur, `metrics: true` et l'absence de capture de messages. Cette étape consigne `demo2.logger_configured` et `demo2.no_message_capture`.

### Exercice 3.4 (pratique) : Générer la répartition prévue

Exécutez les sections de référence et de démonstration.

Résultat attendu : un appel de référence, puis cinq appels en tant que `claims-portal` et trois appels en tant que `analyst-copilot`, chacun dans l'enveloppe de la session.

Avant l'appel de référence, le carnet envoie des appels de préchauffage non notés jusqu'à ce que la nouvelle API, l'abonnement et la stratégie répondent par la passerelle. Un préchauffage réussi est mesuré en tant que `claims-portal`; son utilisation rapportée par le fournisseur est donc incluse dans le rapprochement.

### Exercice 3.5 (pratique) : Interroger et rapprocher

Exécutez les sections de vérification et d'acceptation.

Résultat attendu : deux séries `ClientApp` apparaissent dans la table `customMetrics` d'Application Insights, et les sommes d'invite et de réponse correspondent à l'utilisation rapportée dans la tolérance indiquée. Cette étape consigne `demo2.dimensions_observed` et `demo2.metrics_reconciled`.

Le délai d'ingestion est normal; la requête interroge donc avec un intervalle croissant pendant une durée bornée. Si l'échéance est dépassée, l'objectif n'est pas atteint; un graphique vide ne prouve pas une consommation nulle.

> [!NOTE]
> Pour les réponses en continu, demandez l'utilisation au fournisseur avec `stream_options: {"include_usage": true}` lorsque c'est pris en charge. Un flux interrompu peut produire des comptes incomplets, car l'événement final d'utilisation peut ne jamais arriver. Le flux principal utilise des appels sans diffusion en continu pour que les comptes se rapprochent.

Après la dernière cellule, confirmez les objectifs consignés dans un terminal :

```powershell
./scripts/show-results.ps1 -Notebook demo2-token-metrics
```

```text
notebook            objective                 status
--------            ---------                 ------
demo2-token-metrics demo2.dimensions_observed passed
demo2-token-metrics demo2.logger_configured   passed
demo2-token-metrics demo2.metrics_reconciled  passed
demo2-token-metrics demo2.no_message_capture  passed
```

### Exercice 3.6 : Examiner les preuves de la session

> [!NOTE]
> Preuves examinées de la session `36608221120-1` ([exécution du flux de travail](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), produites le 2026-09-29 uniquement à partir de résultats expurgés.

![Résultats des objectifs de l'atelier 03 pour la session examinée]({{ '/assets/images/lab03-token-metrics-summary.png' | relative_url }})

Cette image provient d'une session automatisée du flux de travail, et non de votre exécution du carnet; vos propres résultats sont le tableau `show-results.ps1` ci-dessus. Pour produire le même tableau et la même image à partir de vos propres exécutions de carnets, exécutez `./scripts/show-results.ps1 -Evidence -OpenPng`; il utilise le même assainisseur et le même moteur de rendu que le flux de travail et écrit dans `outputs/evidence/local/`. Les preuves de session du flux de travail pour cet atelier n'apparaissent dans `./scripts/show-evidence.ps1` qu'après la session `run-existing` de l'atelier 06.

## Liste de vérification

* [ ] L'enregistreur utilise les informations d'identification de l'identité managée, et non une simple chaîne de connexion
* [ ] La relecture du diagnostic montre `metrics: true` et aucune capture de messages
* [ ] Exactement deux séries `ClientApp` sont apparues
* [ ] Les sommes d'invite et de réponse correspondent à l'utilisation rapportée
* [ ] Les quatre objectifs de la démo 2 ont un état consigné

## Vérification des connaissances

* Pourquoi un identifiant d'exécution doit-il rester hors de la dimension `ClientApp`?
* Que se passe-t-il lorsqu'Application Insights désactive l'authentification locale et que l'enregistreur ne possède qu'une chaîne de connexion?
* Pourquoi un graphique de métriques vide ne prouve-t-il pas qu'aucun jeton n'a été consommé?
* Pourquoi `ClientApp` est-il une affirmation de l'appelant plutôt qu'une identité authentifiée?

## Étapes suivantes

Passez à l'[Atelier 04 : Sécurité du contenu]({{ "/fr/labs/lab-04-content-safety" | relative_url }}).
