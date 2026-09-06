from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import httpx

from app.models import QueuedQuestion
from app.memory import ConversationTurn
from app.prompts import DEFAULT_SYSTEM_PROMPT


SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT


class ProviderError(RuntimeError):
    pass


class ProviderTimeout(ProviderError):
    pass


_FORBIDDEN_OUTPUT = re.compile(
    r"<unused\d+>|<\|channel\>thought|</?think>|\[TOOL_REQUEST\]|\"tool_calls\"\s*:",
    re.IGNORECASE,
)


def validate_public_output(text: str) -> str:
    """Reject reserved, reasoning or tool payloads before UI/TTS exposure."""
    if _FORBIDDEN_OUTPUT.search(text):
        raise ProviderError("LLM emitted reserved or internal tokens")
    return text


def _prompt_line(value: str, *, limit: int) -> str:
    return " ".join(value.split())[:limit]


def _with_conversation_context(
    task: str, history: Sequence[ConversationTurn] | None
) -> str:
    response_rule = (
        "Antworte ausschließlich auf die aktuelle Nachricht. Nutze den Verlauf nur, "
        "wenn die aktuelle Nachricht erkennbar darauf Bezug nimmt. Erfinde keine "
        "fehlenden Zusammenhänge oder Personen. Wenn der Bezug unklar ist, frage in "
        "einem kurzen Satz nach. Antworte normalerweise in ein bis drei kurzen Sätzen."
    )
    if not history:
        return f"{task}\n\n{response_rule}"
    lines = ["Bisheriger Live-Dialog (nur Kontext, nicht erneut beantworten):"]
    for turn in history:
        name = _prompt_line(turn.display_name, limit=80)
        message = _prompt_line(turn.message, limit=500)
        answer = _prompt_line(turn.answer, limit=800)
        lines.extend((f"Zuschauer {name}: {message}", f"J.A.R.V.I.S.: {answer}"))
    lines.extend(("", f"Aktuelle Nachricht: {task}", "", response_rule))
    return "\n".join(lines)


def build_question_prompt(
    question: QueuedQuestion,
    history: Sequence[ConversationTurn] | None = None,
    *,
    memory_summary: str = "",
    stream_context: dict[str, str] | None = None,
) -> str:
    """Build spoken-live context while keeping gift policy out of the connector."""
    if question.music_request:
        task = (
            f"{question.display_name} wünscht sich Musik: {question.music_request}. "
            "Der Musikwunsch wurde bereits an den lokalen Player übergeben. "
            "Bestätige das freundlich in genau einem sehr kurzen Satz. Behaupte "
            "nicht, dass ein bestimmtes Lied bereits erfolgreich läuft."
        )
        return _structured_prompt(task, history, memory_summary, stream_context)
    if question.is_question:
        base = f"{question.display_name} fragt: {question.message}"
        response_task = f"beantworte danach bevorzugt die Frage: {question.message}"
    else:
        base = (
            f"{question.display_name} schreibt im TikTok-Live: {question.message}. "
            "Reagiere direkt, freundlich und sehr kurz darauf."
        )
        response_task = f"reagiere danach kurz auf die Nachricht: {question.message}"
    gift = question.gift
    if gift is None:
        return _structured_prompt(base, history, memory_summary, stream_context)
    gift_name = gift.name or "ein Geschenk"
    if gift.tier == "spotlight":
        task = (
            f"SPOTLIGHT im TikTok-Live: {question.display_name} hat {gift_name} geschickt. "
            f"Sprich {question.display_name} zuerst kurz persönlich, souverän und "
            "technisch-elegant an. Bedanke dich konkret für das Geschenk und "
            f"{response_task}"
        )
        return _structured_prompt(task, history, memory_summary, stream_context)
    task = (
        f"TikTok-Live Supporter: {question.display_name} hat {gift_name} geschickt. "
        "Bedanke dich in einem sehr kurzen natürlichen Halbsatz und "
        f"{response_task}"
    )
    return _structured_prompt(task, history, memory_summary, stream_context)


def _structured_prompt(
    task: str,
    history: Sequence[ConversationTurn] | None,
    memory_summary: str,
    stream_context: dict[str, str] | None,
) -> str:
    recent = _with_conversation_context(task, history)
    stream_lines = [f"{key}: {_prompt_line(value, limit=300)}" for key, value in (stream_context or {}).items() if value]
    lowered_question = task.casefold()
    read_aloud = any(
        marker in lowered_question
        for marker in ("lies ", "lese ", "vorlesen", "lies mir", "les mir")
    )
    output_contract = (
        "Nur sprechfertiger Text. Bei diesem ausdrücklichen Vorlesewunsch darf die Antwort länger sein. "
        "Lies direkt vor, ohne Einleitung oder Ablenkung. Kein Markdown, keine URLs, keine Rollenmarker, "
        "keine Memory-Pfade und kein internes Reasoning."
        if read_aloud
        else "Nur sprechfertiger Text. Ein bis drei kurze Sätze. Kein Markdown, keine URLs, keine Rollenmarker, keine Memory-Pfade und kein internes Reasoning."
    )
    return "\n\n".join(
        (
            "[SYSTEM PERSONA]\nDie Persona steht ausschließlich in der Systemnachricht.",
            "[LIVE RULES]\nDer Verlauf gehört ausschließlich zum aktuellen TikTok-Nutzer. Vermische niemals andere Zuschauer.",
            "[STREAM CONTEXT]\n" + ("\n".join(stream_lines) or "Kein zusätzlicher Stream-Kontext."),
            "[USER MEMORY SUMMARY]\n" + (memory_summary or "Keine ältere Zusammenfassung."),
            "[RECENT USER CONVERSATION / CURRENT MESSAGE]\n" + recent,
            "[OUTPUT CONTRACT]\n" + output_contract,
        )
    )


@dataclass(slots=True)
class ProviderRequest:
    base_url: str
    api_key: str | None
    model: str
    temperature: float
    context_length: int
    max_output_tokens: int
    stream: bool
    reasoning: bool
    timeout: float
    system_prompt: str = SYSTEM_PROMPT
    http_referer: str = ""
    x_title: str = ""


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, question: str) -> AsyncIterator[str]:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> bool:
        raise NotImplementedError


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, config: ProviderRequest, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.http_referer:
            headers["HTTP-Referer"] = self.config.http_referer
        if self.config.x_title:
            headers["X-Title"] = self.config.x_title
        return headers

    def _payload(self, question: str) -> dict[str, object]:
        if not self.config.model.strip():
            raise ProviderError("No LLM model is configured")
        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": question},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            "stream": self.config.stream,
        }
        if "openrouter.ai" in self.config.base_url.lower():
            payload["reasoning"] = (
                {"enabled": True, "exclude": True}
                if self.config.reasoning
                else {"effort": "none", "exclude": True}
            )
        return payload

    async def generate(self, question: str) -> AsyncIterator[str]:
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            payload = self._payload(question)
            url = f"{self.config.base_url.rstrip('/')}/chat/completions"
            if self.config.stream:
                async with client.stream(
                    "POST",
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.config.timeout,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data)
                            delta = parsed["choices"][0].get("delta", {})
                            content = delta.get("content")
                        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                            continue
                        if isinstance(content, str) and content:
                            validate_public_output(content)
                            yield content
            else:
                response = await client.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if isinstance(content, str) and content:
                    yield validate_public_output(content)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("LLM request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"LLM request failed ({type(exc).__name__})") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def available_models(self) -> list[str]:
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            response = await client.get(
                f"{self.config.base_url.rstrip('/')}/models",
                headers=self._headers(),
                timeout=min(self.config.timeout, 3.0),
            )
            response.raise_for_status()
            payload = response.json()
            models = payload.get("data", []) if isinstance(payload, dict) else []
            return [
                str(item["id"])
                for item in models
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
        except (httpx.HTTPError, ValueError):
            return []
        finally:
            if owns_client:
                await client.aclose()

    async def health(self) -> bool:
        model = self.config.model.strip()
        if not model:
            return False
        return model in await self.available_models()


class LMStudioProvider(OpenAICompatibleProvider):
    """LM Studio native v1 provider with explicit reasoning control."""

    def _native_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return f"{base}/api/v1/chat"

    def _native_payload(self, question: str) -> dict[str, object]:
        if not self.config.model.strip():
            raise ProviderError("No LLM model is configured")
        return {
            "model": self.config.model,
            "input": question,
            "system_prompt": self.config.system_prompt,
            "temperature": self.config.temperature,
            "context_length": self.config.context_length,
            "max_output_tokens": self.config.max_output_tokens,
            "stream": self.config.stream,
            "reasoning": "on" if self.config.reasoning else "off",
            "store": False,
        }

    async def generate(self, question: str) -> AsyncIterator[str]:
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            payload = self._native_payload(question)
            if self.config.stream:
                async with client.stream(
                    "POST",
                    self._native_url(),
                    headers=self._headers(),
                    json=payload,
                    timeout=self.config.timeout,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        event_type = event.get("type")
                        if event_type == "message.delta":
                            content = event.get("content")
                            if isinstance(content, str) and content:
                                yield validate_public_output(content)
                        elif event_type == "error":
                            raise ProviderError("LM Studio streaming request failed")
            else:
                response = await client.post(
                    self._native_url(),
                    headers=self._headers(),
                    json=payload,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()
                body = response.json()
                output = body.get("output", []) if isinstance(body, dict) else []
                messages = [
                    item.get("content", "")
                    for item in output
                    if isinstance(item, dict) and item.get("type") == "message"
                ]
                content = "".join(item for item in messages if isinstance(item, str))
                if content:
                    yield validate_public_output(content)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("LLM request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"LLM request failed ({type(exc).__name__})") from exc
        finally:
            if owns_client:
                await client.aclose()
