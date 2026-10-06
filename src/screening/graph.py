"""Assembles the 5-node screening graph.
One conditional branch for cost control -- no point spending a Sonnet call
scoring/gap-analyzing a job that's already excluded:
    normalize -> generate_blurb -> filter_gate --(exclude)--> END
                                         |
                                    (keep/flag)
                                         v
                                   score_match -> extract_gaps -> END
Manual (hand-added) jobs never take the exclude branch: filter_gate turns a
rule hit into "flag" with the reason kept, since the user already chose the
job and wants its match/gaps anyway. The short-circuit still saves tokens on
bulk API results.
generate_blurb runs unconditionally (before the filter_gate short-circuit)
so every job, including excluded ones, gets a card blurb for the dashboard's
"show excluded" audit view. The kind of work (archetype) is assigned outside
this graph, from the role card and embeddings (src/archetypes).
"""
from langgraph.graph import END, StateGraph

from src.screening.nodes import (
    extract_gaps_node,
    filter_gate_node,
    generate_blurb_node,
    normalize_node,
    score_match_node,
)
from src.llm.schemas import PipelineState


def _after_filter_gate(state: PipelineState) -> str:
    return "stop" if state.decision == "exclude" else "continue"


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("normalize", normalize_node)
    graph.add_node("generate_blurb", generate_blurb_node)
    graph.add_node("filter_gate", filter_gate_node)
    graph.add_node("score_match", score_match_node)
    graph.add_node("extract_gaps", extract_gaps_node)
    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "generate_blurb")
    graph.add_edge("generate_blurb", "filter_gate")
    graph.add_conditional_edges("filter_gate", _after_filter_gate, {"continue": "score_match", "stop": END})
    graph.add_edge("score_match", "extract_gaps")
    graph.add_edge("extract_gaps", END)
    return graph.compile()
