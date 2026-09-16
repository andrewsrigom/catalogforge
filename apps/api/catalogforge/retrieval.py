from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from .config import settings
from .db import transaction
from .models import Chunk, SourceDocument
from .providers import embeddings


class CatalogRetriever(BaseRetriever):
    workspace_id: str
    identity: dict[str, Any]
    limit: int = 20

    def _get_relevant_documents(self, query, *, run_manager):
        raise NotImplementedError("Use asynchronous retrieval")

    async def _aget_relevant_documents(self, query, *, run_manager):
        vector = await embeddings().aembed_query(query)
        async with transaction() as db:
            base = (
                select(Chunk)
                .join(SourceDocument, Chunk.document_id == SourceDocument.id)
                .where(
                    Chunk.workspace_id == self.workspace_id,
                    SourceDocument.workspace_id == self.workspace_id,
                    SourceDocument.active.is_(True),
                    SourceDocument.status == "ready",
                    Chunk.embedding_space == settings().embedding_space,
                )
            )
            exact = (
                await db.scalars(
                    base.where(
                        or_(
                            Chunk.identifiers["mpn"].astext == self.identity.get("mpn", "---"),
                            (
                                Chunk.identifiers["manufacturer"].astext
                                == self.identity["manufacturer"]
                            )
                            & (Chunk.identifiers["model"].astext == self.identity["model"]),
                        )
                    ).limit(self.limit)
                )
            ).all()
            lexical = (
                await db.scalars(
                    base.where(
                        func.to_tsvector("simple", Chunk.text).op("@@")(
                            func.plainto_tsquery("simple", query)
                        )
                    ).limit(self.limit)
                )
            ).all()
            semantic = (
                await db.scalars(
                    base.order_by(Chunk.embedding.cosine_distance(vector)).limit(self.limit)
                )
            ).all()
            unique = {chunk.id: chunk for chunk in [*exact, *lexical, *semantic]}
            return [
                Document(
                    page_content=c.text,
                    metadata={
                        "id": c.id,
                        "document_id": c.document_id,
                        "identifiers": c.identifiers,
                        "location": c.location,
                    },
                )
                for c in unique.values()
            ]


class RetrievalInput(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


def retrieval_tool(workspace_id: str, identity: dict[str, Any], limit: int):
    retriever = CatalogRetriever(workspace_id=workspace_id, identity=identity, limit=limit)

    @tool(args_schema=RetrievalInput)
    async def search_product_evidence(query: str) -> list[dict[str, Any]]:
        """Search only authorized workspace documents in the configured embedding space."""
        documents = await retriever.ainvoke(query)
        return [{"text": doc.page_content, **doc.metadata} for doc in documents]

    return search_product_evidence
