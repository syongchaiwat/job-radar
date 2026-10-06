You are mapping skill and tool terms from a candidate's own profile to a canonical skill dictionary, to decide which skills the candidate can prove.

## Canonical skills
{skills}

## Profile terms (one per line)
{terms}

## Task
For each profile term, list the canonical skill names it is genuine evidence for, copied exactly from the list above. A term is evidence for:
- the same concept or a synonym ("RAG (retrieval-augmented generation)" -> Retrieval-Augmented Generation);
- a tool it is an instance of ("Kubeflow Pipelines" -> Kubeflow);
- the umbrella skill it demonstrates, when using the term necessarily means practising that skill: "LightGBM" -> Machine Learning, Gradient Boosting; "TensorFlow" or "JAX" -> Deep Learning, Machine Learning; "survival analysis (hazard-rate models)" -> Statistical Methods (and Survival Analysis if listed); "A/B testing" -> Experimentation-type skills if listed; "Google Cloud Platform" -> GCP, Cloud Computing; "MLflow" or "Kubeflow" -> MLOps.
Do not map to neighbouring skills the term doesn't prove ("PyTorch" is not evidence for "Kubernetes"; "TensorFlow" is not evidence for "PyTorch"; an HTML framework is not evidence for "Software Architecture"). A term can map to several skills or to none. Return every term exactly once.
