---
lang: fr
layout: default
title: Accueil
description: Laboratoires pratiques et bilingues pour gouverner des modèles Microsoft Foundry derrière Azure API Management à l'aide de stratégies, de preuves bornées, d'une répartition estimée des coûts et d'un démantèlement des ressources détenues.
nav_order: 0
permalink: /fr/
---

**[English version]({{ "/" | relative_url }})**

Bienvenue dans les **laboratoires de gouvernance de l'IA**, une série pratique et bilingue qui gouverne des modèles Microsoft Foundry derrière Azure API Management (APIM) au moyen de stratégies de passerelle plutôt que de code applicatif. Vous appliquerez des limites et des quotas de jetons, émettrez des métriques de jetons, inspecterez le contenu dans les deux sens, acheminerez les appels dans un pool de back-ends résilient, produirez une répartition estimée des coûts de jetons de modèle et démantèlerez les ressources créées par une session.

![Flux animé de bout en bout des quatre démonstrations de gouvernance : limites de jetons, métriques de jetons, sécurité du contenu et routage dans un pool résilient]({{ "/ai-governance-flows.svg" | relative_url }})

> [!IMPORTANT]
> Utilisez uniquement des invites synthétiques. La journalisation des messages LLM reste désactivée sur chaque API : les laboratoires n'enregistrent jamais les invites ni les réponses dans la télémétrie; seuls les nombres de jetons et des dimensions bornées quittent la passerelle. Les images de session apparaissent sur ce site seulement après qu'une personne responsable a examiné les preuves expurgées.

## Ce que vous allez construire

Une passerelle APIM Basic v2 dessert un déploiement de modèle approuvé et une ressource Azure AI Content Safety. Application Insights, adossé à un espace de travail, reçoit les métriques de jetons par un enregistreur à identité managée, l'authentification locale étant désactivée. Cinq carnets Python configurent des API de démonstration sur cette passerelle, et une API de plateforme nommée `ai-gateway-api` expose trois produits d'équipe pour l'atelier de répartition des coûts.

## Ce que les laboratoires ne prouvent pas

Lisez ces limites avant d'exécuter un atelier. Chaque page d'atelier rappelle les limites qui la concernent.

* Basic v2 est un choix conditionnel. Sa passerelle est un point de terminaison public, sans point de terminaison privé entrant ni connectivité privée vers les back-ends; le déploiement exige donc l'approbation explicite de cette exposition publique. Lorsque le réseau privé est requis, choisissez Standard v2 et validez cette topologie séparément.
* Le pool résilient achemine les appels vers des membres simulés hébergés sur la même instance APIM. Il démontre des décisions de routage, et non une résilience multirégion réelle ni le comportement du débit provisionné.
* Les résultats de sécurité du contenu peuvent être `inconclusive`. Un objectif requis non concluant empêche d'affirmer que tous les ateliers ont réussi.
* L'atelier de répartition des coûts produit une estimation des coûts de jetons de modèle aux prix de détail sans mise en cache. Il ne s'agit pas d'une refacturation facturée, et elle exclut les coûts partagés de plateforme, de journalisation, de sécurité, de réseau, de taxes et de contrat.
* Le démantèlement s'exécute à blanc par défaut, signale l'exposition résiduelle et ne purge jamais. La purge des ressources supprimées de manière réversible est une opération réservée à une personne.

## Parcours d'apprentissage

Vous pouvez suivre les ateliers de deux façons. Le parcours interactif exécute chaque carnet vous-même contre une instance APIM que vous possédez déjà, à partir d'une session `az login`. Le parcours automatisé exécute une session GitHub Actions protégée et approuvée manuellement qui déploie l'environnement, exécute les cinq carnets sans interaction, génère un trafic borné, produit la répartition estimée des coûts et nettoie les ressources qu'elle a créées.

Aucun des deux parcours n'exige GitHub Copilot ni un autre assistant de programmation par IA. Des outils assistés par IA ont aidé à rédiger ces pages, et des personnes responsables révisent chaque page avant sa publication.

## Ateliers

Le programme complet se trouve dans [Ateliers]({{ "/fr/labs/" | relative_url }}).
