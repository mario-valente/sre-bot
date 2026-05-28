"""Node for fetching historical solutions from learned incidents."""

import structlog

from sre_bot.agent.state import (
    AgentState,
    HistoricalSolution,
    HistoricalSolutionsData,
    StateUpdate,
)
from sre_bot.db.repository import LearnedSolutionRepository, get_session

logger = structlog.get_logger()


async def fetch_historical_solutions(state: AgentState) -> StateUpdate:
    """
    Fetch historical solutions from past incidents.

    Searches the learned solutions database for solutions that match
    the current alert, ordered by relevance and success rate.

    Args:
        state: Current agent state with alert context.

    Returns:
        Updated state with historical solutions.
    """
    log = logger.bind(
        node="fetch_historical_solutions",
        service=state.alert.service_name,
        alert=state.alert.alert_name,
    )
    log.info("fetching historical solutions")

    try:
        session = get_session()
        try:
            repo = LearnedSolutionRepository(session)

            solutions = await repo.find_similar(
                alert_name=state.alert.alert_name,
                service_name=state.alert.service_name,
                namespace=state.alert.namespace,
                limit=5,
            )

            if not solutions:
                log.info("no historical solutions found")
                return {
                    "historical_solutions": HistoricalSolutionsData(
                        exact_matches=[],
                        similar_solutions=[],
                        total_found=0,
                    )
                }

            # Categorize solutions
            exact_matches = []
            similar_solutions = []

            for sol in solutions:
                historical = HistoricalSolution(
                    id=sol.id,
                    alert_name=sol.alert_name,
                    service_name=sol.service_name,
                    root_cause=sol.root_cause,
                    solution_steps=sol.solution_steps or [],
                    success_rate=sol.success_rate,
                    times_used=sol.times_used,
                    symptoms=sol.symptoms or [],
                )

                # Exact match: same alert + same service
                if (
                    sol.alert_name == state.alert.alert_name
                    and sol.service_name == state.alert.service_name
                ):
                    exact_matches.append(historical)
                else:
                    similar_solutions.append(historical)

            log.info(
                "historical solutions found",
                exact_matches=len(exact_matches),
                similar_solutions=len(similar_solutions),
            )

            return {
                "historical_solutions": HistoricalSolutionsData(
                    exact_matches=exact_matches,
                    similar_solutions=similar_solutions,
                    total_found=len(solutions),
                )
            }
        finally:
            await session.close()

    except Exception as e:
        log.exception("failed to fetch historical solutions")
        return {
            "historical_solutions": HistoricalSolutionsData(
                exact_matches=[],
                similar_solutions=[],
                total_found=0,
                query_errors=[f"Failed to fetch solutions: {str(e)}"],
            ),
            "errors": [f"Historical solutions fetch failed: {str(e)}"],
        }
