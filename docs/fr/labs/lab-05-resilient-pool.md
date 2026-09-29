---
permalink: /fr/labs/lab-05-resilient-pool
lang: fr
title: "Atelier 05 - Pool de back-ends résilient simulé"
description: "Observer les décisions de priorité, de poids, de disjoncteur et de débordement dans un pool de back-ends APIM composé de membres simulés, puis confirmer que l'inférence réelle utilise le même pool."
nav_order: 15
---

**[English version]({{ "/labs/lab-05-resilient-pool" | relative_url }})**

> [!IMPORTANT]
> Utilisez uniquement des invites synthétiques. La journalisation des messages LLM reste désactivée sur chaque API : le laboratoire n'enregistre jamais les invites ni les réponses dans la télémétrie; seuls les nombres de jetons et des dimensions bornées quittent la passerelle. Les images de session apparaissent sur ce site seulement après qu'une personne responsable a examiné les preuves expurgées.

## Aperçu

{% assign prerequisite_url = "/fr/labs/lab-04-content-safety" | relative_url %}

| Élément | Valeur |
| --- | --- |
| **Durée** | 35 minutes |
| **Niveau** | Avancé |
| **Prérequis** | [Atelier 04]({{ prerequisite_url }}) terminé sur un niveau APIM qui prend en charge les pools de back-ends et les disjoncteurs |

`notebooks/demo4-resilient-pool.ipynb` construit un back-end de type pool, `demo4-aoai-pool`, avec deux membres de priorité 1, `demo4-ptu-east` (poids 2) et `demo4-ptu-central` (poids 1), et un membre de débordement de priorité 2, `demo4-payg`. Chaque membre possède un disjoncteur qui se déclenche sur les réponses `429` et `5xx` et respecte `Retry-After`. La stratégie de l'API délègue la sélection à APIM par une seule ligne `set-backend-service`; la requête du client ne change donc jamais.

> [!WARNING]
> Le pool achemine les appels vers des membres simulés hébergés sur la même instance APIM. Il démontre des décisions de priorité, de poids, de disjoncteur et de débordement; il ne prouve ni une résilience multirégion réelle ni le comportement du débit provisionné (PTU). Les noms des membres sont des étiquettes, et non de vraies régions ni une capacité réservée. Les membres d'un pool réel doivent utiliser le même modèle et la même version, sinon des appels réussis peuvent dériver silencieusement.

## Objectifs d'apprentissage

À la fin de cet atelier, vous serez capable de :

* Expliquer le routage par appel selon la priorité, puis le poids, puis l'état de santé
* Distinguer le mode de routage, qui utilise des membres simulés, du mode d'inférence, qui utilise le vrai modèle
* Observer le déclenchement d'un disjoncteur sur des réponses `429` injectées et le routage vers le membre de remplacement
* Confirmer le rétablissement seulement après une panne consignée
* Expliquer pourquoi l'API simulée exige toujours ses informations d'identification

## Exercices

### Exercice 5.1 : Lire la stratégie du pool

```powershell
Get-Content policies/demo4-resilient-pool.xml
Get-Content policies/demo4-mock-origin.xml
```

Résultat attendu : la stratégie de l'API contient `<set-backend-service backend-id="demo4-aoai-pool" />`, et la stratégie de l'origine simulée renvoie un corps de forme chat-completions avec un en-tête `x-served-by`, ou un `429` d'origine avec `Retry-After` lorsque son commutateur de panne est activé.

### Exercice 5.2 (pratique) : Faire l'appel d'inférence de référence

Ouvrez `notebooks/demo4-resilient-pool.ipynb` et exécutez la section du mode d'inférence.

Résultat attendu : un appel atteint le vrai modèle par la même stratégie de pool. Il prouve que le pool gouverne le trafic d'inférence; il n'identifie pas de membre, car les vraies réponses ne portent pas d'en-tête `x-served-by`.

### Exercice 5.3 (pratique) : Observer le routage et la pondération

Exécutez les sections CALL 1 et CALL 2 en mode de routage.

Résultat attendu : chaque appel client inchangé indique le membre qui le sert dans `x-served-by`, et 30 appels sains se répartissent approximativement à 2:1 entre East et Central. Cette étape consigne `demo4.routing_paths`.

Le ratio est approximatif. Un petit échantillon ne promet jamais une répartition exacte, mais une valeur `x-served-by` inconnue ou absente, un `404` ou un état inattendu fait échouer la phase.

### Exercice 5.4 (pratique) : Provoquer une panne et un débordement

Exécutez la section FAULT.

Résultat attendu : East renvoie les réponses `429` injectées et son disjoncteur s'ouvre, Central sert ensuite le trafic de priorité 1, puis, lorsque Central est aussi en panne, PAYG sert le débordement. Cette étape consigne `demo4.fault_observed` et `demo4.alternate_routing`.

Un disjoncteur qui ne se déclenche pas constitue un objectif en échec, et non un avertissement compatible avec la réussite. Chaque commutateur de panne est rétabli dans `finally`, et une cellule distincte peut rétablir tous les membres simulés à tout moment.

### Exercice 5.5 (pratique) : Rétablir

Exécutez la section RECOVER.

Résultat attendu : après l'expiration de la période du disjoncteur, East réapparaît dans `x-served-by`. Cette étape consigne `demo4.recovery` seulement après une panne consignée.

### Exercice 5.6 : Confirmer l'application des informations d'identification simulées

Résultat attendu : un appel direct à l'API simulée sans ses informations d'identification est rejeté. Ce sondage négatif consigne `demo4.mock_auth_enforced`. L'API simulée n'est jamais rendue anonyme pour corriger le routage.

### Exercice 5.7 : Examiner les preuves de la session

> [!NOTE]
> Preuves en attente d'examen. Les images `lab05-resilient-pool-summary.png` (réussite) ou `lab05-resilient-pool-status.png` (tout autre état) sont produites à partir des résultats d'objectifs de la démo 4 et n'apparaissent ici qu'après qu'une personne responsable a examiné les preuves expurgées de la session.

## Liste de vérification

* [ ] La requête du client était identique octet par octet dans chaque phase
* [ ] Chaque appel acheminé a renvoyé un membre `x-served-by` connu
* [ ] Les pannes d'East ont précédé le routage vers Central, et les pannes de Central ont précédé le routage vers PAYG
* [ ] Le rétablissement n'a été observé qu'après une panne consignée
* [ ] L'API simulée a rejeté un appel sans ses informations d'identification

## Vérification des connaissances

* Dans quel ordre APIM évalue-t-il les membres du pool pour chaque appel?
* Pourquoi une réponse saine d'East sans panne préalable fait-elle échouer l'objectif de rétablissement?
* Que faudrait-il ajouter pour affirmer une résilience multirégion réelle?
* Pourquoi chaque membre d'un pool réel doit-il utiliser le même modèle et la même version?

## Étapes suivantes

Passez à l'[Atelier 06 : Répartition estimée des coûts de jetons]({{ "/fr/labs/lab-06-chargeback" | relative_url }}).
