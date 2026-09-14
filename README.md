# Clinical AI Extraction & Orchestration Pipeline (POC)

An enterprise-grade proof of concept demonstrating automated ingestion, structured data extraction, semantic search, and agentic clinical assistance over clinical trial reports and medical records using Large Language Models (LLMs).

---

## Features

- **AI-Powered Structured Extraction:** Ingests unstructured clinical trial notes and extracts validated, structured medical entities (summary, category, key entities, confidence score) using Groq/OpenAI.
- **Recursive Document Chunking:** Splits large clinical records using `RecursiveCharacterTextSplitter` (500 characters, 50 overlap) for high-granularity vector storage and retrieval.
- **Semantic Vector Search:** Embeds clinical text into 384-dimensional dense vectors using HuggingFace (`sentence-transformers/all-MiniLM-L6-v2`) and executes sub-millisecond cosine distance similarity queries via `pgvector`.
- **Agentic Clinical Tool Calling:** Implements an autonomous clinical agent (`/chat/agent`) that evaluates clinical queries, dynamically dispatches tools through an extensible registry (`TOOL_REGISTRY`), queries the vector database, and synthesizes grounded, evidence-based answers.
- **Real-Time Token Streaming (SSE):** Delivers low-latency clinical responses (`/chat/stream`) via Server-Sent Events (`text/event-stream`), dropping Time-to-First-Token (TTFT) from seconds to sub-300ms.
- **Enterprise Authentication & Tenant Isolation:** Stateless JWT authentication (`OAuth2PasswordBearer`) with Bcrypt password hashing; all document embeddings and search results are strictly isolated by authenticated `user_id`.
- **Defensive Engineering & Resilience:** Retries transient LLM failures and rate limits automatically with exponential backoff (`tenacity`) and returns structured fallback schemas if APIs are unreachable.
- **Input Sanitization:** Protects ingestion pipelines against malicious payloads and prompt injections with automated HTML/text sanitization.
- **Event-Driven Orchestration:** Integrates N8N for webhook automation, batch ingestion pipelines, and downstream Slack/Email notifications.
- **Containerized Infrastructure:** Fully reproducible deployment using Docker Compose orchestrating PostgreSQL (with `pgvector`), FastAPI, and N8N.

---

## Tech Stack

- **API & Core:** FastAPI, Pydantic v2, SQLAlchemy 2.0, Uvicorn
- **AI & NLP:** Groq / OpenAI (`AsyncOpenAI`), HuggingFace (`sentence-transformers`), LangChain
- **Database & Vectors:** PostgreSQL 16 with `pgvector`
- **Security & Auth:** PyJWT, Passlib (Bcrypt), Bleach
- **Resilience:** Tenacity (exponential backoff retry policies)
- **Orchestration:** N8N, Docker & Docker Compose
- **Testing:** Pytest, Pytest-Asyncio

---

## Architecture & Flows

### 1. Ingestion & Chunking Flow
```text
Client / Doctor
  │
  │ HTTP POST /upload (Clinical Document)
  ▼
FastAPI App
  │
  ├── 1. Sanitizes text & authenticates user (JWT)
  ├── 2. RecursiveCharacterTextSplitter chunks text (500 chars / 50 overlap)
  ├── 3. Generates 384-dim embeddings per chunk (HuggingFace)
  ├── 4. LLM extracts structured JSON (summary, category, entities, confidence)
  │
  ▼
PostgreSQL + pgvector
  ├── Stores document chunks with embedding vectors
  └── Stores validated extraction results in relational tables
```

### 2. Semantic Search Flow
```text
Client (Search Query)
  │
  │ POST /search {"query": "patient adverse events on drug X"}
  ▼
FastAPI App
  │
  ├── 1. Embeds query text into 384-dimensional vector
  ├── 2. Runs SQL cosine distance query filtered by user_id
  │      (Document.embedding.cosine_distance(query_vector) <= threshold)
  │
  ▼
PostgreSQL (pgvector)
  │
  ▼
Returns top-k matching clinical document chunks
```

### 3. Agentic Tool Calling Flow (`/chat/agent`)
```text
Clinician Query: "What medications was patient PT-104 prescribed for hypertension?"
  │
  ▼
1. FastAPI passes query + Tool Catalog schema to LLM (Groq/OpenAI)
  │
  ▼
2. LLM emits structured tool call:
   search_medical_records(query="patient PT-104 hypertension medications")
  │
  ▼
3. Agent Service routes dynamically via TOOL_REGISTRY:
   - Injects authenticated user_id & DB session
   - Executes pgvector similarity search
   - Returns raw clinical records as tool response
  │
  ▼
4. LLM receives tool response, synthesizes evidence, and returns final answer:
   "Patient PT-104 was prescribed Lisinopril 10mg daily on 2026-02-14..."
```

### 4. Real-Time Streaming Flow (`/chat/stream`)
```text
Client (Chat UI)
  │
  │ POST /chat/stream
  ▼
FastAPI StreamingResponse
  │
  ├── Vector search retrieves top clinical evidence chunks
  ├── Streams tokens directly from LLM via Server-Sent Events (SSE)
  │   `data: Lisinopril\n\n`
  ▼
Client renders tokens immediately (TTFT < 300ms)
```

---

## Core API Endpoints

| Method | Endpoint | Description | Auth Required |
|---|---|---|:---:|
| `POST` | `/register` | Register a new user (clinician/researcher) | No |
| `POST` | `/token` | Obtain JWT access token via credentials | No |
| `GET` | `/me` | Fetch authenticated user profile | Yes (Bearer) |
| `POST` | `/upload` | Upload & extract structured clinical document | Yes (Bearer) |
| `POST` | `/search` | Semantic vector search across user records | Yes (Bearer) |
| `POST` | `/chat/stream` | Stream clinical QA answers via Server-Sent Events | Yes (Bearer) |
| `POST` | `/chat/agent` | Autonomous clinical agent with dynamic tool calling | Yes (Bearer) |

---

## Regulatory & Compliance Design (Pharma-Ready)

### 1. PHI Pseudonymization & Reversible Token Mapping
To protect patient privacy under **HIPAA Safe Harbor** and **GDPR**, third-party LLM APIs are treated as untrusted perimeters:
- **Pre-LLM Tokenization:** Patient identifiers and Medical Record Numbers (MRNs) are intercepted and replaced with deterministic surrogate tokens (e.g., `MRN-928174` $\rightarrow$ `[MRN_TOKEN_X92]`, `Jane Doe` $\rightarrow$ `[SUBJECT_ID_A04]`).
- **Encrypted Token Vault:** The bidirectional mapping is stored in an encrypted table protected by database Row-Level Security (RLS).
- **Presentation-Time Detokenization:** LLMs only process de-identified text; surrogate tokens are detokenized into real identifiers only when rendered to an authorized clinician.

### 2. Immutable Audit Trailing (21 CFR Part 11)
To satisfy FDA requirements for electronic records in clinical trials:
- **Tamper-Evident Telemetry:** An append-only audit table logs all queries, user IDs, ISO timestamps, and exact SHA256 hashes of vector chunks fed to the model.
- **Deterministic Replay:** Provides full compliance traceability to demonstrate the exact clinical evidence used to generate any diagnosis or recommendation.

---

## Quickstart (How to run locally)

### 1. Prerequisites & Environment Setup
Clone the repository and create a `.env` file in the root directory:
```bash
GROQ_API_KEY=gsk_your_key_here
SECRET_KEY=your_super_secret_jwt_key
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/amgen_db
```

### 2. Run with Docker Compose
Boot up the entire stack (PostgreSQL with `pgvector`, FastAPI API server, and N8N):
```bash
docker-compose up -d --build
```

Access the services:
- **FastAPI Swagger Docs:** `http://localhost:8000/docs`
- **N8N Workflow Automation:** `http://localhost:5678`

### 3. Run Locally with Virtual Environment
```bash
# Activate virtual environment
.\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start FastAPI server
uvicorn app.main:app --reload --port 8000
```

### 4. Running the Test Suite
```bash
pytest
```
Includes automated unit tests for:
- Extraction schema validation (`test_validation.py`)
- Provider fallback & retry handling (`test_providers.py`)
- Autonomous agent loop and dynamic tool registry (`test_agent_service.py`)