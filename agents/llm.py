"""Gemini explanation step.

The rules decide the route and the decision. Gemini only turns the facts the rules
produced into a short plain-English explanation for the reviewer. If Gemini is off,
or fails after retries, the workflow keeps its template explanation.

Enabled only when LLM_ENABLED=1 and GEMINI_API_KEY is set.
GEMINI_MODEL picks the model (default: gemini-2.5-flash). Check the model name
shown in Google AI Studio if the default is not available for your key.
"""

import os
from typing import Callable, Dict, Optional

PROMPT_RULES = """You write short, plain-English explanations for an insurance claims reviewer.
Follow these rules:
- Use only the facts listed below. Do not add facts.
- Do not change or question the decision. It is final.
- Write at most 3 sentences.
- Refer to the claim by its claim ID only. Do not mention any names."""


def llm_enabled() -> bool:
    return os.environ.get("LLM_ENABLED") == "1" and bool(os.environ.get("GEMINI_API_KEY"))


def build_prompt(facts: Dict[str, object]) -> str:
    lines = [PROMPT_RULES, "", "Facts:"]
    for key, value in facts.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("Write the explanation now.")
    return "\n".join(lines)


def call_gemini(prompt: str) -> str:
    """One Gemini call. Imported here so the rest of the app runs without the SDK."""
    from google import genai

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    response = client.models.generate_content(model=model, contents=prompt)
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response")
    return text


def explain(
    facts: Dict[str, object],
    call: Optional[Callable[[str], str]] = None,
    attempts: int = 2,
) -> Optional[str]:
    """Return Gemini's explanation, or None if Gemini is off or fails every attempt."""
    if not llm_enabled():
        return None
    send = call or call_gemini
    prompt = build_prompt(facts)
    for _ in range(attempts):
        try:
            return send(prompt)
        except Exception:  # noqa: BLE001 - any failure falls back to the template
            continue
    return None
