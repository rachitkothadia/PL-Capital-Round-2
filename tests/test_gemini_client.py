import json
from dataclasses import replace

import httpx
import pytest

from pl_capital.errors import PlanningError

PLAN = {
    "intent": "sql_query",
    "sql": "SELECT COUNT(*) FROM portfolios",
    "parameters": [],
    "portfolio": None,
    "message": None,
}


def response(plan=PLAN, finish="STOP"):
    return {
        "candidates": [
            {"finishReason": finish, "content": {"parts": [{"text": json.dumps(plan)}]}}
        ],
        "usageMetadata": {
            "promptTokenCount": 12,
            "candidatesTokenCount": 10,
            "totalTokenCount": 25,
        },
    }


def test_gemini_native_schema_headers_and_usage(settings):
    from pl_capital.gemini_client import GeminiPlanner

    requests = []

    def send(request):
        requests.append(request)
        return httpx.Response(200, json=response())

    client = httpx.Client(transport=httpx.MockTransport(send))
    planner = GeminiPlanner(replace(settings, model="gemini-2.5-pro"), client=client)
    try:
        assert planner.plan("Count portfolios", {"schema": {}}).sql == PLAN["sql"]
        request = requests[0]
        payload = json.loads(request.content)
        assert request.url.host == "generativelanguage.googleapis.com"
        assert "key=" not in str(request.url)
        assert request.headers["x-goog-api-key"] == settings.api_key
        assert settings.api_key not in request.content.decode()
        assert payload["generationConfig"]["responseJsonSchema"]["additionalProperties"] is False
        assert payload["generationConfig"]["thinkingConfig"]["includeThoughts"] is False
        assert planner.last_usage["total_tokens"] == 25
    finally:
        planner.close()


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_provider_errors_hide_body_and_retry_with_bounds(settings, monkeypatch, status):
    from pl_capital.gemini_client import GeminiPlanner

    sleeps = []
    calls = []
    monkeypatch.setattr("pl_capital.gemini_client.time.sleep", sleeps.append)

    def send(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"error": {"message": "sensitive-provider-body"}},
            headers={"retry-after": "1"},
        )

    planner = GeminiPlanner(
        replace(settings, model="gemini-2.5-pro"),
        client=httpx.Client(transport=httpx.MockTransport(send)),
    )
    try:
        with pytest.raises(PlanningError) as error:
            planner.plan("count", {})
        assert "sensitive-provider-body" not in str(error.value)
        assert settings.api_key not in str(error.value)
        assert len(calls) == (3 if status in {429, 500} else 1)
        assert all(delay >= 1 for delay in sleeps)
    finally:
        planner.close()


@pytest.mark.parametrize(
    "body",
    [
        response({"bogus": "not a plan"}),
        response(finish="MAX_TOKENS"),
        {"candidates": []},
        response({**PLAN, "sql": "x" * 31000}),
    ],
)
def test_invalid_incomplete_or_excessive_output_never_becomes_a_plan(settings, body):
    from pl_capital.gemini_client import GeminiPlanner

    planner = GeminiPlanner(
        replace(settings, model="gemini-2.5-pro"),
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ),
    )
    try:
        with pytest.raises(PlanningError):
            planner.plan("count", {})
    finally:
        planner.close()


def test_gemini_requires_key_and_rejects_untrusted_model_path(settings):
    from pl_capital.gemini_client import GeminiPlanner

    with pytest.raises(PlanningError):
        GeminiPlanner(replace(settings, model="gemini-2.5-pro", api_key=""))
    with pytest.raises(PlanningError):
        GeminiPlanner(replace(settings, model="../../remote-host"))


def test_streamed_response_is_read_once_without_buffer_assumptions(settings):
    from pl_capital.gemini_client import GeminiPlanner

    body = json.dumps(response()).encode()
    planner = GeminiPlanner(
        replace(settings, model="gemini-2.5-pro"),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, stream=httpx.ByteStream(body))
            )
        ),
    )
    try:
        assert planner.plan("count", {}).intent == "sql_query"
    finally:
        planner.close()


def test_billing_failure_is_actionable_and_not_retried(settings):
    from pl_capital.gemini_client import GeminiPlanner

    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(
            403, json={"error": {"message": "Your billing account has an outstanding balance."}}
        )

    planner = GeminiPlanner(
        replace(settings, model="gemini-2.5-pro"),
        client=httpx.Client(transport=httpx.MockTransport(send)),
    )
    try:
        with pytest.raises(PlanningError, match="outstanding balance"):
            planner.plan("count", {})
        assert len(calls) == 1
    finally:
        planner.close()


def test_long_retry_instruction_does_not_retry_early(settings, monkeypatch):
    from pl_capital.gemini_client import GeminiPlanner

    sleeps = []
    calls = []
    monkeypatch.setattr("pl_capital.gemini_client.time.sleep", sleeps.append)

    def send(request):
        calls.append(request)
        return httpx.Response(429, json={"error": {"details": [{"retryDelay": "65s"}]}})

    planner = GeminiPlanner(
        replace(settings, model="gemini-2.5-pro"),
        client=httpx.Client(transport=httpx.MockTransport(send)),
    )
    try:
        with pytest.raises(PlanningError):
            planner.plan("count", {})
        assert len(calls) == 1 and sleeps == []
    finally:
        planner.close()


def test_network_retries_are_bounded_and_safe(settings, monkeypatch):
    from pl_capital.gemini_client import GeminiPlanner

    calls = []
    monkeypatch.setattr("pl_capital.gemini_client.time.sleep", lambda _: None)

    def send(request):
        calls.append(request)
        raise httpx.ReadTimeout("private network detail", request=request)

    planner = GeminiPlanner(
        replace(settings, model="gemini-2.5-pro"),
        client=httpx.Client(transport=httpx.MockTransport(send)),
    )
    try:
        with pytest.raises(PlanningError, match="bounded retries") as error:
            planner.plan("count", {})
        assert "private network detail" not in str(error.value)
        assert len(calls) == 3
    finally:
        planner.close()


def test_input_and_streamed_response_budgets(settings):
    from pl_capital.gemini_client import GeminiPlanner

    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b"x" * 200001))

    planner = GeminiPlanner(
        replace(settings, model="gemini-2.5-pro"),
        client=httpx.Client(transport=httpx.MockTransport(send)),
    )
    try:
        with pytest.raises(PlanningError, match="input budget"):
            planner.plan("x" * 45001, {})
        assert not calls
        with pytest.raises(PlanningError, match="output budget"):
            planner.plan("count", {})
        assert len(calls) == 1
    finally:
        planner.close()
