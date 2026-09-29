---
permalink: /fr/labs/lab-02-token-limits
lang: fr
title: "Atelier 02 - Limites et quotas de jetons"
description: "Appliquer llm-token-limit à la portée de l'API, déclencher un 429 de la passerelle et un 403 de quota quotidien dans une enveloppe bornée, puis réinitialiser les compteurs instantanément."
nav_order: 12
---

**[English version]({{ "/labs/lab-02-token-limits" | relative_url }})**

> [!IMPORTANT]
> Utilisez uniquement des invites synthétiques. La journalisation des messages LLM reste désactivée sur chaque API : le laboratoire n'enregistre jamais les invites ni les réponses dans la télémétrie; seuls les nombres de jetons et des dimensions bornées quittent la passerelle. Les images de session apparaissent sur ce site seulement après qu'une personne responsable a examiné les preuves expurgées.

## Aperçu

{% assign prerequisite_url = "/fr/labs/lab-01-setup-validation" | relative_url %}

| Élément | Valeur |
| --- | --- |
| **Durée** | 30 minutes |
| **Niveau** | Intermédiaire |
| **Prérequis** | [Atelier 01]({{ prerequisite_url }}) terminé avec un fichier `.env` conservé |

Les charges de travail d'IA sont facturées et limitées en jetons, et non en requêtes. `notebooks/demo1-token-limits.ipynb` applique la stratégie `llm-token-limit`, indépendante du fournisseur, à la portée de l'API : un seul élément impose à la fois une limite de jetons par minute, qui renvoie `429` avec `Retry-After`, et un quota quotidien de jetons, qui renvoie `403`.

Un abonnement APIM dédié et un suffixe `x-demo-run` dans la clé de compteur de la stratégie isolent les compteurs de cet atelier des autres exécutions, des autres démonstrations et de tout autre trafic sur la même instance.

> [!NOTE]
> Un `429` du back-end ne prouve pas la limite de la passerelle. L'objectif `demo1.rate_limit_429` n'est atteint qu'avec une provenance de la passerelle, comme les en-têtes de stratégie `remaining-tokens`, et un `403` de quota n'est jamais la preuve d'une décision de sécurité du contenu.

## Objectifs d'apprentissage

À la fin de cet atelier, vous serez capable de :

* Lire une stratégie `llm-token-limit` et nommer l'attribut à l'origine de chaque état observé
* Interpréter les en-têtes `tokens-consumed`, `remaining-tokens` et `remaining-quota-tokens`
* Distinguer un `429` de jetons par minute de la passerelle d'une limitation du back-end et d'un `403` de quota
* Réinitialiser chaque compteur de l'atelier sans attendre la fin d'une fenêtre
* Expliquer comment le budget de session borne les boucles de rafale et d'accumulation

## Exercices

### Exercice 2.1 : Lire la stratégie

```powershell
Get-Content policies/demo1-token-limit.xml
```

Résultat attendu : un seul élément `llm-token-limit` définit `tokens-per-minute`, `token-quota`, `token-quota-period="Daily"`, `estimate-prompt-tokens="false"` et une `counter-key` qui combine l'identifiant d'abonnement et l'en-tête `x-demo-run`.

Les valeurs des limites proviennent de valeurs nommées plutôt que de littéraux, et le back-end s'authentifie avec l'identité managée d'APIM. La stratégie retire l'en-tête et le paramètre de requête de la clé d'abonnement du client avant le transfert; la clé n'atteint donc jamais le back-end du modèle.

### Exercice 2.2 (pratique) : Faire un appel de référence

Ouvrez `notebooks/demo1-token-limits.ipynb` et exécutez les cellules jusqu'à l'appel de référence.

Résultat attendu : une réponse `200` avec les trois en-têtes de jetons. Cet appel consigne l'objectif `demo1.baseline`.

Avec `estimate-prompt-tokens="false"`, `tokens-consumed` reflète l'utilisation d'invite et de réponse rapportée par le modèle.

### Exercice 2.3 (pratique) : Déclencher un 429 par rafale

Exécutez la section de rafale.

Résultat attendu : une boucle bornée de requêtes rapides se termine par un `429` avec un en-tête `Retry-After`, et le graphique montre `remaining-tokens` qui diminue pendant la rafale. Cette étape consigne `demo1.rate_limit_429` lorsque les en-têtes de la passerelle confirment la source.

### Exercice 2.4 (pratique) : Accumuler jusqu'au 403 quotidien

Exécutez la section d'accumulation.

Résultat attendu : la boucle respecte chaque `Retry-After`, `remaining-quota-tokens` diminue vers zéro et la passerelle renvoie `403` une fois le quota quotidien épuisé. Cette étape consigne `demo1.quota_exhausted`.

Les deux boucles s'arrêtent à un nombre maximal d'itérations et à une limite de durée. Dans une session automatisée, chaque appel réserve aussi les jetons d'entrée et le maximum de jetons de sortie dans l'enveloppe commune de la session avant son envoi, et une réservation qui ne tient pas arrête la boucle avec `BudgetExceeded`.

### Exercice 2.5 (pratique) : Réinitialiser les compteurs

Exécutez la section de réinitialisation.

Résultat attendu : une nouvelle valeur `DEMO_RUN` est conservée dans `.env`, et l'appel suivant réussit immédiatement. Cette étape consigne `demo1.reset_recovery`.

Les ressources restent en place, car les ateliers suivants réutilisent la même instance APIM.

### Exercice 2.6 : Examiner les preuves de la session

> [!NOTE]
> Preuves examinées de la session `36608221120-1` ([exécution du flux de travail](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), produites le 2026-09-29 uniquement à partir de résultats expurgés.

![Résultats des objectifs de l'atelier 02 pour la session examinée]({{ '/assets/images/lab02-token-limits-summary.png' | relative_url }})

## Liste de vérification

* [ ] La réponse de référence portait les trois en-têtes de jetons
* [ ] Le `429` portait `Retry-After` et une provenance de la passerelle
* [ ] Le `403` n'est apparu qu'après que `remaining-quota-tokens` a atteint zéro
* [ ] Une nouvelle valeur `DEMO_RUN` a rétabli le service immédiatement
* [ ] Les quatre objectifs de la démo 1 ont un état consigné

## Vérification des connaissances

* Quel attribut de `llm-token-limit` produit le `429`, et lequel produit le `403`?
* Pourquoi un `429` provenant du back-end du modèle fait-il échouer l'objectif `demo1.rate_limit_429`?
* Comment la modification de `DEMO_RUN` réinitialise-t-elle les compteurs sans toucher à la stratégie?
* Pourquoi les limites de jetons d'APIM peuvent-elles être dépassées sous un trafic concurrent?

## Étapes suivantes

Passez à l'[Atelier 03 : Métriques de jetons]({{ "/fr/labs/lab-03-token-metrics" | relative_url }}).
