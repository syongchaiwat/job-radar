"""Assembles the CV draft/critique loop graph.

Unlike the screening graph (graph.py), this one has an actual cycle:

    draft_cv --> critique_cv --(revise, attempt_count < MAX_ATTEMPTS)--> draft_cv
                      |
                (approve, or attempt_count >= MAX_ATTEMPTS)
                      v
                     END

No interrupt()/checkpointer: this runs fully automated in one blocking
invoke(), same "slow blocking route" precedent as compute_breakdown, just
with more calls. MAX_ATTEMPTS is the sole termination guardrail beyond an
"approve" verdict.
"""
from langgraph.graph import END, StateGraph

from src.pipeline.cv_nodes import critique_cv_node, draft_cv_node
from src.pipeline.schemas import CVDraftState

MAX_ATTEMPTS = 3  # 1 initial draft + up to 2 revisions -> worst case 6 "deep" LLM calls


def _after_critique_cv(state: CVDraftState) -> str:
    if state.verdict == "approve":
        return "done"
    if state.attempt_count >= MAX_ATTEMPTS:
        return "done"
    return "revise"


def build_cv_graph():
    graph = StateGraph(CVDraftState)
    graph.add_node("draft_cv", draft_cv_node)
    graph.add_node("critique_cv", critique_cv_node)

    graph.set_entry_point("draft_cv")
    graph.add_edge("draft_cv", "critique_cv")
    graph.add_conditional_edges("critique_cv", _after_critique_cv, {"revise": "draft_cv", "done": END})

    return graph.compile()
