"""Assembles the 6-node screening graph.

Two conditional branches beyond the plan's original linear sketch, both for
cost control -- no point spending a Sonnet call scoring/gap-analyzing a job
that's already excluded or matches no theme at all:

    normalize -> generate_blurb -> filter_gate --(exclude)--> END
                                         |
                                    (keep/flag)
                                         v
                                   classify_theme --(none)--> END
                                         |
                                    (has theme)
                                         v
                                   score_match -> extract_gaps -> END

Manual (hand-added) jobs never take the exclude branch: filter_gate turns a
rule hit into "flag" with the reason kept, since the user already chose the
job and wants its theme/match/gaps anyway. The short-circuit still saves
tokens on bulk API results.

generate_blurb runs unconditionally (before the filter_gate short-circuit)
so every job, including excluded ones, gets a card blurb for the dashboard's
"show excluded" audit view.
"""
from langgraph.graph import END, StateGraph

from src.pipeline.nodes import (
    classify_theme_node,
    extract_gaps_node,
    filter_gate_node,
    generate_blurb_node,
    normalize_node,
    score_match_node,
)
from src.pipeline.schemas import PipelineState


def _after_filter_gate(state: PipelineState) -> str:
    return "stop" if state.decision == "exclude" else "continue"


def _after_classify_theme(state: PipelineState) -> str:
    return "stop" if state.theme in (None, "none") else "continue"


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("normalize", normalize_node)
    graph.add_node("generate_blurb", generate_blurb_node)
    graph.add_node("filter_gate", filter_gate_node)
    graph.add_node("classify_theme", classify_theme_node)
    graph.add_node("score_match", score_match_node)
    graph.add_node("extract_gaps", extract_gaps_node)

    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "generate_blurb")
    graph.add_edge("generate_blurb", "filter_gate")
    graph.add_conditional_edges("filter_gate", _after_filter_gate, {"continue": "classify_theme", "stop": END})
    graph.add_conditional_edges("classify_theme", _after_classify_theme, {"continue": "score_match", "stop": END})
    graph.add_edge("score_match", "extract_gaps")
    graph.add_edge("extract_gaps", END)

    return graph.compile()
