"""Per-turn tracing and structured logging.

Each REPL turn gets a unique 12-char trace_id. Every LLM call and tool call
during that turn is emitted as a JSON Lines event carrying token counts,
latency, and an estimated cost; at the end of the turn a compact one-line
summary is printed to stderr so the operator can see what just happened
without tailing the file.

Output goes to ``~/.jira_agent/traces.jsonl`` by default. Override the path
with ``JIRA_AGENT_TRACE_FILE`` or disable tracing entirely with
``JIRA_AGENT_TRACE=0`` (also ``off`` / ``false`` / ``no``). ``/trace`` in
the REPL toggles it live.

Design note: the Tracer is *observability*, not load-bearing. Its failure
modes (full disk, permission denied, closed stderr) must never propagate
into ``Agent.chat()`` — ``end_turn`` runs from a ``finally`` block and a
raise here would mask the loop's real return value or real exception.
Both ``end_turn`` and ``_emit`` swallow exceptions and degrade to a
single per-session stderr warning.

Stdlib only; no new dependencies.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tools import TOOL_TRACE_POLICY

DEFAULT_TRACE_FILE = Path.home() / ".jira_agent" / "traces.jsonl"

# ESTIMATED prices, $/1M tokens (prompt, completion). Scraped from provider
# price pages at the time of writing — these *will* go stale as providers
# change tiers. Refresh by hand when numbers stop matching reality. Keys
# are *base* model names; ``_normalize_model`` strips any OpenRouter slug
# variant suffix (e.g. ``:free``, ``:nitro``) before lookup.
#
# Conservative philosophy: an unknown model emits $0 with
# ``pricing_unknown=true`` rather than a guess. Operators grep traces for
# unknowns and extend this table.
PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-4o":                     (2.50, 10.00),
    "openai/gpt-4o-mini":                (0.15,  0.60),
    "anthropic/claude-3.5-sonnet":       (3.00, 15.00),
    "anthropic/claude-3-haiku":          (0.25,  1.25),
    "google/gemini-2.0-flash":           (0.10,  0.40),
    "google/gemma-3-27b-it":             (0.0,   0.0),    # free tier
    "google/gemma-4-31b-it":             (0.0,   0.0),    # free; ':free' slug also handled
    "meta-llama/llama-3.3-70b-instruct": (0.13,  0.39),
}

# OpenRouter slug variant suffixes. ``:free`` is the only one that changes
# price; the others are routing hints on the same underlying model. Add
# new variants here as encountered. Anything not in this set is left
# attached to the slug so the lookup falls through to pricing_unknown=true
# — that's the operator's signal to extend either this set or PRICING
# rather than silently masking what may be a different model.
_KNOWN_VARIANTS = frozenset({"free", "beta", "nitro", "floor"})


def _normalize_model(model: str) -> tuple[str, bool]:
    """Strip a known OpenRouter variant suffix.

    Returns ``(base_name, is_explicit_free)``. Unknown variants are NOT
    stripped — the full slug is returned so the lookup misses.
    """
    if ":" not in model:
        return model, False
    base, variant = model.rsplit(":", 1)
    if variant == "free":
        return base, True
    if variant in _KNOWN_VARIANTS:
        return base, False
    return model, False


def _price(
    model: str, prompt_tokens: int, completion_tokens: int
) -> tuple[float, bool]:
    """Returns ``(estimated_cost_usd, pricing_unknown)``."""
    base, is_free = _normalize_model(model)
    if is_free:
        return 0.0, False  # confidently free, not an unknown
    if base not in PRICING:
        return 0.0, True
    p_in, p_out = PRICING[base]
    return (prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000, False


def _redacted(value: Any) -> str:
    return f"<redacted len={len(str(value))}>"


def _redact_args(tool_name: str, args: dict) -> dict:
    """Apply ``TOOL_TRACE_POLICY`` to a parsed args dict, fail-closed.

    Keys listed under ``policy['safe']`` are kept verbatim; everything
    else — declared ``redact`` keys *and* unknown keys — becomes
    ``<redacted len=N>``. Unknown tools redact all values, so a schema
    change without a policy update can't silently leak free text.
    """
    policy = TOOL_TRACE_POLICY.get(tool_name)
    if policy is None:
        return {k: _redacted(v) for k, v in args.items()}
    safe = set(policy["safe"])
    return {k: (v if k in safe else _redacted(v)) for k, v in args.items()}


def _truncate_error(s: str | None, limit: int = 200) -> str | None:
    """Bound error strings. Jira error bodies are unbounded and can carry
    untrusted free text; this caps them so they don't bloat traces."""
    if s is None:
        return None
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


@dataclass
class TurnTrace:
    """In-flight aggregate for the current turn. Mutated by record_*."""

    trace_id: str
    turn: int
    started_at: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0


class Tracer:
    """Per-session tracer.

    Owns one in-flight :class:`TurnTrace` between ``start_turn`` and
    ``end_turn``. All emit paths are gated by ``self._enabled``; flipping
    it is the ``/trace`` slash command's job.

    Invariant: ``event_count`` equals the number of lines this Tracer has
    successfully appended to ``self._path`` this session — so ``/trace
    status`` truthfully answers "how much did I write."
    """

    def __init__(self, path: Path | None, enabled: bool) -> None:
        self._path = path
        self._enabled = enabled
        self._turn_count = 0
        self._event_count = 0
        self._current: TurnTrace | None = None
        self._warned = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def event_count(self) -> int:
        return self._event_count

    def toggle(self) -> bool:
        self._enabled = not self._enabled
        return self._enabled

    def start_turn(self) -> TurnTrace:
        # ``_turn_count`` increments unconditionally: the agent calls
        # start_turn every turn and verification relies on monotonic turn
        # numbers across off-mode toggles.
        self._turn_count += 1
        self._current = TurnTrace(
            trace_id=uuid.uuid4().hex[:12],
            turn=self._turn_count,
            started_at=time.time(),
        )
        return self._current

    def end_turn(self) -> None:
        # Defensive: this runs from Agent.chat()'s finally block. If it
        # raised, it would mask the loop's real return value or real
        # exception — the opposite of what telemetry should do.
        try:
            t = self._current
            if t is None:
                return
            if self._enabled:
                elapsed_ms = (time.time() - t.started_at) * 1000
                print(
                    f"[trace {t.trace_id}] turn={t.turn} "
                    f"llm={t.llm_calls} tools={t.tool_calls} "
                    f"tokens={t.prompt_tokens}+{t.completion_tokens} "
                    f"cost=${t.cost_usd:.4f} in {elapsed_ms:.0f}ms",
                    file=sys.stderr,
                )
        except Exception as e:  # pragma: no cover — defensive backstop
            self._warn_once(f"end_turn failed: {e}")
        finally:
            self._current = None

    def record_llm_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        tool_calls_emitted: int,
    ) -> None:
        cost, pricing_unknown = _price(model, prompt_tokens, completion_tokens)
        if self._current is not None:
            self._current.llm_calls += 1
            self._current.prompt_tokens += prompt_tokens
            self._current.completion_tokens += completion_tokens
            self._current.cost_usd += cost
        record = self._envelope("llm_call")
        record["model"] = model
        record["prompt_tokens"] = prompt_tokens
        record["completion_tokens"] = completion_tokens
        record["cost_usd"] = cost
        record["pricing_unknown"] = pricing_unknown
        record["latency_ms"] = latency_ms
        record["tool_calls_emitted"] = tool_calls_emitted
        self._emit(record)

    def record_tool_call(
        self,
        name: str,
        args: dict | None,
        ok: bool,
        error: str | None,
        latency_ms: float,
        raw_args_size: int = 0,
    ) -> None:
        """Record a tool dispatch.

        ``args=None`` is the explicit signal that the agent could not
        parse ``tool_call.function.arguments``; in that case the record
        carries shape-only metadata (``args_parse_error``, ``arg_keys``,
        ``arguments_size``) and the raw malformed string is *never*
        given to the tracer.
        """
        if self._current is not None:
            self._current.tool_calls += 1
        record = self._envelope("tool_call")
        record["name"] = name
        if args is None:
            record["args_parse_error"] = True
            record["arg_keys"] = []
            record["arguments_size"] = raw_args_size
        else:
            record["args"] = _redact_args(name, args)
        record["ok"] = ok
        record["error"] = _truncate_error(error)
        record["latency_ms"] = latency_ms
        self._emit(record)

    def _envelope(self, event_type: str) -> dict[str, Any]:
        record: dict[str, Any] = {"event": event_type}
        if self._current is not None:
            record["trace_id"] = self._current.trace_id
            record["turn"] = self._current.turn
        record["ts"] = time.time()
        return record

    def _emit(self, record: dict[str, Any]) -> None:
        if not self._enabled or self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            # Disk full, permission denied, parent path is a file, etc.
            # Telemetry must not crash the agent — degrade silently after
            # one warning so the operator knows the file is stale.
            self._warn_once(f"trace write failed ({self._path}): {e}")
            return
        self._event_count += 1

    def _warn_once(self, msg: str) -> None:
        if self._warned:
            return
        self._warned = True
        print(f"(tracer warning: {msg})", file=sys.stderr)


def tracer_from_env() -> Tracer:
    """Build a :class:`Tracer` from ``JIRA_AGENT_TRACE`` /
    ``JIRA_AGENT_TRACE_FILE`` environment variables.

    Defaults: tracing on, output to ``~/.jira_agent/traces.jsonl``.
    ``JIRA_AGENT_TRACE`` is interpreted permissively — ``0``, ``off``,
    ``false``, ``no``, or empty string disable; anything else enables.
    """
    raw = os.getenv("JIRA_AGENT_TRACE", "1").strip().lower()
    enabled = raw not in {"0", "off", "false", "no", ""}
    custom = os.getenv("JIRA_AGENT_TRACE_FILE")
    path = Path(custom).expanduser() if custom else DEFAULT_TRACE_FILE
    return Tracer(path=path, enabled=enabled)
