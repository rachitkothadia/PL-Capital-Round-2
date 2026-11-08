"""Gemini native JSON-schema planner; financial execution stays in local tools."""

import json
import math
import time

import httpx
from pydantic import ValidationError

from pl_capital.config import GEMINI_MODELS, Settings
from pl_capital.errors import PlanningError
from pl_capital.models import Plan
from pl_capital.prompts import SYSTEM_PROMPT


def _retry_delay(response, attempt, payload):
    """Honor provider retry instructions; never retry earlier than requested."""
    try:
        delay = float(response.headers.get("retry-after", 2**attempt))
        for item in payload.get("error", {}).get("details", []):
            if "retryDelay" in item:
                delay = max(delay, float(item["retryDelay"].removesuffix("s")))
        return max(0, delay) if math.isfinite(delay) else float(2**attempt)
    except (ValueError, TypeError, AttributeError):
        return float(2**attempt)


class GeminiPlanner:
    def __init__(self, settings: Settings, *, client=None):
        if settings.model not in GEMINI_MODELS:
            raise PlanningError("Choose a documented Gemini model.")
        if not settings.api_key:
            raise PlanningError(
                "GEMINI_API_KEY is not configured in the environment or ignored .env."
            )
        self.model = settings.model
        self._key = settings.api_key
        self.client = client or httpx.Client(timeout=45, follow_redirects=False)
        self.last_usage = {}

    def set_model(self, model):
        if model not in GEMINI_MODELS:
            raise PlanningError("Choose a documented Gemini model.")
        self.model = model

    def plan(self, question, context, *, previous_portfolio=None, correction=None):
        self.last_usage = {}
        encoded = json.dumps(
            {
                "question": question,
                "context": context,
                "previous_portfolio": previous_portfolio,
                "validation_correction": correction,
            },
            ensure_ascii=False,
        )
        if len(encoded) > 45_000:
            raise PlanningError("Planning context exceeds the bounded input budget.")
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": encoded}]}],
            "generationConfig": {
                "temperature": 0,
                "candidateCount": 1,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
                "responseJsonSchema": Plan.model_json_schema(),
                "thinkingConfig": {"thinkingBudget": 2048, "includeThoughts": False},
            },
        }
        if self.model.startswith("gemini-3") :
            body["generationConfig"].pop("thinkingConfig", None)
        for attempt in range(3):
            try:
                with self.client.stream(
                    "POST",
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                    headers={"x-goog-api-key": self._key},
                    json=body,
                ) as response:
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 200_000:
                            raise PlanningError("Gemini response exceeded its output budget.")
                    try:
                        payload = json.loads(data)
                    except ValueError:
                        payload = {}
                    if response.status_code in {429, 500, 502, 503, 504}:
                        delay = _retry_delay(response, attempt, payload)
                        if attempt < 2 and delay <= 30:
                            time.sleep(delay)
                            continue
                        raise PlanningError(
                            "Gemini rate limit or temporary service failure; retry later."
                        )
                    if (
                        response.status_code == 403
                        and "outstanding balance"
                        in str(payload.get("error", {}).get("message", "")).lower()
                    ):
                        raise PlanningError(
                            "Gemini billing is blocked by an outstanding balance; restore service at https://aistudio.google.com/billing."
                        )
                    if response.status_code in {401, 403}:
                        raise PlanningError(
                            "Gemini authentication or permission denied; check the private API key and model access."
                        )
                    if response.status_code != 200:
                        raise PlanningError(
                            f"Gemini request rejected (HTTP {response.status_code}); verify model and configuration."
                        )
                result = json.loads(data)
                usage = result.get("usageMetadata", {})
                self.last_usage = {
                    "prompt_tokens": usage.get("promptTokenCount", 0),
                    "completion_tokens": usage.get("candidatesTokenCount", 0),
                    "total_tokens": usage.get("totalTokenCount", 0),
                }
                candidate = result.get("candidates", [])[0]
                if candidate.get("finishReason") != "STOP":
                    raise PlanningError(
                        "Gemini returned an incomplete or blocked plan; no SQL was executed."
                    )
                content = "".join(
                    part.get("text", "")
                    for part in candidate["content"]["parts"]
                    if not part.get("thought")
                )
                if len(content) > 30_000:
                    raise PlanningError("Gemini plan exceeds the output budget.")
                return Plan.model_validate_json(content)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise PlanningError("Gemini connection failed after bounded retries.") from None
            except (ValidationError, ValueError, IndexError, KeyError, TypeError, AttributeError):
                raise PlanningError(
                    "Gemini returned an invalid structured plan; no SQL was executed."
                ) from None
        raise PlanningError("Gemini planning retries exhausted.")

    def close(self):
        self.client.close()
