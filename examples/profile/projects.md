---
name: projects
description: Project database (fictional example), tagged by source, feeding the CV-drafting agent. Each entry's Tools field is the only list of skills the agent may cite.
---

# Project Database

Format per entry: Type (work/study/personal), Source (matches an anchor in `cv_profile/cv_template.md`, or the project's own name for personal work), Render section (only for `study` entries: `education` nests it under the degree, `projects` promotes it to the Projects section), Period, Repo (optional public repository URL, the only repo links a CV may show), Tools (explicit and exhaustive), Methodology, Results. Theme angles (T1-T4) are optional hints; a dash means the project doesn't help that theme.

---

## Northwind: Dynamic Pricing Model for Hotel Offers
- **Type:** work
- **Source:** Northwind
- **Period:** 2021-2025
- **Tools:** Python, LightGBM, Spark, SQL, Airflow, A/B testing
- **Methodology:** Built a gradient-boosted demand model that sets daily price adjustments per market, validated through staged A/B tests before each rollout.
- **Results:** Lifted margin per booking by 3% across 40 markets in the final A/B test.
- **Theme angles:**
  - T1: pricing under margin constraints.
  - T2: -
  - T3a: shipped production ML with measured impact.
  - T3b: Spark/Airflow pipelines behind the model.
  - T4: quantified business impact for stakeholders.

## Northwind: Experimentation Platform Metrics
- **Type:** work
- **Source:** Northwind
- **Period:** 2021-2025
- **Tools:** Python, statistics, SQL, dashboarding
- **Methodology:** Added variance reduction (CUPED) and multiple-testing correction to the company's A/B testing platform and built the dashboard product teams read results from.
- **Results:** Cut the average experiment runtime by about 25% at equal statistical power.
- **Theme angles:**
  - T1: rigorous statistical inference.
  - T2: transfers to LLM evaluation design.
  - T3a: experimentation depth.
  - T3b: -
  - T4: decision-ready metrics for product teams.

## Northwind: Production MLOps
- **Type:** work
- **Source:** Northwind
- **Period:** 2021-2025
- **Tools:** MLflow, Docker, CI/CD, automated testing, model monitoring & alerting
- **Methodology:** Owned model versioning in MLflow, containerized training jobs, and set up drift alerts for the pricing models in production.
- **Results:** Every model change shipped through tests and CI/CD; drift alerts caught two data-quality incidents before they affected prices.
- **Theme angles:**
  - T1: model risk control.
  - T2: production discipline for LLM systems.
  - T3a: end-to-end ML ownership.
  - T3b: delivery and monitoring infrastructure.
  - T4: -

## Contoso Bank: Credit Default Scorecard (internship)
- **Type:** work
- **Source:** Contoso
- **Period:** 2020
- **Tools:** Python, scikit-learn, logistic regression
- **Methodology:** Built a credit default scorecard on loan application data with monotonic binning and documented it for model validation.
- **Results:** Model approved by the bank's validation team for a pilot.
- **Theme angles:**
  - T1: credit risk modeling, finance-flavored ML.
  - T2: -
  - T3a: classical ML with interpretability.
  - T3b: -
  - T4: -

## MSc Thesis: Retrieval-Augmented QA over Scientific Papers
- **Type:** study
- **Source:** MSc
- **Render section:** education
- **Period:** 2026-2027, ongoing
- **Tools:** Python, PyTorch, Hugging Face Transformers, FAISS, RAG
- **Methodology:** Comparing dense and hybrid retrieval for question answering over a corpus of scientific papers, with an evaluation set of 300 expert-written questions.
- **Results:** Hybrid retrieval improves answer accuracy by 9 points over dense-only retrieval on the evaluation set so far.
- **Theme angles:**
  - T1: -
  - T2: flagship RAG + evaluation story.
  - T3a: research-grade deep learning.
  - T3b: -
  - T4: -

## Paper Pal: Literature Assistant
- **Type:** personal
- **Source:** Paper Pal
- **Render section:** projects
- **Period:** 2026
- **Repo:** https://github.com/example/paper-pal
- **Tools:** Python, LangGraph, FastAPI, LLM APIs, SQLite
- **Methodology:** Built an agent that searches arXiv, summarizes papers, and drafts related-work paragraphs with citations, with a small eval set to check citation accuracy.
- **Results:** 92% citation accuracy on a 50-question eval set.
- **Theme angles:**
  - T1: -
  - T2: agentic LLM workflow with evaluation, directly on-theme.
  - T3a: -
  - T3b: API and storage layer.
  - T4: -
