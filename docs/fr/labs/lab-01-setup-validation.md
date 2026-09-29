---
permalink: /fr/labs/lab-01-setup-validation
lang: fr
title: "Atelier 01 - Configuration et validation"
description: "Confirmer l'identité, saisir la configuration et valider l'instance APIM et la ressource Content Safety avec le carnet de configuration, de manière interactive ou sans interaction."
nav_order: 11
---

**[English version]({{ "/labs/lab-01-setup-validation" | relative_url }})**

> [!IMPORTANT]
> Utilisez uniquement des invites synthétiques. La journalisation des messages LLM reste désactivée sur chaque API : le laboratoire n'enregistre jamais les invites ni les réponses dans la télémétrie; seuls les nombres de jetons et des dimensions bornées quittent la passerelle. Les images de session apparaissent sur ce site seulement après qu'une personne responsable a examiné les preuves expurgées.

## Aperçu

{% assign prerequisite_url = "/fr/labs/lab-00-environment" | relative_url %}

| Élément | Valeur |
| --- | --- |
| **Durée** | 20 minutes |
| **Niveau** | Débutant |
| **Prérequis** | Environnement de l'[atelier 00]({{ prerequisite_url }}) ou instance APIM existante, Python 3.10 ou plus récent et Azure CLI |

`notebooks/00-setup-and-validation.ipynb` est le prérequis commun de tous les carnets de démonstration. Il confirme votre identité Azure CLI, saisit le groupe de ressources et le nom de l'instance APIM, vérifie que la passerelle est joignable, indique la SKU et contrôle la ressource Content Safety dont l'atelier 04 a besoin. Il ne crée ni ne modifie aucune ressource Azure.

En mode interactif, le carnet demande les valeurs manquantes et les conserve dans un fichier `.env` local qui n'est jamais versionné. Dans une session automatisée, `scripts/lab_session.py write-env` écrit le fichier `.env` complet à partir des sorties du déploiement, et `AIGOV_HEADLESS=1` transforme chaque invite potentielle en erreur qui nomme la clé manquante.

## Objectifs d'apprentissage

À la fin de cet atelier, vous serez capable de :

* Confirmer l'identité Azure connectée et l'abonnement sans exposer d'informations d'identification
* Expliquer la priorité de configuration entre les variables d'environnement, le fichier `.env` et les invites interactives
* Valider que la passerelle APIM est joignable et prend en charge les stratégies utilisées par les ateliers
* Expliquer pourquoi le mode sans interaction échoue au lieu de poser une question
* Lire les résultats d'objectifs structurés qui remplacent les bannières de console comme preuve d'acceptation

## Exercices

### Exercice 1.1 : Préparer l'environnement Python

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
az login
az account show --query "{name:name, id:id}" -o table
```

Résultat attendu : la dernière commande affiche l'abonnement que vous comptez utiliser.

Les carnets utilisent `AzureCliCredential` et se replient sur `DefaultAzureCredential`. Ils n'ouvrent jamais de connexion interactive dans un navigateur.

### Exercice 1.2 (pratique) : Exécuter le carnet de configuration

```powershell
jupyter notebook notebooks/00-setup-and-validation.ipynb
```

Exécutez chaque cellule de haut en bas.

Résultat attendu : le carnet affiche l'URL de la passerelle et la SKU, rend compte de la vérification de la ressource Content Safety et conserve vos réponses dans `.env`. Les secrets, comme les clés d'API et les clés d'abonnement, apparaissent masqués, jamais en entier.

Les démos 1 et 3 ont besoin de `llm-token-limit` et de `llm-content-safety`, que Basic v2 prend en charge. La démo 4 a besoin de pools de back-ends et de disjoncteurs, pris en charge par Basic v2, Standard v2, Premium v2 ainsi que Standard et Premium classiques.

### Exercice 1.3 : Observer le comportement sans interaction

```powershell
$env:AIGOV_HEADLESS = "1"
python -c "from shared.config import load_config; load_config()"
Remove-Item Env:AIGOV_HEADLESS
```

Résultat attendu : avec un fichier `.env` complet, la commande se termine sans poser de question. Si une clé obligatoire manque, elle lève `ConfigError` en nommant la clé. Si une clé existe à la fois dans l'environnement du processus et dans `.env` avec des valeurs différentes, elle échoue et liste uniquement les noms de clés, jamais les valeurs.

`DEMO_RUN` doit provenir uniquement de `.env`; une variable d'environnement `DEMO_RUN` héritée compte donc comme un conflit en mode sans interaction.

### Exercice 1.4 : Lire les résultats d'objectifs

```powershell
Get-ChildItem outputs/results -Recurse -Filter *.json | Select-Object FullName
```

Résultat attendu : le fichier de résultats de configuration consigne `setup.identity`, `setup.endpoints` et `setup.apim_sku`, chacun avec l'état `passed`, `failed` ou `inconclusive` et uniquement des preuves scalaires autorisées.

Les bannières du carnet s'adressent aux personnes. Le fichier de résultats est la preuve d'acceptation que lit le vérificateur de session.

### Exercice 1.5 : Examiner les preuves de la session

> [!NOTE]
> Preuves examinées de la session `36608221120-1` ([exécution du flux de travail](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), produites le 2026-09-29 uniquement à partir de résultats expurgés.

![Résultats des objectifs de l'atelier 01 pour la session examinée]({{ '/assets/images/lab01-setup-validation-summary.png' | relative_url }})

## Liste de vérification

* [ ] `az account show` renvoie l'abonnement prévu
* [ ] Le carnet de configuration a affiché l'URL de la passerelle et la SKU
* [ ] `.env` existe localement et n'est pas suivi par Git
* [ ] Le mode sans interaction échoue sur une clé manquante au lieu de poser une question
* [ ] Les trois objectifs de configuration ont un état consigné

## Vérification des connaissances

* Quelle source l'emporte lorsqu'une même clé est définie dans l'environnement et dans `.env` pendant une exécution interactive?
* Pourquoi le mode sans interaction considère-t-il une valeur `DEMO_RUN` héritée comme un conflit?
* Pourquoi une bannière PASS affichée n'est-elle pas acceptée comme preuve d'achèvement?

## Étapes suivantes

Passez à l'[Atelier 02 : Limites et quotas de jetons]({{ "/fr/labs/lab-02-token-limits" | relative_url }}).
