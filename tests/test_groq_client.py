import json

import httpx
import pytest
from groq import Groq

from pl_capital.errors import PlanningError


def test_strict_schema_has_no_ambiguous_numeric_union():
    from pl_capital.models import Plan

    value = Plan.model_json_schema()["$defs"]["Parameter"]["properties"]["value"]
    types = {part.get("type") for part in value["anyOf"]}
    assert not {"integer", "number"} <= types


def test_strict_plan_payload_and_usage(settings):
    from pl_capital.groq_client import GroqPlanner

    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        plan = {
            "intent": "sql_query",
            "sql": "SELECT COUNT(*) FROM portfolios",
            "parameters": [],
            "portfolio": None,
            "message": None,
        }
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": settings.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(plan)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 10, "total_tokens": 22},
            },
        )

    client = Groq(
        api_key="test-only", http_client=httpx.Client(transport=httpx.MockTransport(respond))
    )
    planner = GroqPlanner(settings, client=client)
    plan = planner.plan("count portfolios", {"schema": {}})
    assert plan.intent == "sql_query"
    assert captured[0]["stream"] is False
    assert captured[0]["temperature"] == 0
    assert captured[0]["response_format"]["json_schema"]["strict"] is True
    assert planner.last_usage["total_tokens"] == 22
    client.close()


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_sdk_errors_never_expose_headers_or_body(settings, status):
    from pl_capital.groq_client import GroqPlanner

    count = []

    def respond(request):
        count.append(1)
        return httpx.Response(
            status,
            json={"error": {"message": "secret-from-response-body"}},
            headers={"retry-after": "0"},
        )

    client = Groq(
        api_key="test-only",
        max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    planner = GroqPlanner(settings, client=client)
    with pytest.raises(PlanningError) as caught:
        planner.plan("count", {})
    assert "secret-from-response-body" not in str(caught.value)
    assert len(count) <= 3
    client.close()


def test_missing_key_does_not_call_network(settings):
    from dataclasses import replace

    from pl_capital.groq_client import GroqPlanner

    with pytest.raises(PlanningError, match="GROQ_API_KEY"):
        GroqPlanner(replace(settings, api_key=""))
