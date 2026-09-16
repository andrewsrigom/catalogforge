# Engineering decisions

The [product specification](SPECIFICATION.txt) defines the supported workflow. [ARCHITECTURE.md](ARCHITECTURE.md) describes its implementation in detail.

- **Modular monolith:** API and worker run separately, sharing PostgreSQL/pgvector. The queue does not require Redis.
- **Transactional outbox:** HTTP transactions record business changes and requested work together. A dispatcher delivers jobs to Procrastinate. Delivery is at least once; locks and idempotent nodes protect replay.
- **Workflow boundaries:** LangGraph owns transitions, bounded retrieval and review interrupts. LangChain owns document splitting, embeddings, retrieval tools and structured provider output.
- **Storage separation:** business tables and prefixed queue tables use `public`; LangGraph uses a dedicated `checkpoints` schema.
- **Explicit provider modes:** fixtures handle recognized synthetic records. Real chat and embedding integrations never fall back to fixtures.
- **Embedding identity:** mode/model/dimension identify a vector space. Retrieval compares only matching spaces; changes require reindexing.
- **Review consistency:** immutable decisions resume only their recorded interrupt. A product's approvals apply in one transaction guarded by product, schema and evidence versions.
- **Workspace authorization:** sessions, CSRF checks, reviewer permissions and composite foreign keys enforce data boundaries.
- **Polling:** active screens refresh every two seconds. Persistent event IDs support diagnostics without long-lived streams.
- **Original-data preservation:** populated imported fields remain immutable. Manual additions are labeled separately from source-supported values.

## Implementation references

- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/integrations/chat/openai
- https://procrastinate.readthedocs.io/en/stable/quickstart.html
- https://procrastinate.readthedocs.io/en/stable/howto/advanced/locks.html
- https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html
- https://docs.sqlalchemy.org/en/20/dialects/postgresql.html
- https://www.shadcn-vue.com/docs/installation/vite
- https://tanstack.com/query/latest/docs/framework/vue/overview
- https://vite.dev/guide/
