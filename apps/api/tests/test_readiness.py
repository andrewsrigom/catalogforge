import asyncio
import io
import tarfile
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import openai
import pytest
from catalogforge import provider_meter as meter
from catalogforge import providers
from catalogforge.config import Settings, settings
from catalogforge.models import ProviderBudget, ProviderCall, Workspace, uid
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


@pytest.fixture
def isolated_meter(monkeypatch):
    engine = create_async_engine(settings().database_url, poolclass=NullPool)
    session = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction():
        async with session() as db, db.begin():
            yield db

    monkeypatch.setattr(meter, "transaction", transaction)
    monkeypatch.setenv("AI_MODE", "real")
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    settings.cache_clear()
    yield transaction
    settings.cache_clear()


@asynccontextmanager
async def budget_context(transaction, scope_id=None):
    wid = uid()
    async with transaction() as db:
        db.add(Workspace(id=wid, name="Meter verification"))
    token = meter.scope.set(meter.CallScope(wid, "document", scope_id or uid(), uid()))
    try:
        yield wid
    finally:
        meter.scope.reset(token)
        async with transaction() as db:
            await db.execute(delete(ProviderCall).where(ProviderCall.workspace_id == wid))
            await db.execute(delete(ProviderBudget).where(ProviderBudget.workspace_id == wid))
            await db.execute(delete(Workspace).where(Workspace.id == wid))


@pytest.mark.asyncio
async def test_parallel_calls_cannot_overspend_and_reservations_survive_reentry(
    isolated_meter, monkeypatch
):
    monkeypatch.setenv("AI_WORKSPACE_MAX_CALLS", "2")
    settings.cache_clear()
    async with budget_context(isolated_meter) as wid:
        outcomes = await asyncio.gather(
            *(meter.reserve("extract", "test", 100, 20) for _ in range(8)), return_exceptions=True
        )
        calls = [outcome for outcome in outcomes if isinstance(outcome, str)]
        assert len(calls) == 2
        assert all(
            isinstance(outcome, meter.ProviderLimitError)
            for outcome in outcomes
            if not isinstance(outcome, str)
        )
        async with isolated_meter() as db:
            budget = await db.scalar(
                select(ProviderBudget).where(
                    ProviderBudget.workspace_id == wid, ProviderBudget.scope_key == "workspace"
                )
            )
            assert budget.calls == 2 and budget.charged_tokens == 240
        original = meter.scope.get()
        token = meter.scope.set(meter.CallScope(wid, "document", uid(), uid()))
        try:
            with pytest.raises(meter.ProviderLimitError):
                await meter.reserve("embedding_documents", "test", 1, 0)
        finally:
            meter.scope.reset(token)
        assert meter.scope.get() == original
        await meter.settle(calls[0], "succeeded", {"input_tokens": 7, "output_tokens": 3}, 0.1)
        await meter.settle(calls[0], "succeeded", {"input_tokens": 7, "output_tokens": 3}, 0.1)
        async with isolated_meter() as db:
            budget = await db.scalar(
                select(ProviderBudget).where(
                    ProviderBudget.workspace_id == wid, ProviderBudget.scope_key == "workspace"
                )
            )
            assert budget.charged_tokens == 130 and budget.calls == 2


@pytest.mark.asyncio
async def test_all_real_operations_record_usage_without_network(isolated_meter, monkeypatch):
    class FakeChat:
        def with_structured_output(self, schema, **kwargs):
            self.schema = schema
            return self

        async def ainvoke(self, messages):
            result = (
                self.schema()
                if self.schema is providers.ExtractionOutput
                else self.schema(manufacturer="Portwest", model="A120")
            )
            return {
                "parsed": result,
                "raw": SimpleNamespace(usage_metadata={"input_tokens": 10, "output_tokens": 5}),
                "parsing_error": None,
            }

    class FakeEmbeddingClient:
        async def create(self, **kwargs):
            return {
                "data": [
                    {"index": i, "embedding": [0.1] * settings().embedding_dimension}
                    for i, _ in enumerate(kwargs["input"])
                ],
                "usage": {"prompt_tokens": 8},
            }

    monkeypatch.setattr(providers, "chat", FakeChat)
    monkeypatch.setattr(
        providers,
        "OpenAIEmbeddings",
        lambda **kwargs: SimpleNamespace(async_client=FakeEmbeddingClient()),
    )
    async with budget_context(isolated_meter) as wid:
        identity = await providers.identify("Portwest glove A120 information")
        assert identity["model"] == "A120"
        await providers.extract({"identity": identity, "attributes": [], "passages": []})
        assert (
            len(await providers.embeddings().aembed_query("A120")) == settings().embedding_dimension
        )
        assert len(await providers.embeddings().aembed_documents(["A120", "A121"])) == 2
        async with isolated_meter() as db:
            records = (
                await db.scalars(select(ProviderCall).where(ProviderCall.workspace_id == wid))
            ).all()
            assert {r.operation for r in records} == {
                "identify",
                "extract",
                "embedding_query",
                "embedding_documents",
            }
            assert all(r.status == "succeeded" and r.usage for r in records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,retries",
    [
        ("rate", 2),
        ("timeout", 2),
        ("credentials", 1),
        ("malformed", 1),
        ("connection", 2),
        ("server", 2),
    ],
)
async def test_failures_are_bounded_sanitized_and_never_fall_back(isolated_meter, failure, retries):
    attempts = []

    async def request():
        attempts.append(1)
        response = httpx.Response(
            429 if failure == "rate" else 401,
            request=httpx.Request("POST", "https://example.invalid"),
        )
        if failure == "rate":
            raise openai.RateLimitError("private provider response", response=response, body=None)
        if failure == "credentials":
            raise openai.AuthenticationError(
                "private provider response", response=response, body=None
            )
        if failure == "timeout":
            raise TimeoutError("private provider response")
        if failure == "connection":
            raise openai.APIConnectionError(
                message="private provider response", request=response.request
            )
        if failure == "server":
            unavailable = httpx.Response(503, request=response.request)
            raise openai.InternalServerError(
                "private provider response", response=unavailable, body=None
            )
        raise ValueError("private provider response")

    async with budget_context(isolated_meter) as wid:
        with pytest.raises(meter.ProviderOperationError) as error:
            await meter.invoke("extract", "test", "input", 128, request)
        assert "private provider response" not in str(error.value)
        assert len(attempts) == retries
        async with isolated_meter() as db:
            records = (
                await db.scalars(select(ProviderCall).where(ProviderCall.workspace_id == wid))
            ).all()
            assert len(records) == retries
            assert all(
                r.status == "failed" and r.charged_tokens == r.reserved_tokens for r in records
            )


@pytest.mark.asyncio
async def test_cancelled_call_retains_reservation(isolated_meter):
    async def interrupted():
        raise asyncio.CancelledError()

    async with budget_context(isolated_meter) as wid:
        with pytest.raises(asyncio.CancelledError):
            await meter.invoke("extract", "test", "input", 128, interrupted)
        async with isolated_meter() as db:
            call = await db.scalar(select(ProviderCall).where(ProviderCall.workspace_id == wid))
            assert call.status == "interrupted" and call.usage is None
            assert call.charged_tokens == call.reserved_tokens


@pytest.mark.asyncio
async def test_usd_reservation_includes_output_and_is_persistent(isolated_meter, monkeypatch):
    for key, value in {
        "AI_CHAT_INPUT_USD_PER_MILLION": "1",
        "AI_CHAT_OUTPUT_USD_PER_MILLION": "2",
        "AI_EMBEDDING_USD_PER_MILLION": "0.1",
        "AI_PRICING_DATE": "2026-09-16",
        "AI_PRICING_CHAT_MODEL": settings().chat_model,
        "AI_PRICING_EMBEDDING_MODEL": settings().embedding_model,
        "AI_WORKSPACE_BUDGET_USD": "0.00015",
    }.items():
        monkeypatch.setenv(key, value)
    settings.cache_clear()
    async with budget_context(isolated_meter) as wid:
        first = await meter.reserve("extract", settings().chat_model, 100, 20)
        with pytest.raises(meter.ProviderLimitError):
            await meter.reserve("extract", settings().chat_model, 100, 20)
        await meter.settle(first, "succeeded", {"input_tokens": 10, "output_tokens": 2}, 0.1)
        async with isolated_meter() as db:
            budget = await db.scalar(
                select(ProviderBudget).where(
                    ProviderBudget.workspace_id == wid, ProviderBudget.scope_key == "workspace"
                )
            )
            assert budget.charged_cost_micros == 14 and budget.limits["cost_micros"] == 150


def test_pricing_configuration_requires_all_prices_and_matching_models():
    with pytest.raises(ValueError, match="three token prices"):
        Settings(_env_file=None, ai_workspace_budget_usd="1")
    with pytest.raises(ValueError, match="explicitly match"):
        Settings(
            _env_file=None,
            ai_chat_input_usd_per_million="1",
            ai_chat_output_usd_per_million="2",
            ai_embedding_usd_per_million=".1",
            ai_pricing_date="2026-09-16",
        )


def test_operations_are_workspace_scoped_and_readable_by_viewer(workspace):
    from conftest import checked

    own = checked(workspace["client"].get("/operations"))
    assert own["worker"]["healthy"]
    assert checked(workspace["viewer"].get("/operations"))["queue"] == own["queue"]
    workspace["client"].headers["x-workspace-id"] = workspace["other_id"]
    try:
        other = checked(workspace["client"].get("/operations"))
        assert other["queue"]["counts"] == {"runs": {}, "documents": {}}
        assert other["failures"] == [] and other["budgets"] == []
    finally:
        workspace["client"].headers["x-workspace-id"] = workspace["id"]


def test_restore_rejects_path_traversal_before_extracting(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "backup", Path(__file__).resolve().parents[3] / "scripts/backup.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive_path = tmp_path / "uploads.tar"
    with tarfile.open(archive_path, "w") as archive:
        entry = tarfile.TarInfo("../escaped.txt")
        entry.size = 1
        archive.addfile(entry, io.BytesIO(b"x"))
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(ValueError, match="Unsafe"):
        module.extract_uploads(archive_path, target)
    assert not (tmp_path / "escaped.txt").exists()


@pytest.mark.asyncio
async def test_workspace_budget_remains_visible_after_many_documents(isolated_meter):
    from catalogforge.operations import summary

    async with budget_context(isolated_meter) as wid:
        await meter.reserve("identify", "test", 20, 10)
        async with isolated_meter() as db:
            db.add_all(
                [
                    ProviderBudget(
                        workspace_id=wid,
                        scope_key=f"document:extra-{i}",
                        limits={"calls": 2, "tokens": 1000, "cost_micros": None},
                        calls=0,
                        charged_tokens=0,
                        charged_cost_micros=0,
                    )
                    for i in range(110)
                ]
            )
        async with isolated_meter() as db:
            result = await summary(db, wid)
            assert len(result["budgets"]) == 100
            assert result["budgets"][0]["scope"] == "workspace"
            assert result["budgets"][0]["calls"] == 1
