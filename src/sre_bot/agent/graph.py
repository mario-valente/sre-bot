"""LangGraph definition for the SRE Copilot agent."""

import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sre_bot.agent.nodes import (
    extract_context,
    fetch_correlated_alerts,
    fetch_github,
    fetch_historical_solutions,
    fetch_kubernetes,
    fetch_logs,
    fetch_metrics,
    fetch_traces,
    post_to_slack,
    synthesize,
)
from sre_bot.agent.state import AgentState

logger = structlog.get_logger()

# Module-level cache for compiled graph
_compiled_graph: CompiledStateGraph | None = None


def build_graph() -> CompiledStateGraph:
    """
    Build and compile the SRE Copilot agent graph.

    Graph Structure:
    ```
                                 START
                                   │
                                   ▼
                            extract_context
                                   │
        ┌───────────┬───────┬──────┼──────┬───────────┬──────────────────────┬────────────────────────┐
        │           │       │      │      │           │                      │                        │
        ▼           ▼       ▼      ▼      ▼           ▼                      ▼                        ▼
    fetch_metrics fetch_logs fetch_traces fetch_kubernetes fetch_correlated_alerts fetch_historical_solutions (parallel)
        │           │       │      │      │           │                      │                        │
        └───────────┴───────┴──────┼──────┴───────────┴──────────────────────┴────────────────────────┘
                                   │
                                   ▼
                             fetch_github
                                   │
                                   ▼
                              synthesize
                                   │
                                   ▼
                            post_to_slack
                                   │
                                   ▼
                                  END
    ```

    Returns:
        CompiledStateGraph: Ready-to-execute graph.
    """
    log = logger.bind(component="graph_builder")
    log.info("building agent graph")

    # Create graph with Pydantic state
    graph = StateGraph(AgentState)

    # === Register Nodes ===
    graph.add_node("extract_context", extract_context)
    graph.add_node("fetch_metrics", fetch_metrics)
    graph.add_node("fetch_logs", fetch_logs)
    graph.add_node("fetch_traces", fetch_traces)
    graph.add_node("fetch_kubernetes", fetch_kubernetes)
    graph.add_node("fetch_correlated_alerts", fetch_correlated_alerts)
    graph.add_node("fetch_historical_solutions", fetch_historical_solutions)
    graph.add_node("fetch_github", fetch_github)
    graph.add_node("synthesize", synthesize)
    graph.add_node("post_to_slack", post_to_slack)

    # === Define Edges ===

    # Start → extract_context
    graph.add_edge(START, "extract_context")

    # extract_context → parallel fan-out to all data collection nodes
    graph.add_edge("extract_context", "fetch_metrics")
    graph.add_edge("extract_context", "fetch_logs")
    graph.add_edge("extract_context", "fetch_traces")
    graph.add_edge("extract_context", "fetch_kubernetes")
    graph.add_edge("extract_context", "fetch_correlated_alerts")
    graph.add_edge("extract_context", "fetch_historical_solutions")

    # Parallel fan-in: all observability nodes → fetch_github
    graph.add_edge("fetch_metrics", "fetch_github")
    graph.add_edge("fetch_logs", "fetch_github")
    graph.add_edge("fetch_traces", "fetch_github")
    graph.add_edge("fetch_kubernetes", "fetch_github")
    graph.add_edge("fetch_correlated_alerts", "fetch_github")
    graph.add_edge("fetch_historical_solutions", "fetch_github")

    # Sequential: fetch_github → synthesize → post_to_slack → END
    graph.add_edge("fetch_github", "synthesize")
    graph.add_edge("synthesize", "post_to_slack")
    graph.add_edge("post_to_slack", END)

    # Compile the graph
    compiled = graph.compile()

    log.info("graph compiled successfully")
    return compiled


def get_graph() -> CompiledStateGraph:
    """
    Get the compiled agent graph (singleton).

    Returns a cached instance of the compiled graph for reuse.

    Returns:
        CompiledStateGraph: Ready-to-execute graph.
    """
    global _compiled_graph

    if _compiled_graph is None:
        _compiled_graph = build_graph()

    return _compiled_graph


def clear_graph_cache() -> None:
    """
    Clear the cached graph.

    Useful for testing or when the graph needs to be rebuilt.
    """
    global _compiled_graph
    _compiled_graph = None


async def run_investigation(state: AgentState) -> AgentState:
    """
    Run a full incident investigation.

    Convenience function that executes the graph with the given state.

    Args:
        state: Initial state with alert context.

    Returns:
        Final state with analysis and all collected data.

    Example:
        >>> from sre_bot.agent.state import AgentState, AlertContext
        >>> alert = AlertContext(
        ...     alert_name="HighErrorRate",
        ...     severity="critical",
        ...     service_name="payment-api",
        ...     namespace="production",
        ...     cluster="main",
        ...     timestamp=datetime.utcnow(),
        ... )
        >>> initial_state = AgentState(alert=alert)
        >>> final_state = await run_investigation(initial_state)
        >>> print(final_state.analysis.summary)
    """
    log = logger.bind(
        component="investigation",
        alert=state.alert.alert_name,
        service=state.alert.service_name,
    )
    log.info("starting investigation")

    graph = get_graph()

    # Run the graph
    final_state = await graph.ainvoke(state)

    log.info(
        "investigation completed",
        has_analysis=final_state.get("analysis") is not None,
        errors=len(final_state.get("errors", [])),
    )

    return final_state


def get_graph_visualization() -> str:
    """
    Get a Mermaid diagram representation of the graph.

    Useful for documentation and debugging.

    Returns:
        Mermaid diagram as string.
    """
    return """
```mermaid
graph TD
    START((Start)) --> extract_context
    extract_context --> fetch_metrics
    extract_context --> fetch_logs
    extract_context --> fetch_traces
    extract_context --> fetch_kubernetes
    extract_context --> fetch_correlated_alerts
    fetch_metrics --> fetch_github
    fetch_logs --> fetch_github
    fetch_traces --> fetch_github
    fetch_kubernetes --> fetch_github
    fetch_correlated_alerts --> fetch_github
    fetch_github --> synthesize
    synthesize --> post_to_slack
    post_to_slack --> END((End))

    style extract_context fill:#e1f5fe
    style fetch_metrics fill:#fff3e0
    style fetch_logs fill:#fff3e0
    style fetch_traces fill:#fff3e0
    style fetch_kubernetes fill:#e3f2fd
    style fetch_correlated_alerts fill:#ffecb3
    style fetch_github fill:#f3e5f5
    style synthesize fill:#e8f5e9
    style post_to_slack fill:#fce4ec
```
"""
