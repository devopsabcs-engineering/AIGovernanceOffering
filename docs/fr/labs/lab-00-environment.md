---
permalink: /fr/labs/lab-00-environment
lang: fr
title: "Atelier 00 - Déployer l'environnement du laboratoire"
description: "Planifier, approuver et déployer l'environnement Basic v2 au moyen d'une session protégée, puis lire le manifeste et les preuves de préparation."
nav_order: 10
---

**[English version]({{ "/labs/lab-00-environment" | relative_url }})**

> [!IMPORTANT]
> Utilisez uniquement des invites synthétiques. La journalisation des messages LLM reste désactivée sur chaque API : le laboratoire n'enregistre jamais les invites ni les réponses dans la télémétrie; seuls les nombres de jetons et des dimensions bornées quittent la passerelle. Les images de session apparaissent sur ce site seulement après qu'une personne responsable a examiné les preuves expurgées.

## Aperçu

| Élément | Valeur |
| --- | --- |
| **Durée** | 45 minutes, plus le temps d'approbation et d'approvisionnement |
| **Niveau** | Intermédiaire |
| **Prérequis** | Amorçage administratif terminé, droits de révision sur l'environnement GitHub `lab` et un ensemble de paramètres de modèle approuvé |

L'environnement est un groupe de ressources déployé à partir de `infra/main.bicep` : une instance APIM Basic v2 avec une identité managée attribuée par l'utilisateur, un déploiement de modèle approuvé, une ressource Azure AI Content Safety, un espace de travail Log Analytics et Application Insights adossé à cet espace de travail. L'API de plateforme `ai-gateway-api` utilise le back-end `ai-gateway-foundry` et expose trois produits d'équipe : `team-retail`, `team-finance` et `team-hr`.

> [!WARNING]
> Basic v2 est un choix conditionnel. Sa passerelle est un point de terminaison public, sans point de terminaison privé entrant ni connectivité privée vers les back-ends; le déploiement exige donc l'approbation explicite de cette exposition publique. Lorsque le réseau privé est requis, choisissez Standard v2 et validez cette topologie séparément. La prise en charge documentée des stratégies ne prouve pas que le laboratoire fonctionne tant que les preuves de la session ne sont pas concluantes.

Une personne administratrice exécute `scripts/bootstrap-lab.ps1` une seule fois, hors de tout flux de travail. Le script crée le groupe de ressources du laboratoire, un groupe de ressources d'identité distinct qui contient l'identité attribuée par l'utilisateur d'APIM, les rôles personnalisés, les deux identités fédérées de déploiement et d'exécution, ainsi que l'environnement protégé `lab`. Les flux de travail n'exécutent jamais l'amorçage et n'écrivent jamais d'attributions de rôles.

## Objectifs d'apprentissage

À la fin de cet atelier, vous serez capable de :

* Expliquer ce que crée l'amorçage administratif et pourquoi les flux de travail ne l'exécutent jamais
* Choisir le mode de `lab-session.yml` qui correspond à l'autorité que vous comptez accorder
* Lire les résultats de la vérification préalable et de l'analyse what-if d'une exécution à blanc avant d'approuver un déploiement payant
* Expliquer comment l'enregistrement de manifeste limite le nettoyage ultérieur aux ressources créées par cette session
* Interpréter le sommaire de préparation et l'enveloppe budgétaire de la session

## Exercices

### Exercice 0.1 : Lire les paramètres approuvés

```powershell
Get-Content infra/main.bicepparam
```

Résultat attendu : `chatModelName`, `chatModelVersion`, `chatDeploymentSku`, `chatDeploymentCapacity`, `aiLocation` et `generation` n'ont aucune valeur par défaut, et `allowGlobalProcessing` vaut `false`.

Aucun modèle, aucune version, aucune SKU, aucune région ni aucune capacité n'est choisi à votre place. L'emplacement canadien des ressources n'approuve pas le traitement d'inférence mondial; la vérification préalable rejette donc les types de déploiement Global, sauf si `allowGlobalProcessing` est défini explicitement.

### Exercice 0.2 : Compiler les modèles sans informations d'identification

```powershell
az bicep build --file infra/main.bicep
az bicep build-params --file infra/main.bicepparam
```

Résultat attendu : `az bicep build` réussit sans informations d'identification et sans avertissement autre que les suppressions documentées. `az bicep build-params` ne réussit qu'une fois définies dans votre interpréteur de commandes toutes les variables `AIGOV_*` énumérées dans `infra/README.md`; d'ici là, la commande échoue avec `BCP427` en nommant la variable manquante, de sorte qu'aucun modèle, aucune région ni aucune identité n'est jamais déduit du contrôle de code source.

Pour charger les valeurs approuvées dans votre interpréteur de commandes, copiez-les à partir des variables de dépôt déjà écrites par l'amorçage et la configuration de l'environnement :

```powershell
gh variable list --json name,value | ConvertFrom-Json |
    Where-Object name -like 'AIGOV_*' |
    ForEach-Object { Set-Item "env:$($_.name)" $_.value }
az bicep build-params --file infra/main.bicepparam
```

Sans accès à GitHub, définissez les variables directement. Le tuple de modèle ci-dessous est le tuple de référence du laboratoire; remplacez les valeurs entre crochets par la sortie de `scripts/bootstrap-lab.ps1` :

```powershell
$env:AIGOV_ENVIRONMENT_NAME          = 'lab'
$env:AIGOV_GENERATION                = '<generation>'
$env:AIGOV_NAME_SUFFIX               = '<name-suffix>'
$env:AIGOV_LOCATION                  = 'canadaeast'
$env:AIGOV_AI_LOCATION               = 'canadaeast'
$env:AIGOV_CONTENT_SAFETY_LOCATION   = 'canadaeast'
$env:AIGOV_PUBLISHER_EMAIL           = '<publisher-email>'
$env:AIGOV_PUBLISHER_NAME            = 'AI Governance Lab'
$env:AIGOV_APIM_IDENTITY_RESOURCE_ID = '/subscriptions/<subscription-id>/resourceGroups/rg-aigov-lab-identity/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-aigov-apim-lab'
$env:AIGOV_APIM_IDENTITY_CLIENT_ID   = '<apim-identity-client-id>'
$env:AIGOV_CHAT_MODEL_NAME           = 'gpt-4.1-mini'
$env:AIGOV_CHAT_MODEL_VERSION        = '2025-04-14'
$env:AIGOV_CHAT_DEPLOYMENT_SKU       = 'Standard'
$env:AIGOV_CHAT_DEPLOYMENT_CAPACITY  = '30'
$env:AIGOV_ALLOW_GLOBAL_PROCESSING   = 'false'
az bicep build-params --file infra/main.bicepparam
```

La compilation prouve que les modèles sont bien formés. Elle ne prouve ni le quota, ni la capacité, ni l'admissibilité du modèle, ni le bon comportement des stratégies.

> [!NOTE]
> Ces commandes laissent des variables `AIGOV_*`, dont `AIGOV_GENERATION`, dans votre terminal. Cela convient pour compiler, mais une valeur `AIGOV_GENERATION` périmée entre ensuite en conflit avec le fichier `.env` qu'utilisent les carnets. L'atelier 01 exécute `./scripts/sync-lab-env.ps1`, qui les efface; ouvrir un nouveau terminal fonctionne aussi.

### Exercice 0.3 : Choisir un mode de session

Chaque mode accorde une autorité différente. Le nettoyage agit toujours uniquement sur les ressources consignées dans le manifeste propre à la session en cours.

| Mode | Déploie | Exécute les carnets et le trafic | Nettoyage |
| --- | --- | --- | --- |
| `dry-run` | Non | Non | Aucun; s'arrête après la vérification préalable et what-if |
| `full-session` | Oui | Oui | En cas de réussite et d'échec, sauf si `keep_environment=true` |
| `deploy-only` | Oui | Non | Seulement si le déploiement ou la préparation échoue |
| `run-existing` | Non; vérifie le manifeste | Oui | Aucun; l'environnement est conservé |
| `report-only` | Non; vérifie le manifeste | Rapport de répartition des coûts seulement | Aucun; l'environnement est conservé |
| `lock-test` | Non | Non | Aucun; répète le verrou du flux de travail sans Azure |

Résultat attendu : vous pouvez nommer les modes qui conservent les ressources en cas d'échec (`run-existing` et `report-only`) et le seul indicateur qui conserve un environnement `full-session` (`keep_environment=true`, qui signale aussi l'exposition continue aux coûts).

### Exercice 0.4 (pratique) : Lancer une exécution à blanc

Chaque déploiement utilise une nouvelle génération, une courte étiquette comme `g05` qui figure dans le nom de chaque ressource. Une session démantelée laisse des noms APIM, Cognitive Services et Log Analytics supprimés de manière réversible; la réutilisation de sa génération fait donc échouer la vérification préalable avec `tombstone_collision`. Affichez les générations existantes et la suivante :

```powershell
az login
python scripts/lab_session.py generations
```

```text
Lab resource group: rg-aigov-lab
generation  state            records  last activity (UTC)
g03         retired                3  2026-09-30T12:45:48
g04         torn down              3  2026-10-01T19:37:16
active generation: none
next unused generation: g05
```

Lancez l'exécution à blanc. Le script choisit la prochaine génération inutilisée, lit le groupe de ressources dans la variable de dépôt `AIGOV_LAB_RESOURCE_GROUP`, ouvre la page de l'exécution et la suit jusqu'à la fin :

```powershell
./scripts/run-lab-workflow.ps1 -Mode dry-run
```

Sur la page de l'exécution qui s'ouvre, sélectionnez **Review deployments**, cochez **lab**, puis sélectionnez **Approve and deploy**. Chaque session attend cette approbation.

Chaque session cible le groupe de ressources existant créé par l'amorçage (`rg-aigov-lab` par défaut). Aucune entrée ne permet de choisir un autre groupe de ressources; l'entrée `confirm_resource_group` du flux de travail est une vérification de sécurité qui doit correspondre exactement à ce nom. Le script la remplit pour vous. La commande brute équivalente est :

```powershell
gh workflow run lab-session.yml -f mode=dry-run -f generation=<generation> -f confirm_resource_group=<groupe-de-ressources>
```

Résultat attendu : après l'approbation, la session se connecte avec l'identité de déploiement, exécute la vérification préalable et what-if, puis s'arrête. Aucun enregistrement de manifeste, aucun déploiement ni aucun nettoyage n'a lieu.

La vérification préalable contrôle l'ensemble de paramètres du modèle, l'inscription des fournisseurs, la disponibilité régionale d'API Management, le quota du modèle, la disponibilité de Content Safety ainsi que les noms APIM, Cognitive Services et Log Analytics supprimés de manière réversible qui entreraient en collision. L'analyse what-if échoue en cas de suppression inattendue ou de modification hors des identifiants de ressources prévus.

### Exercice 0.5 (pratique) : Déployer et lire la préparation

Lancez une session `deploy-only` pour la même génération, puis approuvez-la. Comme `full-session` et `run-existing`, ce mode refuse de démarrer tant que la variable de dépôt `AIGOV_PRICE_SNAPSHOT` ne désigne pas un fichier d'instantané de prix approuvé sous `scripts/prices/`.

```powershell
./scripts/run-lab-workflow.ps1 -Mode deploy-only
```

L'exécution à blanc n'a créé aucun enregistrement de manifeste; le script choisit donc de nouveau la même génération. Le déploiement et la préparation prennent environ 15 minutes. Lorsque l'exécution réussit, le script :

1. Définit la variable de dépôt `AIGOV_GENERATION` sur la nouvelle génération, pour que les exécutions ultérieures qui omettent la génération ciblent la bonne.
2. Exécute `./scripts/sync-lab-env.ps1`, qui écrit votre fichier `.env` local à partir des sorties du déploiement pour l'atelier 01.

Une session `deploy-only` conserve l'environnement; le nettoyage s'exécute seulement si le déploiement ou la préparation échoue. Pour déployer, exécuter tous les carnets et conserver les ressources en une seule session, utilisez plutôt `-Mode full-session -KeepEnvironment`. Les ressources conservées continuent d'engendrer des coûts jusqu'au démantèlement.

Les commandes brutes équivalentes sont :

```powershell
gh workflow run lab-session.yml -f mode=deploy-only -f generation=<generation> -f confirm_resource_group=<groupe-de-ressources>
gh run watch (gh run list --workflow lab-session.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh variable set AIGOV_GENERATION --body <generation>
```

Résultat attendu : la session écrit un enregistrement de manifeste en ajout seulement, nommé `aigov-manifest-<generation>-<session_id>-<hash8>`, avant toute modification, déploie en mode incrémentiel et écrit `outputs/readiness/<session_id>/summary.json` avec un état par vérification.

La préparation interroge la passerelle, la relecture de l'enregistreur et du diagnostic, y compris les dimensions des métriques personnalisées, l'état d'approvisionnement du compte Content Safety, un appel de modèle par l'API de plateforme à `/ai-gateway` ainsi que la première ingestion de métriques. Le premier appel Content Safety par la passerelle a lieu dans l'atelier 04. Un échec de préparation ou de sondage des portées fait sauter chaque carnet, le trafic et la répartition des coûts; les preuves et le nettoyage prévu par le mode s'exécutent quand même. L'enveloppe de session plafonne les tentatives, les jetons réservés, la dépense estimée et la durée, et chaque appel de modèle ou de sécurité effectue sa réservation avant l'envoi.

### Exercice 0.6 : Examiner les preuves de la session

> [!NOTE]
> Preuves examinées de la session `36608221120-1` ([exécution du flux de travail](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), produites le 2026-09-29 uniquement à partir de résultats expurgés.

![Résultats des objectifs de l'atelier 00 pour la session examinée]({{ '/assets/images/lab00-environment-summary.png' | relative_url }})

Pour afficher les mêmes tableaux pour votre propre session, téléchargez ses preuves assainies et affichez-les :

```powershell
# Dernière exécution de lab-session
./scripts/show-evidence.ps1

# Une exécution précise, avec ouverture des fichiers PNG générés
./scripts/show-evidence.ps1 -RunId <id-execution> -OpenPng
```

Le script télécharge les artefacts de l'exécution dans un dossier temporaire avec `gh run download`, lit `evidence.json`, puis affiche les vérifications de préparation et l'état de chaque atelier. Il lit uniquement des preuves assainies et ne requiert aucune information d'identification Azure.

```text
check                    status attempts
-----                    ------ --------
content_safety_account   passed        1
custom_metric_dimensions passed        1
diagnostic               passed        1
gateway                  passed        1
inference                passed        1
logger                   passed        1
metric_ingestion         passed       15
```

Résultat attendu : après une session `deploy-only`, `lab00-environment` est `passed`, les ateliers 01 à 06 sont `not_run` et `lab07-teardown` est `kept`. Les ateliers 01 à 05 exécutent vous-même les carnets sur cet environnement, et l'atelier 06 lance une session `run-existing` pour le trafic et le rapport automatisés.

## Liste de vérification

* [ ] L'ensemble de paramètres du modèle et la génération sont explicites et approuvés
* [ ] Vous avez approuvé l'exposition publique de Basic v2 ou choisi Standard v2 pour le réseau privé
* [ ] Une exécution à blanc s'est terminée et son analyse what-if correspondait aux ressources prévues
* [ ] L'enregistrement de manifeste existe avant toute ressource déployée
* [ ] Chaque vérification de préparation indique un état dans le sommaire

## Vérification des connaissances

* Pourquoi l'amorçage s'exécute-t-il une seule fois par une personne administratrice plutôt que dans un flux de travail?
* Quels modes peuvent supprimer des ressources, et selon quels résultats?
* Qu'est-ce qu'un échec de préparation fait sauter, et qu'est-ce qui s'exécute quand même?
* Pourquoi une commande `az bicep build` réussie ne prouve-t-elle pas que le laboratoire fonctionne?

## Étapes suivantes

Passez à l'[Atelier 01 : Configuration et validation]({{ "/fr/labs/lab-01-setup-validation" | relative_url }}).
