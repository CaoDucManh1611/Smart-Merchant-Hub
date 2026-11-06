"""One tenant/configuration contract for knowledge retrieval on serving paths."""
from time import perf_counter
from functools import wraps
from inspect import signature

from app.rag.agentic_controller import (
    corrective_retry_decision, evidence_quality, load_rag_runtime_options,
)
from app.rag.catalog_filters import extract_query_hard_filters

CONTRACT_VERSION = "shop_retrieval_v1"


def bounded_turn(operation):
    """Cover shortcuts, planner and fallback with the same turn budget/trace."""
    def decorate(function):
        parameters = signature(function)
        @wraps(function)
        def wrapped(*args, **kwargs):
            from app.rag.turn_budget import turn_budget
            from app.rag.run_logger import RagRunLog
            inputs = parameters.bind_partial(*args, **kwargs).arguments
            with turn_budget() as budget, RagRunLog(
                operation + "_entry", business_id=inputs.get("business_id"),
                conversation_id=inputs.get("conversation_id", getattr(inputs.get("conversation"), "id", None)),
                query_preview=inputs.get("query", inputs.get("query_text", "")),
                retrieval_contract=CONTRACT_VERSION,
            ) as run:
                try:
                    result = function(*args, **kwargs)
                    run.update(result_route=getattr(result, "status", None))
                    return result
                finally:
                    run.update(**budget.snapshot())
        return wrapped
    return decorate


def retrieve_shop_knowledge(*, query, db, business_id, diagnostics=None,
                            hard_filters=None, retrieval_mode=None,
                            timeout_seconds=None, enable_ppr=False,
                            adaptive=True, **kwargs):
    """Keep caller constraints through one bounded, opt-in corrective retry.

    Offline experiments still call retriever.retrieve directly. Serving always
    disables PPR until a separately evaluated implementation earns activation.
    Existing auto-reply owns its shadow diagnostics and passes adaptive=False.
    """
    from app.rag.retriever import retrieve, _retry_retrieval_mode

    if type(business_id) is not int or business_id <= 0:
        raise ValueError("business_id_required")
    options = load_rag_runtime_options(db, business_id)
    mode = retrieval_mode or options.retrieval_mode
    if mode not in {"bm25", "hybrid", "auto"}:
        raise ValueError("invalid_serving_retrieval_mode")
    filters = extract_query_hard_filters(query) if hard_filters is None else hard_filters
    trace = diagnostics if diagnostics is not None else {}
    timeout = min(float(timeout_seconds or options.timeout_seconds), options.timeout_seconds)
    from app.rag.turn_budget import remaining_seconds
    timeout = remaining_seconds(timeout)
    started = perf_counter()
    trace.update(retrieval_contract=CONTRACT_VERSION, effective_retrieval_mode=mode,
                 serving_ppr_enabled=False)
    chunks = retrieve(query=query, db=db, business_id=business_id,
                      diagnostics=trace, hard_filters=filters,
                      retrieval_mode=mode, enable_ppr=False,
                      timeout_seconds=timeout, **kwargs)
    if not adaptive:
        return chunks
    retry, reason, expanded = corrective_retry_decision(
        query, chunks, agentic_mode=options.agentic_mode, has_image=False,
        is_casual=False, tool_calls=1, max_tool_calls=min(options.max_tool_calls, 2),
        elapsed_seconds=perf_counter()-started, timeout_seconds=timeout,
        threshold=options.retry_threshold,
    )
    trace.update(adaptive_mode=options.agentic_mode, adaptive_reason=reason,
                 adaptive_would_retry=retry, adaptive_retry_selected=False)
    if retry and options.agentic_mode != "decision_shadow":
        retry_trace = {}
        try:
            remaining = remaining_seconds(timeout - (perf_counter()-started))
            candidate = retrieve(query=expanded, db=db, business_id=business_id,
                                 diagnostics=retry_trace, hard_filters=filters,
                                 retrieval_mode=_retry_retrieval_mode(mode, trace),
                                 enable_ppr=False, timeout_seconds=remaining, **kwargs)
        except Exception as error:
            trace.update(adaptive_error_type=type(error).__name__)
            return chunks
        trace.update(adaptive_retry_chunk_ids=[c.chunk_id for c in candidate])
        # Ranking signals are comparable only in the same retrieval mode.
        if (options.agentic_mode == "active"
                and _retry_retrieval_mode(mode, trace) == mode
                and evidence_quality(candidate) > evidence_quality(chunks)):
            chunks = candidate
            trace.update(retry_trace)
            trace["adaptive_retry_selected"] = True
    trace["adaptive_ms"] = round((perf_counter()-started)*1000, 2)
    return chunks
