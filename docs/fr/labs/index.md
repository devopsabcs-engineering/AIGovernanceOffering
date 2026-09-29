---
permalink: /fr/labs/
lang: fr
title: "Ateliers"
description: "Le programme de huit ateliers pour gouverner des modèles Microsoft Foundry derrière Azure API Management."
nav_order: 1
---

**[English version]({{ "/labs/" | relative_url }})**

> [!IMPORTANT]
> Utilisez uniquement des invites synthétiques. La journalisation des messages LLM reste désactivée sur chaque API : les laboratoires n'enregistrent jamais les invites ni les réponses dans la télémétrie; seuls les nombres de jetons et des dimensions bornées quittent la passerelle. Les images de session apparaissent sur ce site seulement après qu'une personne responsable a examiné les preuves expurgées.

## Programme des ateliers

Suivez les ateliers dans l'ordre. L'atelier 00 déploie l'environnement, les ateliers 01 à 05 suivent les cinq carnets, l'atelier 06 mesure la répartition estimée des coûts à partir d'un trafic borné, et l'atelier 07 retire ce que la session a créé et signale ce qui reste.

<!-- markdownlint-disable MD055 MD056 -->

| Atelier | Titre | Responsable des preuves |
| --- | --- | --- |
{% for lab in site.data.labs -%}
{%- assign lab_url = "/fr/labs/" | append: lab.slug | relative_url -%}
| [{{ lab.number }}]({{ lab_url }}) | {{ lab.title_fr }} | {{ lab.evidence_owner_fr }} |
{% endfor %}

<!-- markdownlint-enable MD055 MD056 -->

## État des preuves

Chaque page d'atelier termine ses exercices par une section sur les preuves. Tant qu'une personne responsable n'a pas examiné les preuves expurgées d'une session approuvée, cette section indique que les preuves sont en attente d'examen. Les états en échec, non concluants, incomplets ou avec exposition résiduelle sont publiés sous forme de cartes d'état, jamais sous forme d'images de réussite.
