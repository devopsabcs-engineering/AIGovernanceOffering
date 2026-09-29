---
permalink: /labs/
title: "Labs"
description: "The eight-lab curriculum for governing Microsoft Foundry models behind Azure API Management."
nav_order: 1
---

**[Version française]({{ "/fr/labs/" | relative_url }})**

> [!IMPORTANT]
> Use synthetic prompts only. LLM message logging stays off on every API, so the labs never record prompts or completions in telemetry; only token counts and bounded dimensions leave the gateway. Session images appear on this site only after a maintainer reviews sanitized evidence.

## Lab Curriculum

Work through the labs in order. Lab 00 deploys the environment, Labs 01 through 05 follow the five notebooks, Lab 06 measures estimated showback from bounded traffic, and Lab 07 removes what the session created and reports what remains.

<!-- markdownlint-disable MD055 MD056 -->

| Lab | Title | Evidence owner |
| --- | --- | --- |
{% for lab in site.data.labs -%}
{%- assign lab_url = "/labs/" | append: lab.slug | relative_url -%}
| [{{ lab.number }}]({{ lab_url }}) | {{ lab.title_en }} | {{ lab.evidence_owner_en }} |
{% endfor %}

<!-- markdownlint-enable MD055 MD056 -->

## Evidence status

Every lab page ends its exercises with an evidence section. Until a maintainer reviews sanitized evidence from an approved session, that section states that evidence is pending review. Failed, inconclusive, incomplete, or residual-exposure states are published as status cards, never as success images.
