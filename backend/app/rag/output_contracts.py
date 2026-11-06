"""Native schemas validated by the Pydantic dependency already in the app."""
from typing import Literal
from pydantic import BaseModel, ConfigDict


class TurnPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["answer", "chat", "workflow", "handoff", "out_of_scope"]
    tools: list[Literal["catalog", "knowledge", "customer", "orders", "payment", "recommendations"]]
    recommendation_query: str | None


class CalculationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: int
    right: int
    operation: Literal["multiply", "add", "subtract", "divide"]


class AnswerClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    sources: list[int]
    # Internal catalog identities; never rendered to the customer.
    offering_refs: list[str]


class ShopAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[AnswerClaim]
    calculation: CalculationStep | list[CalculationStep] | None
    needs_staff_decision: bool


PLAN_SCHEMA = TurnPlan
ANSWER_SCHEMA = ShopAnswer


def graph_json_completion(messages, *, schema, name, model, default_model):
    """Custom model callables keep the existing test/extension contract."""
    import json
    if model is not default_model:
        return model(messages)
    from app.rag.llm_caller import call_structured
    result = call_structured(messages, schema, schema_name=name)
    if "claims" in result:
        result["answer"] = "\n".join(claim["text"] for claim in result["claims"])
        result["sources"] = list(dict.fromkeys(
            source for claim in result["claims"] for source in claim["sources"]))
    return json.dumps(result, ensure_ascii=False)
