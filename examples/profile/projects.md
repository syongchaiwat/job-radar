---
name: projects
description: Project database (fictional example), tagged by source, feeding the CV-drafting agent. Each entry's Tools field is the only list of skills the agent may cite.
---

# Project Database

Format per entry: Type (work/study/personal), Source (matches an anchor in `cv_profile/cv_template.md`, or the project's own name for personal work), Render section (only for `study` entries: `education` nests it under the degree, `projects` promotes it to the Projects section), Period, Repo (optional public repository URL, the only repo links a CV may show), Tools (explicit and exhaustive), Methodology, Results. Role angles are optional hints per kind of role; a dash means the project doesn't help that kind of role.

---

## Northwind: Dynamic Pricing Model for Hotel Offers
- **Type:** work
- **Source:** Northwind
- **Period:** 2021-2025
- **Tools:** Python, LightGBM, Spark, SQL, Airflow, A/B testing
- **Methodology:** Built a gradient-boosted demand model that sets daily price adjustments per market, validated through staged A/B tests before each rollout.
- **Results:** Lifted margin per booking by 3% across 40 markets in the final A/B test.
- **Role angles:**
  - Quant finance / risk: pricing under margin constraints.
  - LLM / agentic AI: -
  - ML engineering / applied ML: shipped production ML with measured impact.
  - Data / backend engineering: Spark/Airflow pipelines behind the model.
  - Business / product analytics: quantified business impact for stakeholders.

## Northwind: Experimentation Platform Metrics
- **Type:** work
- **Source:** Northwind
- **Period:** 2021-2025
- **Tools:** Python, statistics, SQL, dashboarding
- **Methodology:** Added variance reduction (CUPED) and multiple-testing correction to the company's A/B testing platform and built the dashboard product teams read results from.
- **Results:** Cut the average experiment runtime by about 25% at equal statistical power.
- **Role angles:**
  - Quant finance / risk: rigorous statistical inference.
  - LLM / agentic AI: transfers to LLM evaluation design.
  - ML engineering / applied ML: experimentation depth.
  - Data / backend engineering: -
  - Business / product analytics: decision-ready metrics for product teams.

## Northwind: Production MLOps
- **Type:** work
- **Source:** Northwind
- **Period:** 2021-2025
- **Tools:** MLflow, Docker, CI/CD, automated testing, model monitoring & alerting
- **Methodology:** Owned model versioning in MLflow, containerized training jobs, and set up drift alerts for the pricing models in production.
- **Results:** Every model change shipped through tests and CI/CD; drift alerts caught two data-quality incidents before they affected prices.
- **Role angles:**
  - Quant finance / risk: model risk control.
  - LLM / agentic AI: production discipline for LLM systems.
  - ML engineering / applied ML: end-to-end ML ownership.
  - Data / backend engineering: delivery and monitoring infrastructure.
  - Business / product analytics: -

## Contoso Bank: Credit Default Scorecard (internship)
- **Type:** work
- **Source:** Contoso
- **Period:** 2020
- **Tools:** Python, scikit-learn, logistic regression
- **Methodology:** Built a credit default scorecard on loan application data with monotonic binning and documented it for model validation.
- **Results:** Model approved by the bank's validation team for a pilot.
- **Role angles:**
  - Quant finance / risk: credit risk modeling, finance-flavored ML.
  - LLM / agentic AI: -
  - ML engineering / applied ML: classical ML with interpretability.
  - Data / backend engineering: -
  - Business / product analytics: -

## MSc Thesis: Retrieval-Augmented QA over Scientific Papers
- **Type:** study
- **Source:** MSc
- **Render section:** education
- **Period:** 2026-2027, ongoing
- **Tools:** Python, PyTorch, Hugging Face Transformers, FAISS, RAG
- **Methodology:** Comparing dense and hybrid retrieval for question answering over a corpus of scientific papers, with an evaluation set of 300 expert-written questions.
- **Results:** Hybrid retrieval improves answer accuracy by 9 points over dense-only retrieval on the evaluation set so far.
- **Role angles:**
  - Quant finance / risk: -
  - LLM / agentic AI: flagship RAG + evaluation story.
  - ML engineering / applied ML: research-grade deep learning.
  - Data / backend engineering: -
  - Business / product analytics: -

## Paper Pal: Literature Assistant
- **Type:** personal
- **Source:** Paper Pal
- **Render section:** projects
- **Period:** 2026
- **Repo:** https://github.com/example/paper-pal
- **Tools:** Python, LangGraph, FastAPI, LLM APIs, SQLite
- **Methodology:** Built an agent that searches arXiv, summarizes papers, and drafts related-work paragraphs with citations, with a small eval set to check citation accuracy.
- **Results:** 92% citation accuracy on a 50-question eval set.
- **Role angles:**
  - Quant finance / risk: -
  - LLM / agentic AI: agentic LLM workflow with evaluation, directly on target.
  - ML engineering / applied ML: -
  - Data / backend engineering: API and storage layer.
  - Business / product analytics: -
