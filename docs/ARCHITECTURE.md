# Architecture and consistency

## System

~~~mermaid
flowchart LR
  Browser[Vue 3 workspace] -->|Session + workspace + CSRF| API[FastAPI]
  API --> Services[Application services]
  Services --> DB[(PostgreSQL business tables)]
  Services --> Storage[Local storage interface]
  Services --> Outbox[Transactional outbox]
  Outbox --> Dispatcher[Worker dispatcher]
  Dispatcher --> Queue[Procrastinate PostgreSQL queue]
  Queue --> Worker[Independent worker process]
  Worker --> Ingest[Ingestion StateGraph]
  Worker --> Enrich[Per-product StateGraph]
  Ingest --> DB
  Enrich --> DB
  Worker --> Checkpoints[(Separate checkpoints schema)]
  Ingest --> LC[LangChain documents and embeddings]
  Enrich --> LC2[LangChain retriever, typed tool and structured model]
~~~

FastAPI handlers authenticate and delegate business rules. SQLAlchemy models are separate from Pydantic HTTP and extraction contracts. Vue uses Composition API/script setup, Vue Router and TanStack Query. A small module keeps the session/selected workspace; Pinia is unnecessary for the present client state.

Business modules cover identity/workspaces, catalog imports, immutable original rows, product revisions, category versions, documents, searchable chunks, batches/runs, candidates/evidence, reviews, exports, events and audit. Attribute definitions live as validated JSONB in immutable schema versions. Composite foreign keys enforce workspace relationships.

## Ingestion graph

~~~mermaid
flowchart TD
  A[Validate stored upload and hash] --> B[Extract text and page/row/section]
  B --> C[Reject unsupported/empty content]
  C --> D[Split while preserving record context]
  D --> E[Extract explicit identity metadata]
  E --> F[Generate embeddings]
  F --> G[Persist chunks and mark ready]
~~~

Uploading validates size/type, stores bytes through the storage interface and commits a content-hash-unique document plus outbox request. The graph rechecks the stored hash. PDFs retain page numbers; CSV records retain row numbers. TXT records can be separated by a line containing three hyphens. Long single records use LangChain RecursiveCharacterTextSplitter.

Ambiguous sections with multiple explicit identities cannot establish an exact match. Scanned/empty PDFs are rejected. Duplicate bytes reuse a workspace document; a new same-name document receives another version and supersedes older versions after it becomes ready.

Fixture embeddings are a deterministic 64-dimensional hash space. Real embeddings use a separately configured model and dimension. SQL filters the exact space before cosine ordering. Reindex retains chunk IDs/text and changes only vectors; source revision increments invalidate pending proposals.

## Enrichment graph

~~~mermaid
flowchart TD
  Inspect[Inspect original and missing fields] --> Retrieve[Hybrid retrieval]
  Retrieve --> Identity[Exact or explicit family applicability]
  Identity --> Extract[Structured candidate extraction]
  Extract --> Validate[Normalize, verify citations and compare values]
  Validate -->|Unresolved and budget remains| Retrieve
  Validate -->|Budget exhausted or sufficient| Persist[Persist candidates and evidence]
  Persist --> Review[Interrupt for human review]
  Review --> Apply[Validate decision and apply transactionally]
  Apply -->|Pending fields remain| Review
  Apply -->|All resolved| Refresh[Refresh product search text]
  Refresh --> Complete[Complete]
~~~

LangGraph owns state transitions, checkpoints, bounded retrieval loops and interrupt/resume. LangChain owns embeddings, document processing, a workspace-scoped BaseRetriever, a Pydantic-input search tool, and structured extraction through ChatOpenAI or the explicit deterministic provider replacement. There is no multi-agent planner.

Retrieval combines exact MPN/manufacturer/model queries, PostgreSQL lexical matching and pgvector similarity. Semantic ranking never authorizes identity. Manufacturer/model and explicit variant applicability are required; contradictory MPN, size or coating rejects the passage. Family passages need explicit applicable variants.

Only referenced, run-available workspace chunks can become evidence. The quote must occur verbatim in the chunk and contain the raw proposed value. Candidates retain raw/normalized values, original values, validation outcomes, conflicts and evidence references. Unknowns become insufficient-evidence records, without invented values or certifications.

## Durable execution and transactions

There is **no exactly-once claim**.

1. API transactions commit business state and outbox rows together.
2. The dispatcher locks undelivered outbox rows, defers jobs to Procrastinate, then marks delivery. A crash between queue insertion and commit can deliver twice.
3. Queue locks serialize jobs for the same workspace/entity. Graph nodes reuse immutable identifiers and uniqueness constraints; repeated jobs at a saved interrupt do not duplicate candidates.
4. LangGraph checkpoints commit independently from business transactions. Nodes that mutate business state are replay-safe. A worker can recover a graph after a business commit that preceded its next checkpoint.
5. Review submission binds an idempotency key to an exact request hash, proposal versions, product revision and interrupt ID. It creates immutable decisions and a resume outbox row.
6. The resumed graph rechecks workspace membership, reviewer permission, current schema/source/product revision, proposal status and evidence. Approval, product revision, alternative rejection, audit and review-applied marker commit together.
7. On replay, an already-applied review returns the remaining pending count. Another interruption is persisted for remaining fields. A new source/schema/product change requires a new revalidation run.
8. Procrastinate's max_attempts parameter observes prior retries. The configured value 2 produces three total executions, verified against recorded events. Provider calls have one retry. Retrieval is at most two rounds by default; worker concurrency is two and active invocation timeout is 180 seconds.
9. A dispatcher sweep discovers stalled worker jobs using heartbeats and retries within the attempt budget. Graceful restart at a review interrupt is verified by both checkpoint ID and candidate identity. Cancellation is checked between nodes; it does not revoke an external request already in flight.

Checkpointer setup uses AsyncPostgresSaver.setup() in the checkpoints schema. Procrastinate schema creation is guarded by a PostgreSQL advisory lock and existence check. Alembic manages only business tables, the vector extension and the workflow-event sequence. Queue/checkpoint library upgrades require their documented migration procedure; changing package constraints alone is not a schema-upgrade process.

## Review and export

Field-level approve/reject and explicit selected-supported bulk approval are available. Conflicting approvals need reasons. Approving one alternative rejects the others. Manual values are normalized and validated, flagged as manual, and never claimed to be supported by the source quote.

Existing imported fields cannot be overwritten. Contradictions are review exceptions. Completeness counts required fields; validation failures and approved source-evidence coverage are independent. Manual edits do not count as source-evidence coverage.

Exports acquire the workspace transaction lock and write an immutable ZIP. CSV merges only original values and approved empty-field additions, preserving original unmapped columns. JSON reports include schema/proposal/product revisions, review actors, decisions, raw values, validation, conflicts and sources. Formula-like CSV cells receive an apostrophe for spreadsheet safety.

## Authorization and UI updates

Cookies are HTTP-only, SameSite Strict and server-side session tokens are stored as hashes. Passwords use Argon2id. Write requests require CSRF tokens and same-origin checks. Viewers are read-only. Workspace IDs on requests are checked against memberships before all data, file and resume operations.

The browser polls active pages every two seconds and diagnostics every four seconds. Events have persistent numeric IDs and support an after cursor. Polling avoids SSE session/reconnect complexity but adds bounded request load and up to a polling interval of visible latency. Expired sessions cannot retrieve events or resume workflows.


## Everyday-use consistency update

HTTP database dependencies use FastAPI `Depends(scope="function")`. The transaction commits before response headers are sent. Commit failures therefore produce an error response instead of an acknowledged write followed by a transient 404. This follows the official lifecycle: https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope .

Cancel, retry, revalidate and review submission acquire workspace before run locks. Application checks cancellation again inside its locked transaction. Revalidating a completed run preserves the historical completion. Resume jobs receive priority 100; document ingestion receives priority 10 and background enrichment remains priority 0, so a human decision need not wait behind an entire queued catalog. Active jobs are not preempted.

Stalled-job recovery is serialized by an advisory transaction lock. When the execution budget is exhausted, business failure state commits before the queue job is finalized; a crash between these steps can be retried by the next sweep. Already completed or paused business outcomes are preserved. Queue/checkpoint/business commits remain separate, with no exactly-once execution claim.

Guided examples are deterministic fixtures installed atomically into a per-user workspace identified by UUIDv5. All import, source ingestion, retrieval, enrichment and review operations use the same application services. Repeated setup or start requests reuse their existing workspace/run. Fixture setup and new example runs are blocked in real mode, avoiding accidental paid model calls.
