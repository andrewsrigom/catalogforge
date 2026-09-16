import csv
import hashlib
import io
from typing import Any, TypedDict

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, StateGraph
from pypdf import PdfReader
from sqlalchemy import select

from .config import settings
from .db import transaction
from .models import Chunk, SourceDocument, WorkflowEvent
from .providers import embeddings, identify
from .services import get_scoped, get_workspace_lock
from .storage import storage


class IngestState(TypedDict, total=False):
    workspace_id: str
    document_id: str
    sections: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    vectors: list[list[float]]


def extract_sections(content: bytes, media_type: str) -> list[dict[str, Any]]:
    if media_type == "pdf":
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are unsupported")
            if len(reader.pages) > 200:
                raise ValueError("PDF limit is 200 pages")
            sections: list[dict[str, Any]] = [
                {"text": page.extract_text() or "", "location": {"page": i + 1}}
                for i, page in enumerate(reader.pages)
            ]
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("The PDF could not be read; upload a valid text-based PDF") from exc
        if not any(len(s["text"].strip()) > 20 for s in sections):
            raise ValueError(
                "Scanned or empty PDF: OCR is not supported. Upload a text-based PDF, TXT or CSV."
            )
        # Do not quietly accept pages that contain images but no text.
        if any(
            not s["text"].strip() and len(reader.pages[i].images) > 0
            for i, s in enumerate(sections)
        ):
            raise ValueError("This PDF contains scanned pages. OCR is not supported.")
        return [s for s in sections if s["text"].strip()]
    text = content.decode("utf-8-sig")
    if "\x00" in text:
        raise ValueError("Binary content is unsupported; use UTF-8 text")
    if media_type == "csv":
        csv_reader = csv.DictReader(io.StringIO(text))
        if not csv_reader.fieldnames or len(set(csv_reader.fieldnames)) != len(
            csv_reader.fieldnames
        ):
            raise ValueError("Source CSV needs unique headers")
        rows = []
        for number, row in enumerate(csv_reader, start=2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"Malformed CSV source row {number}")
            rows.append(
                {
                    "text": "\n".join(f"{k}: {v}" for k, v in row.items()),
                    "location": {"row": number},
                }
            )
        return rows
    return [
        {"text": part.strip(), "location": {"section": f"Record {i + 1}"}}
        for i, part in enumerate(text.split("\n---\n"))
        if part.strip()
    ]


async def ingest_event(state, step):
    async with transaction() as db:
        doc = await get_scoped(db, SourceDocument, state["document_id"], state["workspace_id"])
        doc.status = "processing"
        doc.error = None
        db.add(WorkflowEvent(workspace_id=state["workspace_id"], document_id=doc.id, step=step))


async def validate_upload(state: IngestState):
    await ingest_event(state, "Validating document")
    async with transaction() as db:
        doc = await get_scoped(db, SourceDocument, state["document_id"], state["workspace_id"])
        data = storage().read(doc.storage_key)
        if not data or len(data) > settings().max_upload_bytes:
            raise ValueError("Empty or oversized document")
        if hashlib.sha256(data).hexdigest() != doc.content_hash:
            raise ValueError("Stored document content hash does not match")
    return {}


async def read_document(state: IngestState):
    await ingest_event(state, "Reading documents")
    async with transaction() as db:
        doc = await get_scoped(db, SourceDocument, state["document_id"], state["workspace_id"])
        sections = extract_sections(storage().read(doc.storage_key), doc.media_type)
    if not sections or not any(s["text"].strip() for s in sections):
        raise ValueError("No extractable text was found")
    if sum(len(s["text"]) for s in sections) > 1_000_000:
        raise ValueError("Extracted content exceeds the 1 MB text limit")
    return {"sections": sections}


async def split_document(state: IngestState):
    await ingest_event(state, "Indexing passages")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=3500, chunk_overlap=250, separators=["\n\n", "\n", " "]
    )
    chunks = []
    if len(state["sections"]) > 300:
        raise ValueError("Document limit is 300 sections; split the source before ingestion")
    for section in state["sections"]:
        identifiers = await identify(section["text"])
        if len(section["text"]) <= 4500:
            parts = [Document(page_content=section["text"])]
        else:
            parts = splitter.create_documents([section["text"]])
        for part in parts:
            chunks.append(
                {
                    "text": part.page_content,
                    "location": section["location"],
                    "identifiers": identifiers,
                }
            )
    if len(chunks) > 300:
        raise ValueError("Document limit is 300 passages; split the source into smaller documents")
    return {"chunks": chunks}


async def embed_document(state: IngestState):
    await ingest_event(state, "Creating search index")
    return {"vectors": await embeddings().aembed_documents([c["text"] for c in state["chunks"]])}


async def persist_document(state: IngestState):
    async with transaction() as db:
        workspace = await get_workspace_lock(db, state["workspace_id"])
        doc = await get_scoped(
            db, SourceDocument, state["document_id"], state["workspace_id"], lock=True
        )
        existing = (
            await db.scalars(
                select(Chunk).where(
                    Chunk.workspace_id == state["workspace_id"], Chunk.document_id == doc.id
                )
            )
        ).all()
        # Replays replace vectors in place, retaining evidence identifiers.
        by_ordinal = {chunk.ordinal: chunk for chunk in existing}
        for i, (data, vector) in enumerate(zip(state["chunks"], state["vectors"], strict=True)):
            if i in by_ordinal:
                chunk = by_ordinal[i]
                if chunk.text != data["text"]:
                    raise ValueError("Chunk content changed; upload a new document version")
                chunk.embedding = vector
                chunk.embedding_space = settings().embedding_space
            else:
                db.add(
                    Chunk(
                        workspace_id=state["workspace_id"],
                        document_id=doc.id,
                        ordinal=i,
                        text=data["text"],
                        location=data["location"],
                        identifiers=data["identifiers"],
                        embedding_space=settings().embedding_space,
                        embedding=vector,
                    )
                )
        if doc.status != "ready":
            workspace.source_revision += 1
        doc.status = "ready"
        doc.embedding_space = settings().embedding_space
        doc.metadata_json = {"chunks": len(state["chunks"]), "dimension": len(state["vectors"][0])}
        # A new version supersedes old same-name documents only after it is searchable.
        older = (
            await db.scalars(
                select(SourceDocument).where(
                    SourceDocument.workspace_id == state["workspace_id"],
                    SourceDocument.filename == doc.filename,
                    SourceDocument.version < doc.version,
                )
            )
        ).all()
        for previous in older:
            previous.active = False
        db.add(
            WorkflowEvent(
                workspace_id=state["workspace_id"],
                document_id=doc.id,
                step="Document ready",
                details={"chunks": len(state["chunks"])},
            )
        )
    return {}


def ingestion_graph(checkpointer):
    graph = StateGraph(IngestState)
    for name, node in [
        ("validate", validate_upload),
        ("extract", read_document),
        ("split", split_document),
        ("embed", embed_document),
        ("persist", persist_document),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "validate")
    graph.add_edge("validate", "extract")
    graph.add_edge("extract", "split")
    graph.add_edge("split", "embed")
    graph.add_edge("embed", "persist")
    graph.add_edge("persist", END)
    return graph.compile(checkpointer=checkpointer)
