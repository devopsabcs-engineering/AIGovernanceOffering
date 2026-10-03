---
permalink: /fr/labs/lab-06-chargeback
lang: fr
title: "Atelier 06 - Répartition estimée des coûts de jetons"
description: "Générer un trafic d'équipe borné sur l'API de plateforme, rapprocher les métriques de jetons d'un manifeste d'utilisation et lire une répartition estimée des coûts de jetons avec sa couverture et ses exclusions."
nav_order: 16
---

**[English version]({{ "/labs/lab-06-chargeback" | relative_url }})**

> [!IMPORTANT]
> Utilisez uniquement des invites synthétiques. La journalisation des messages LLM reste désactivée sur chaque API : le laboratoire n'enregistre jamais les invites ni les réponses dans la télémétrie; seuls les nombres de jetons et des dimensions bornées quittent la passerelle. Les images de session apparaissent sur ce site seulement après qu'une personne responsable a examiné les preuves expurgées.

## Aperçu

{% assign prerequisite_url = "/fr/labs/lab-03-token-metrics" | relative_url %}

| Élément | Valeur |
| --- | --- |
| **Durée** | 30 minutes, délai d'ingestion compris |
| **Niveau** | Avancé |
| **Prérequis** | [Atelier 03]({{ prerequisite_url }}) terminé et environnement de session déployé |

L'API de plateforme `ai-gateway-api`, servie à `/ai-gateway`, expose trois produits d'équipe, `team-retail`, `team-finance` et `team-hr`. Chacun a son propre abonnement limité au produit (`team-retail-sub`, `team-finance-sub` et `team-hr-sub`) et ses propres limites : 3 000, 2 000 et 1 000 jetons par minute, et 30 000, 20 000 et 10 000 jetons par jour. La passerelle déduit l'équipe de l'abonnement authentifié, jamais d'un en-tête fourni par l'appelant. `scripts/generate_traffic.py` envoie une petite charge bornée par équipe, et `scripts/showback_report.py` transforme les métriques de jetons obtenues en répartition estimée des coûts.

> [!WARNING]
> Chaque sortie porte l'étiquette `Estimated model-token showback (USD retail)` avec son intervalle UTC, son instantané de prix, son état de couverture et ses exclusions. Il s'agit d'une estimation aux prix de détail sans mise en cache, et non d'une refacturation facturée. Elle exclut APIM partagé, la journalisation, Content Safety, le réseau, les taxes, les remises et rajustements contractuels, les remises de mise en cache des invites et la tarification du débit provisionné. Une couverture manquante, en double ou sans prix supprime le total, et une télémétrie absente est signalée comme incomplète, jamais comme nulle. Rapprochez les chiffres de Cost Management ou de la facture avant tout usage financier.

## Objectifs d'apprentissage

À la fin de cet atelier, vous serez capable de :

* Expliquer comment l'attribution à une équipe provient de la correspondance des abonnements et pourquoi `ClientApp` reste une affirmation de l'appelant
* Décrire l'enveloppe de trafic bornée et sa fenêtre UTC fixe semi-ouverte
* Rapprocher les sommes des métriques du manifeste d'utilisation des réponses
* Lire l'état de couverture, l'état de rapprochement et les exclusions d'un rapport de répartition des coûts
* Expliquer quels abonnements peuvent contourner les quotas des produits

## Exercices

### Exercice 6.1 : Lire la conception de l'attribution aux équipes

```powershell
Get-Content policies/platform-ai-gateway.xml
Get-Content policies/platform-team-product.xml
```

Résultat attendu : la stratégie de plateforme émet une seule métrique de jetons avec les dimensions `API ID`, `Subscription ID` et `ClientApp`, normalise `ClientApp` selon la liste autorisée `retail-web`, `finance-batch` et `hr-assistant`, en signalant toute autre valeur comme `unknown`, et supprime l'en-tête `Ocp-Apim-Subscription-Key`, le paramètre de requête `subscription-key` et tout en-tête `api-key` avant le transfert. La stratégie de produit d'équipe applique `llm-token-limit` avec une `counter-key` égale à l'identifiant d'abonnement.

### Exercice 6.2 (pratique) : Lancer la session de trafic borné

Le trafic s'exécute dans une session `full-session` ou `run-existing` après la réussite de la préparation et des sondages de portée. Lancez une session `run-existing` sur la génération déployée à l'atelier 00 :

```powershell
./scripts/run-lab-workflow.ps1 -Mode run-existing
```

Approuvez l'exécution sur la page qui s'ouvre. La session réexécute les cinq carnets sans interaction, envoie le trafic des équipes, écrit le rapport de répartition des coûts et ne supprime jamais de ressources. Elle dure environ 15 minutes, puis le script affiche les preuves.

Résultat attendu : chaque atelier de `lab00-environment` à `lab06-chargeback` est `passed`, et `lab07-teardown` est `not_run`. Vous pouvez énoncer les valeurs par défaut du trafic : un processus, 30 tentatives, 128 jetons de sortie au maximum, 10 000 jetons réservés, une échéance de cinq minutes, des appels en série sans diffusion en continu et aucune nouvelle tentative. Les clés sont récupérées en privé et jamais affichées, et chaque appel effectue sa réservation dans l'enveloppe de la session.

Le générateur consigne un manifeste d'utilisation des réponses et une fenêtre UTC fixe semi-ouverte dans `outputs/showback/<session_id>/manifest.json`. Un verrou de flux de travail n'arrête pas le trafic humain; une fenêtre qui contient des appels non comptabilisés est donc rejetée comme contaminée.

### Exercice 6.3 : Lire le rapport de répartition des coûts

Les preuves affichées par le script se terminent par la répartition des coûts. Pour l'afficher de nouveau pour la dernière session :

```powershell
./scripts/show-evidence.ps1
```

```text
Estimated model-token showback (USD retail) | 2026-10-03T09:25:00Z to 2026-10-03T09:27:00Z (half-open UTC)
coverage complete | reconciliation reconciled | snapshot retail-2026-09-29-gpt-4.1-mini-canadaeast

team         prompt_tokens completion_tokens estimated_usd
----         ------------- ----------------- -------------
team-finance           190               155 0.00039204
team-hr                180               221 0.000514976
team-retail            190               237 0.000550792

total estimated_usd 0.001457808 (complete)
```

Résultat attendu : le rapport interroge une seule représentation, la table `customMetrics` d'Application Insights sommée par `valueSum`, limitée au composant, à l'espace de noms de métriques observé, à l'API de plateforme, aux trois équipes et à la fenêtre. Il rapproche les sommes d'invite et de réponse du manifeste selon une tolérance explicite et les valorise avec exactement un tarif par modèle, version, SKU, région, devise, période d'effet et unité, tiré de `scripts/prices/<snapshot>.json`.

Un rapport à couverture complète affiche des totaux. Un rapport à couverture partielle marque les valeurs connues comme partielles. Un rapport où l'utilisation, l'attribution ou les prix manquent supprime le total et consigne les nombres d'appels non attribués, sans prix, en échec et ambigus.

### Exercice 6.4 (pratique) : Lancer une session report-only

```powershell
./scripts/run-lab-workflow.ps1 -Mode report-only
```

Sans fenêtre, le script réutilise l'intervalle de la dernière session `run-existing` ou `full-session` réussie. Pour choisir votre propre fenêtre, passez `-WindowStart 2026-10-03T09:00:00Z -WindowEnd 2026-10-03T10:00:00Z`. La commande brute équivalente est :

```powershell
gh workflow run lab-session.yml -f mode=report-only -f generation=<generation> -f confirm_resource_group=<groupe-de-ressources> -f report_window_start=<debut-utc> -f report_window_end=<fin-utc>
```

Résultat attendu : la fenêtre n'est acceptée que si les deux valeurs sont en UTC, que le début précède la fin, que la fin n'est pas dans le futur et que la durée ne dépasse pas 24 heures. Sans manifeste de trafic, le rapport porte l'état `unreconciled` et n'affirme jamais un total complet. L'environnement est conservé quel que soit le résultat.

### Exercice 6.5 : Connaître le contournement des quotas

Résultat attendu : vous pouvez expliquer que les stratégies de produit ne s'appliquent pas aux abonnements limités à une API, aux abonnements à toutes les API ni à l'abonnement intégré à accès complet. Le sondage de portée de la session consigne le comportement des clés d'équipe limitées au produit, d'un abonnement de test temporaire limité à l'API et supprimé ensuite, ainsi que du chemin anonyme, qui doit renvoyer `401`. La clé intégrée à accès complet n'est jamais utilisée.

### Exercice 6.6 : Examiner les preuves de la session

> [!NOTE]
> Preuves examinées de la session `36608221120-1` ([exécution du flux de travail](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), produites le 2026-09-29 uniquement à partir de résultats expurgés. Les montants sont une répartition estimée des jetons du modèle au prix de détail, et non des frais facturés.

![Répartition estimée des jetons du modèle par équipe pour la session examinée]({{ '/assets/images/lab06-chargeback-summary.png' | relative_url }})

![Jetons d'invite et de réponse par équipe pour la session examinée]({{ '/assets/images/lab06-chargeback-tokens.png' | relative_url }})

## Liste de vérification

* [ ] Chaque graphique et chaque tableau porte l'étiquette de répartition estimée, l'intervalle, l'instantané, la couverture et les exclusions
* [ ] La fenêtre était réservée au trafic approuvé
* [ ] Les sommes des métriques correspondaient au manifeste d'utilisation, ou le rapport explique pourquoi
* [ ] Aucun total complet n'apparaît lorsqu'une couverture manque
* [ ] La sortie report-only porte l'état `unreconciled`

## Vérification des connaissances

* Pourquoi l'identifiant de page mentionne-t-il la refacturation (chargeback) alors que chaque sortie parle de répartition estimée?
* Pourquoi additionner à la fois `customMetrics` et `AppMetrics` de l'espace de travail compte-t-il deux fois la même utilisation?
* Quels coûts l'estimation exclut-elle, et pourquoi?
* Qu'est-ce qui rend une fenêtre de mesure contaminée?

## Étapes suivantes

Passez à l'[Atelier 07 : Démantèlement et exposition résiduelle aux coûts]({{ "/fr/labs/lab-07-teardown" | relative_url }}).
