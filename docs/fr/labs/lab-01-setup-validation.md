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

En mode interactif, le carnet lit un fichier `.env` local qui n'est jamais versionné. `./scripts/sync-lab-env.ps1` écrit ce fichier à partir des sorties de déploiement de la génération actuellement déployée; vous ne tapez donc aucun nom de ressource. Sans atelier déployé, le carnet demande plutôt les valeurs manquantes et les conserve dans `.env`. Dans une session automatisée, `scripts/lab_session.py write-env` écrit le fichier `.env` complet, et `AIGOV_HEADLESS=1` transforme chaque invite potentielle en erreur qui nomme la clé manquante.

## Objectifs d'apprentissage

À la fin de cet atelier, vous serez capable de :

* Confirmer l'identité Azure connectée et l'abonnement sans exposer d'informations d'identification
* Expliquer la priorité de configuration entre les variables d'environnement, le fichier `.env` et les invites interactives
* Valider que la passerelle APIM est joignable et prend en charge les stratégies utilisées par les ateliers
* Expliquer pourquoi le mode sans interaction échoue au lieu de poser une question
* Lire les résultats d'objectifs structurés qui remplacent les bannières de console comme preuve d'acceptation

## Exercices

### Exercice 1.1 : Préparer l'environnement Python

À partir de la racine du dépôt :

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
az login
az account show --query "{name:name, id:id}" -o table
```

Résultat attendu : la dernière commande affiche l'abonnement que vous comptez utiliser.

Les carnets utilisent `AzureCliCredential` et se replient sur `DefaultAzureCredential`. Ils n'ouvrent jamais de connexion interactive dans un navigateur.

### Exercice 1.2 (pratique) : Pointer `.env` vers la génération déployée

```powershell
./scripts/sync-lab-env.ps1
```

Résultat attendu :

```text
Subscription: <votre abonnement>
local-env: wrote 39 keys to .env for generation g05 (secrets not shown)
local-env: APIM apim-aigov-lab-g05-001-<suffixe> at https://apim-aigov-lab-g05-001-<suffixe>.azure-api.net
Cleared from this terminal: AIGOV_GENERATION
Ready: .env and this terminal now target generation g05. Restart Jupyter if it was already running.
```

Le script trouve la génération la plus récente dont l'instance APIM existe, écrit `.env` à partir des sorties de ce déploiement et enregistre le fichier `.env` précédent sous `.env.bak`. Il retire ensuite du terminal courant toute variable qui remplacerait `.env` ou entrerait en conflit avec lui, comme les valeurs `AIGOV_*` chargées à l'atelier 00 ou les valeurs `AIGOV_HEADLESS` et `SESSION_*` d'une session automatisée. Il avertit aussi lorsque la variable de dépôt `AIGOV_GENERATION` désigne une autre génération.

Les terminaux VS Code peuvent aussi démarrer avec les valeurs que contenait `.env` à leur ouverture, car l'extension Python peut charger `.env` dans les nouveaux terminaux. C'est une autre façon dont une génération périmée atteint un carnet, et le script efface aussi ces valeurs.

Exécutez-le de nouveau après chaque déploiement ou démantèlement. S'il indique `No active generation`, déployez-en d'abord une à l'[atelier 00]({{ prerequisite_url }}).

### Exercice 1.3 (pratique) : Exécuter le carnet de configuration

Dans le même terminal :

```powershell
jupyter notebook notebooks/00-setup-and-validation.ipynb
```

Jupyter ouvre le carnet dans votre navigateur. Si le navigateur affiche **File not found** pour un fichier `jpserver-<nombre>-open.html`, sélectionnez plutôt l'un des liens `http://localhost:8888/...?token=...` affichés dans le terminal. Gardez ce terminal ouvert; le fermer arrête le noyau du carnet.

Sélectionnez **Run** > **Run All Cells**. Vous pouvez aussi ouvrir le carnet dans VS Code, choisir l'interpréteur `.venv` comme noyau, puis sélectionner **Run All**.

Résultat attendu : le carnet affiche la génération de l'atelier, l'URL de la passerelle et la SKU, et rend compte de la vérification de la ressource Content Safety. Les secrets, comme les clés d'API et les chaînes de connexion, apparaissent masqués, jamais en entier.

Si la cellule 3 indique que l'instance APIM n'existe pas, `.env` désigne une génération démantelée. Arrêtez Jupyter avec Ctrl+C, exécutez `./scripts/sync-lab-env.ps1`, relancez Jupyter, puis sélectionnez **Kernel** > **Restart Kernel and Run All Cells**.

Les démos 1 et 3 ont besoin de `llm-token-limit` et de `llm-content-safety`, que Basic v2 prend en charge. La démo 4 a besoin de pools de back-ends et de disjoncteurs, pris en charge par Basic v2, Standard v2, Premium v2 ainsi que Standard et Premium classiques.

### Exercice 1.4 : Observer le comportement sans interaction

Ouvrez un deuxième terminal à la racine du dépôt, activez l'environnement, puis exécutez :

```powershell
.venv\Scripts\Activate.ps1
$env:AIGOV_HEADLESS = "1"
python -c "from shared.config import load_config; load_config(); print('headless load_config: OK')"
$env:AIGOV_GENERATION = "g00"
python -c "from shared.config import load_config; load_config()"
Remove-Item Env:AIGOV_GENERATION, Env:AIGOV_HEADLESS
```

Résultat attendu : avec un fichier `.env` complet et un terminal propre, la première commande affiche `headless load_config: OK` sans poser de question. Après que vous avez défini une autre valeur `AIGOV_GENERATION` dans le terminal, la deuxième commande lève `ConfigError: Inherited environment variables conflict with .env in headless mode: AIGOV_GENERATION`. Elle liste uniquement les noms de clés, jamais les valeurs. Si une clé obligatoire manque, le mode sans interaction lève `ConfigError` en nommant la clé.

En mode interactif, une variable du terminal l'emporte silencieusement sur `.env`; c'est ainsi qu'une valeur périmée d'une session antérieure peut diriger un carnet vers les mauvaises ressources. Le mode sans interaction refuse plutôt. Si cette erreur apparaît de façon inattendue, exécutez `./scripts/sync-lab-env.ps1` dans ce terminal.

`DEMO_RUN` doit provenir uniquement de `.env`; une variable d'environnement `DEMO_RUN` héritée compte donc comme un conflit en mode sans interaction.

### Exercice 1.5 : Lire les résultats d'objectifs

```powershell
./scripts/show-results.ps1 -Notebook 00-setup-and-validation
```

```text
notebook                objective       status recorded_at
--------                ---------       ------ -----------
00-setup-and-validation setup.apim_sku  passed 2026-10-03 8:18:36 AM
00-setup-and-validation setup.endpoints passed 2026-10-03 8:18:36 AM
00-setup-and-validation setup.identity  passed 2026-10-03 8:18:28 AM
```

Résultat attendu : le fichier de résultats de configuration consigne `setup.identity`, `setup.endpoints` et `setup.apim_sku`, chacun avec l'état `passed`, `failed` ou `inconclusive` et uniquement des preuves scalaires autorisées. Le script lit le fichier `outputs/results/<exécution>/00-setup-and-validation.json` le plus récent; ouvrez ce fichier pour voir les valeurs des preuves. Sans `-Notebook`, il affiche tous les carnets; c'est ainsi que vous vérifiez les ateliers 02 à 05.

Les bannières du carnet s'adressent aux personnes. Le fichier de résultats est la preuve d'acceptation que lit le vérificateur de session.

### Exercice 1.6 : Examiner les preuves de la session

> [!NOTE]
> Preuves examinées de la session `36608221120-1` ([exécution du flux de travail](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), produites le 2026-09-29 uniquement à partir de résultats expurgés.

![Résultats des objectifs de l'atelier 01 pour la session examinée]({{ '/assets/images/lab01-setup-validation-summary.png' | relative_url }})

Cette image provient d'une session automatisée du flux de travail, et non de votre exécution du carnet; vos propres résultats sont le tableau `show-results.ps1` ci-dessus. Pour voir les mêmes tableaux et images pour vos propres sessions, exécutez `./scripts/show-evidence.ps1 -OpenPng` après la session `run-existing` de l'atelier 06. Une session `deploy-only` indique cet atelier comme `not_run`.

## Liste de vérification

* [ ] `az account show` renvoie l'abonnement prévu
* [ ] `sync-lab-env.ps1` a indiqué la génération déployée
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
