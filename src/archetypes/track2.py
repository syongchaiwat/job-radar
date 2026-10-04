"""Track 2 of an archetype rework: taxonomy built by an LLM (docs §5.3 step 3).

Opus reads role cards batch by batch, proposing a taxonomy and refining it with
every batch (TnT-LLM pattern), then labels every job with the final version.
Independent of Track 1, so the two catch each other's blind spots.
"""
from src.archetypes.features import PoolJob, compact_card
from src.pipeline.llm_call import call, load_prompt
from src.pipeline.schemas import JobLabels, Taxonomy

ROLE = "critique"  # Opus, native structured outputs
TAXONOMY_BATCH = 24
LABEL_BATCH = 30


def _taxonomy_text(t: Taxonomy) -> str:
    return "\n\n".join(
        f"- {a.name}: {a.definition}\n  include: {a.include}\n  exclude: {a.exclude}\n  skills: {', '.join(a.defining_skills)}"
        for a in t.archetypes
    )


def build_taxonomy(pool: list[PoolJob], progress=None) -> tuple[Taxonomy, int]:
    tokens = 0
    taxonomy: Taxonomy | None = None
    batches = [pool[i:i + TAXONOMY_BATCH] for i in range(0, len(pool), TAXONOMY_BATCH)]
    for i, batch in enumerate(batches, 1):
        if progress:
            progress(f"Track 2: building taxonomy, batch {i}/{len(batches)}")
        instruction = (
            "Propose the initial taxonomy from this batch." if taxonomy is None
            else "Refine the previous taxonomy with this batch: keep what still fits, add, merge, split or rename where these jobs require it. Return the full updated taxonomy."
        )
        prompt = load_prompt("archetype_taxonomy").format(
            previous=_taxonomy_text(taxonomy) if taxonomy else "(none yet: this is the first batch)",
            cards="\n".join(compact_card(pj) for pj in batch),
            instruction=instruction,
        )
        taxonomy, log = call(ROLE, prompt, Taxonomy)
        tokens += log.input_tokens + log.output_tokens
    return taxonomy, tokens


def label_jobs(pool: list[PoolJob], taxonomy: Taxonomy, progress=None) -> tuple[dict[str, tuple[str, float]], int]:
    names = {a.name for a in taxonomy.archetypes}
    labels: dict[str, tuple[str, float]] = {}
    tokens = 0
    batches = [pool[i:i + LABEL_BATCH] for i in range(0, len(pool), LABEL_BATCH)]
    for i, batch in enumerate(batches, 1):
        if progress:
            progress(f"Track 2: labeling jobs, batch {i}/{len(batches)}")
        prompt = load_prompt("archetype_label").format(
            taxonomy=_taxonomy_text(taxonomy), cards="\n".join(compact_card(pj) for pj in batch)
        )
        parsed, log = call(ROLE, prompt, JobLabels)
        tokens += log.input_tokens + log.output_tokens
        for lab in parsed.labels:
            labels[lab.job_id] = (lab.archetype if lab.archetype in names else "none", lab.confidence)
    for pj in pool:  # an id the model skipped counts as unlabeled
        labels.setdefault(pj.job_id, ("none", 0.0))
    return labels, tokens


def taxonomy_text(t: Taxonomy) -> str:
    return _taxonomy_text(t)
