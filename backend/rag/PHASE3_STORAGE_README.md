# EduGen AI — Phase 3: Canonical Storage + pgvector

## Scope

This phase adds a standalone PostgreSQL persistence layer for the normalized PDFs, document blocks, chunks, source relationships, file assets and text embeddings created by Phases 1–2. It does not add an API endpoint, frontend upload UI, hybrid retrieval, hierarchical expansion, cross-reference resolution or lesson-generation integration.

## Tables

- `rag_documents`: source hash, document metadata, parser version and source PDF key.
- `rag_document_blocks`: normalized source blocks and section/page provenance.
- `rag_document_assets`: relative managed-file keys, checksums, MIME types and figure associations.
- `rag_document_chunks`: canonical chunk text, context, page range, section path, adjacency and figure keys.
- `rag_chunk_source_blocks`: source/related relationships from each chunk to normalized blocks.
- `rag_chunk_embeddings`: model name, current input-content hash, dimensions and `VECTOR(1536)` embedding. Each chunk retains one current vector per model; re-embedding updates that vector when input content changes.

The migration creates an HNSW cosine index. PostgreSQL must have the pgvector extension available, and the database role needs permission to enable the extension if it is not already enabled. The migration intentionally leaves the extension in place on downgrade.

## Install dependencies

From the active backend environment:

```powershell
python -m pip install -r requirements.txt
```

All database, migration, pgvector and account dependencies are in `requirements.txt`. Review `python -m pip check` after installing; do not blindly downgrade unrelated packages to fix pre-existing conflicts.

### Installing the pgvector extension on Windows

The `pgvector` Python package is only the client. The PostgreSQL **server** also needs the extension. On Windows, with the C++ build tools (Visual Studio Build Tools) installed, open a Command Prompt **as administrator** and run, adjusting the paths to your installation:

```
"C:\Program Files (x86)\Microsoft Visual Studio\2017\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
set "PGROOT=C:\Program Files\PostgreSQL\18"
git clone --branch v0.8.7 https://github.com/pgvector/pgvector.git
cd pgvector
nmake /F Makefile.win
nmake /F Makefile.win install
```

Verify with `select name, default_version from pg_available_extensions where name = 'vector'`. The migration then runs `CREATE EXTENSION vector` itself (the database role must be allowed to create extensions, as a superuser is).

### Integration-test database

Tests marked `integration` need a disposable PostgreSQL database on the same server, for example `edugen_rag_test`. Set `RAG_TEST_DATABASE_URL` (environment or `backend/.env`) to its URL. The tests wipe and recreate its tables, so never point it at the development database. Without the variable they are skipped.

## Environment variables

Set these in the backend environment or `backend/.env` (never commit `.env`):

```dotenv
RAG_DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/edugen_rag
RAG_ASSET_DIR=./data/rag_assets
RAG_EMBEDDING_MODEL=gemini-embedding-2
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
```

`RAG_DATABASE_URL` takes precedence over `DATABASE_URL` so this feature can use a separate database. Create the `edugen_rag` database first. URL-encode any special characters in the password. Do not print, paste or commit secrets.

The initial schema uses `VECTOR(1536)`. Google documents 1536 as one of the recommended output dimensions for `gemini-embedding-2`. Changing dimensions requires a schema migration and rebuilding all embeddings; this is deliberately not a runtime environment toggle.

## Migration and database check

Run commands from `backend/`:

```powershell
python -m scripts.check_rag_db
python -m alembic -c alembic.ini upgrade head
```

If the database check fails because `vector` is missing, install/enable the PostgreSQL pgvector extension for your PostgreSQL installation before retrying. A Python package alone does not install the server-side extension.

## Ingest a PDF

From `backend/`:

```powershell
python -m scripts.ingest_research_pdf .\IJRTI2304061.pdf --no-embeddings
```

This parses and chunks the PDF, then stores the canonical data and copies the original PDF and extracted figures into managed storage. Assets are stored under relative, content-addressed keys in `RAG_ASSET_DIR`, not the source machine's absolute paths.

After verifying DB persistence, generate missing chunk embeddings:

```powershell
python -m scripts.ingest_research_pdf .\IJRTI2304061.pdf
```

The source hash makes repeat ingestion of the same PDF idempotent. Failed embedding generation does not roll back canonical source data; run the command again to retry missing embeddings. Existing documents are not automatically reparsed when the parser version changes; reprocessing policy is a later explicit decision.

## Code API

```python
from rag.document_ingestion import PDFIngestionService
from rag.chunking import StructureAwareChunker
from rag.storage_service import RAGStorageService

pdf_path = "path/to/paper.pdf"
document = PDFIngestionService().ingest(pdf_path)
chunks = StructureAwareChunker().chunk(document)
storage = RAGStorageService.from_env()
result = storage.persist_document(pdf_path, document, chunks)
new_vectors = storage.generate_missing_embeddings(result.document_id)
hits = storage.search_similar("What is the paper's main idea?", limit=5)
```

`search_similar` is a minimal vector-store smoke path only. Reranking, hierarchical parent/neighbor expansion, hybrid keyword retrieval and cross-reference-aware retrieval are out of scope until Phase 4 and later.

## Tests and what they do not prove

`tests/test_rag_storage.py` tests asset copying, checksums, idempotency orchestration, metadata guards, Gemini input formatting, vector dimension checks and batch behavior using fakes. `tests/test_rag_db_models.py` checks ORM table definitions when pgvector is installed. `tests/test_postgres_integration.py` runs the migrations on a real PostgreSQL with pgvector (see above). None of the tests make a live Gemini API request.

## Limitations

- No PDF upload API or public asset endpoint is added.
- The asset store uses the local filesystem by default; production object storage can replace it later.
- Initial embedding generation uses one API call per chunk. The Gemini Embedding 2 text-only retrieval prefixes follow Google's current embedding guidance.
- Vector table and model are fixed at 1536 dimensions in this initial migration.
- Plain canonical content survives embedding API failures, allowing embeddings to be retried.

## Uploading papers

Logged-in users upload PDFs through `POST /papers` (multipart field `file`) and follow them with `GET /papers` and `GET /papers/{id}`.

- Limits: PDF only, 50 MB by default (`MAX_PAPER_UPLOAD_MB`). Oversized bodies are refused with 413 before they are read. One paper is read at a time (`MAX_CONCURRENT_INGESTIONS`, default 1).
- Statuses: `queued` (waiting its turn), `parsing`, `chunking`, `storing`, `embedding`, `ready`, `failed`. A failed paper carries a one-line reason.
- The same PDF uploaded twice by one user returns the existing paper. If it had failed while being read, uploading it again reads it again.
- `POST /papers/{id}/retry` re-runs only the indexing (embedding) step of a paper whose text was already saved. A paper that failed while parsing must be uploaded again.
- Reading runs on in-process threads. If the server stops mid-way, the paper is marked failed on the next start.
- A PDF with no readable text (for example a scan) fails with a clear message; text recognition for scans is not available yet.
- Uploaded files are kept in `backend/data/uploads` only while a paper is being read, and are never committed.

