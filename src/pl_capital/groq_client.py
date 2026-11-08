import json

import groq
from pydantic import ValidationError

from pl_capital.config import GROQ_MODELS, Settings
from pl_capital.errors import PlanningError
from pl_capital.models import Plan
from pl_capital.prompts import SYSTEM_PROMPT


class GroqPlanner:
    def __init__(self, settings: Settings, *, client=None):
        if not settings.api_key:
            raise PlanningError(
                "GROQ_API_KEY is not configured. Set it in the environment or ignored .env."
            )
        self.model = settings.model
        self.client = client or groq.Groq(api_key=settings.api_key, timeout=30.0, max_retries=2)
        self.last_usage = {}

    def plan(
        self, question: str, context: dict, *, previous_portfolio=None, correction=None
    ) -> Plan:
        payload = {
            "question": question,
            "context": context,
            "previous_portfolio": previous_portfolio,
            "validation_correction": correction,
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        if len(encoded) > 45_000:
            raise PlanningError("Planning context exceeds the bounded input budget.")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                reasoning_effort="low",
                stream=False,
                max_completion_tokens=4096,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": encoded},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "portfolio_plan",
                        "strict": True,
                        "schema": Plan.model_json_schema(),
                    },
                },
            )
            self.last_usage = {
                name: getattr(response.usage, name, 0)
                for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
            content = response.choices[0].message.content or ""
            if len(content) > 30_000:
                raise PlanningError("Groq plan exceeds the output budget.")
            return Plan.model_validate_json(content)
        except groq.AuthenticationError as exc:
            raise PlanningError("Groq authentication failed; check the private API key.") from exc
        except groq.PermissionDeniedError as exc:
            raise PlanningError("Groq permission denied for the selected model.") from exc
        except groq.RateLimitError as exc:
            raise PlanningError("Groq rate limit retries exhausted; retry later.") from exc
        except groq.APIConnectionError as exc:
            raise PlanningError(
                "Groq connection failed or timed out after bounded retries."
            ) from exc
        except groq.APIStatusError as exc:
            raise PlanningError(
                f"Groq request failed (HTTP {exc.status_code}); verify model/API availability."
            ) from exc
        except (ValidationError, ValueError, IndexError, TypeError) as exc:
            raise PlanningError(
                "Groq returned an invalid structured plan; no SQL was executed."
            ) from exc

    def set_model(self, model: str):
        if model not in GROQ_MODELS:
            raise PlanningError("Unsupported model. Choose a documented Groq GPT-OSS model.")
        self.model = model

    def close(self):
        self.client.close()
