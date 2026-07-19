"""
LLM client for CallGuard AI — uses OpenRouter free tier.
Supports fallback chain: primary model → fallback model → deterministic.

Free models on OpenRouter (no credit card required):
  - meta-llama/llama-3.1-8b-instruct:free
  - mistralai/mistral-7b-instruct:free
  - google/gemma-2-9b-it:free

Set OPENROUTER_API_KEY in your environment before running.
Get a free key at: https://openrouter.ai
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.error
from typing import Any

OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"

# Free model fallback chain — if first is rate-limited, tries next
FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemma-3-27b-it",
    "meta-llama/llama-3.2-3b-instruct",
]


class LLMClient:
    """
    Thin wrapper around OpenRouter's free-tier chat completions.
    Falls back to deterministic scoring if no API key is set.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.available = bool(self.api_key)
        self._call_count = 0

    def judge(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 400,
    ) -> dict[str, Any]:
        """
        Call the LLM judge. Returns a dict with:
          - score: float 0.0–1.0
          - reasoning: str
          - violations: list[str]
          - model_used: str
          - llm_powered: bool
        """
        if not self.available:
            return self._deterministic_fallback(user_prompt)

        last_error = None
        for model in FREE_MODELS:
            try:
                result = self._call_openrouter(system_prompt, user_prompt, model, max_tokens)
                self._call_count += 1
                return result
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code} from {model}"
                if e.code == 429:
                    continue  # rate limited, try next model
                break
            except Exception as e:
                last_error = str(e)
                break

        # All models failed — fall back gracefully
        fallback = self._deterministic_fallback(user_prompt)
        fallback["fallback_reason"] = last_error
        return fallback

    def _call_openrouter(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1,  # Low temp for consistent evaluation
        }).encode("utf-8")

        req = urllib.request.Request(
            OPENROUTER_BASE,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/callguard-ai",
                "X-Title": "CallGuard AI Evaluator",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        raw_content = data["choices"][0]["message"]["content"].strip()
        parsed = self._parse_judge_response(raw_content)
        parsed["model_used"] = model
        parsed["llm_powered"] = True
        return parsed

    def _parse_judge_response(self, content: str) -> dict[str, Any]:
        """
        Parse JSON from LLM response. Falls back to text parsing if needed.
        The system prompt asks the LLM to respond in JSON.
        """
        # Try to extract JSON block
        try:
            # Handle ```json ... ``` fencing
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content.strip())
        except (json.JSONDecodeError, IndexError):
            pass

        # Text fallback: extract score from "Score: 0.8" patterns
        score = 0.7
        for line in content.lower().splitlines():
            if "score:" in line:
                try:
                    score = float(line.split("score:")[-1].strip().split()[0])
                    score = max(0.0, min(1.0, score))
                    break
                except (ValueError, IndexError):
                    pass

        return {
            "score": score,
            "reasoning": content[:500],
            "violations": [],
        }

    def _deterministic_fallback(self, user_prompt: str) -> dict[str, Any]:
        """
        Used when no API key is set. Signals clearly that no LLM was used.
        Returns a neutral score so the system still runs end-to-end.
        """
        return {
            "score": 0.75,
            "reasoning": (
                "⚠ LLM judge not active — set OPENROUTER_API_KEY for AI-powered evaluation. "
                "Using deterministic fallback score."
            ),
            "violations": [],
            "model_used": "deterministic-fallback",
            "llm_powered": False,
        }


# Module-level singleton — shared across all evaluators in a run
_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def reset_client() -> None:
    """Call between test runs to reset state."""
    global _client
    _client = None
