"""Persist reservations before remote calls; unknown outcomes retain their full charge."""

import asyncio
import math
import time
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .config import settings
from .db import transaction
from .models import ProductRun, ProviderBudget, ProviderCall, now, uid


class ProviderLimitError(ValueError):
    pass


class ProviderOperationError(ValueError):
    pass


@dataclass(frozen=True)
class CallScope:
    workspace_id: str
    kind: str
    scope_id: str
    entity_id: str


scope: ContextVar[CallScope | None] = ContextVar("provider_scope", default=None)


def conservative_tokens(text: str) -> int:
    # UTF-8 bytes bound ordinary text tokenization conservatively; chat framing gets margin.
    return len(text.encode("utf-8"))


def prices() -> dict[str, Any] | None:
    cfg = settings()
    if cfg.ai_chat_input_usd_per_million is None:
        return None
    return {
        "chat_input": str(cfg.ai_chat_input_usd_per_million),
        "chat_output": str(cfg.ai_chat_output_usd_per_million),
        "embedding": str(cfg.ai_embedding_usd_per_million),
        "date": cfg.ai_pricing_date,
        "currency": "USD",
        "chat_model": cfg.chat_model,
        "embedding_model": cfg.embedding_model,
    }


def cost_micros(kind: str, input_tokens: int, output_tokens: int, pricing) -> int:
    if pricing is None:
        return 0
    # USD per million tokens numerically equals micro-USD per token.
    incoming = Decimal(pricing["embedding" if kind.startswith("embedding") else "chat_input"])
    outgoing = Decimal(pricing["chat_output"]) if output_tokens else Decimal(0)
    return math.ceil(incoming * input_tokens + outgoing * output_tokens)


async def reserve(kind: str, model: str, input_tokens: int, output_tokens: int) -> str:
    current = scope.get()
    if current is None:
        raise ProviderLimitError("Real provider calls require an authenticated job budget context")
    cfg = settings()
    if input_tokens > cfg.ai_max_input_tokens:
        raise ProviderLimitError("Provider input limit reached; reduce document or batch input")
    pricing = prices()
    reserved_tokens = input_tokens + output_tokens
    reserved_cost = cost_micros(kind, input_tokens, output_tokens, pricing)
    keys = sorted(["workspace", f"{current.kind}:{current.scope_id}"])
    async with transaction() as db:
        if current.kind == "batch":
            run = await db.scalar(
                select(ProductRun).where(
                    ProductRun.id == current.entity_id,
                    ProductRun.workspace_id == current.workspace_id,
                )
            )
            if run is None or run.cancelled:
                raise ProviderLimitError("Run cancelled or unavailable; provider call blocked")
        for key in keys:
            workspace_limit = key == "workspace"
            cap = cfg.ai_workspace_budget_usd if workspace_limit else cfg.ai_scope_budget_usd
            limits = {
                "calls": cfg.ai_workspace_max_calls if workspace_limit else cfg.ai_scope_max_calls,
                "tokens": cfg.ai_workspace_max_tokens
                if workspace_limit
                else cfg.ai_scope_max_tokens,
                "cost_micros": math.floor(cap * 1_000_000) if cap is not None else None,
            }
            await db.execute(
                insert(ProviderBudget)
                .values(
                    id=uid(),
                    created_at=now(),
                    workspace_id=current.workspace_id,
                    scope_key=key,
                    limits=limits,
                    calls=0,
                    charged_tokens=0,
                    charged_cost_micros=0,
                )
                .on_conflict_do_nothing(index_elements=["workspace_id", "scope_key"])
            )
            budget = await db.scalar(
                select(ProviderBudget)
                .where(
                    ProviderBudget.workspace_id == current.workspace_id,
                    ProviderBudget.scope_key == key,
                )
                .with_for_update()
            )
            assert budget is not None
            if (
                budget.calls + 1 > budget.limits["calls"]
                or budget.charged_tokens + reserved_tokens > budget.limits["tokens"]
                or (
                    budget.limits["cost_micros"] is not None
                    and (
                        pricing is None
                        or budget.charged_cost_micros + reserved_cost > budget.limits["cost_micros"]
                    )
                )
            ):
                raise ProviderLimitError(
                    "Persisted AI budget exhausted. Inspect usage before authorizing more work."
                )
            budget.calls += 1
            budget.charged_tokens += reserved_tokens
            budget.charged_cost_micros += reserved_cost
        call_id = uid()
        db.add(
            ProviderCall(
                id=call_id,
                workspace_id=current.workspace_id,
                scope_key=keys[0] if keys[0] != "workspace" else keys[1],
                entity_id=current.entity_id,
                operation=kind,
                model=model,
                status="reserved",
                reserved_tokens=reserved_tokens,
                charged_tokens=reserved_tokens,
                charged_cost_micros=reserved_cost,
                usage=None,
                pricing=pricing,
                duration_ms=None,
                error_code=None,
                finished_at=None,
            )
        )
    return call_id


async def settle(call_id: str, status: str, usage, elapsed: float, error_code=None):
    async with transaction() as db:
        call = await db.get(ProviderCall, call_id, with_for_update=True)
        assert call is not None
        if call.finished_at is not None:
            return
        input_count = usage.get("input_tokens") if isinstance(usage, dict) else None
        output_count = usage.get("output_tokens") if isinstance(usage, dict) else None
        known = all(
            isinstance(n, int) and not isinstance(n, bool) and n >= 0
            for n in [input_count, output_count]
        )
        charged_tokens = (
            int(input_count or 0) + int(output_count or 0) if known else call.reserved_tokens
        )
        charged_cost = (
            cost_micros(call.operation, int(input_count or 0), int(output_count or 0), call.pricing)
            if known
            else call.charged_cost_micros
        )
        for key in sorted(["workspace", call.scope_key]):
            budget = await db.scalar(
                select(ProviderBudget)
                .where(
                    ProviderBudget.workspace_id == call.workspace_id,
                    ProviderBudget.scope_key == key,
                )
                .with_for_update()
            )
            assert budget is not None
            budget.charged_tokens += charged_tokens - call.charged_tokens
            budget.charged_cost_micros += charged_cost - call.charged_cost_micros
        call.charged_tokens, call.charged_cost_micros = charged_tokens, charged_cost
        call.status, call.usage = status, usage if known else None
        call.duration_ms = round(elapsed * 1000)
        call.error_code, call.finished_at = error_code, now()


def classify_error(exc: BaseException) -> tuple[str, bool]:
    import openai

    if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
        return "interrupted", False
    if isinstance(exc, openai.AuthenticationError):
        return "credentials_invalid", False
    if isinstance(exc, openai.RateLimitError):
        return "rate_limited", True
    if isinstance(exc, (openai.APITimeoutError, TimeoutError)):
        return "provider_timeout", True
    if isinstance(exc, openai.APIConnectionError):
        return "provider_unavailable", True
    if isinstance(exc, openai.APIStatusError):
        return (
            "provider_unavailable" if exc.status_code >= 500 else "provider_request_rejected",
            exc.status_code >= 500,
        )
    return "invalid_provider_response", False


async def invoke(kind: str, model: str, text: str, output_tokens: int, operation):
    cfg = settings()
    for attempt in range(cfg.ai_provider_retries + 1):
        call_id = await reserve(
            kind, model, conservative_tokens(text) + (512 if output_tokens else 0), output_tokens
        )
        started = time.monotonic()
        try:
            async with asyncio.timeout(cfg.ai_call_timeout_seconds):
                result, usage = await operation()
        except BaseException as exc:
            code, retry = classify_error(exc)
            await asyncio.shield(
                settle(
                    call_id,
                    "interrupted" if code == "interrupted" else "failed",
                    None,
                    time.monotonic() - started,
                    code,
                )
            )
            if not isinstance(exc, Exception):
                raise
            if retry and attempt < cfg.ai_provider_retries:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise ProviderOperationError(
                f"AI provider: {code}. Inspect provider configuration and usage before retrying."
            ) from None
        await settle(call_id, "succeeded", usage, time.monotonic() - started)
        return result, usage
    raise AssertionError("Unreachable provider attempt")
