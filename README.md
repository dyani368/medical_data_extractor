# Clinical AI Extraction & Orchestration Pipeline (POC)
An enterprise-grade proof of concept demonstrating automated ingestion, structured data extraction, and semantic search of clinical trial reports using Large Language Models (LLMs). 

## Features
- **AI-Powered Extraction:** Uses Groq to read unstructured clinical notes and extract structured patient data.
- **Strict Data Validation:** Enforces strict JSON schemas using Pydantic, ensuring downstream systems only receive clean data.
- **Defensive Engineering:** Abstracted LLM provider interface with exponential backoff retries and graceful fallback responses for API failures.
- **Semantic Search:** Embeds clinical text into 384-dimensional vectors using HuggingFace and performs high-speed cosine similarity search via `pgvector`.
- **Event-Driven Orchestration:** Uses N8N to handle webhooks, batch processing schedules, and downstream Slack/Gmail notifications.
- **Containerized Infrastructure:** Fully deployable via Docker Compose with isolated PostgreSQL, FastAPI, and N8N services.

## Tech Stack
- **API**: FastAPI, Pydantic, SQLAlchemy
- **AI**: Groq, HuggingFace (`sentence-transformers`)
- **Database**: PostgreSQL with `pgvector`
- **Orchestration**: N8N
- **Infrastructure**: Docker & Docker Compose

## Architecture

### 1. The Ingestion Flow
```text
Client / Doctor
  |
  | HTTP POST File
  v
N8N (Webhook Node)
  |
  |-- HTTP POST to FastAPI
  v
FastAPI App
  |
  |-- 1. Pydantic validates input
  |-- 2. LLM Provider (Groq) extracts structured data
  |-- 3. Generates vector embeddings (HuggingFace)
  |
  v
PostgreSQL (pgvector)
  |
  v
FastAPI returns JSON summary
  |
  v
N8N (Gmail/Slack Node)
  |
  |-- Emails doctor with AI summary
```

### The Semantic Search Flow
```text
Client (Search Bar)
  |
  | GET /search?query="patient with migraines"
  v
FastAPI App
  |
  |-- Converts query into a vector embedding
  |-- Executes cosine similarity SQL query against pgvector
  |
  v
PostgreSQL
  |
  v
Returns top 3 matching clinical reports
```

## Quickstart (How to run locally)

1. Clone this repository.
2. Create a `.env` file in the root directory and add your API key:
   ```bash
   GROQ_API_KEY=gsk_your_key_here
   ```
3. Boot up the entire infrastructure (Database, API, and Orchestrator) with one command:
   ```bash
   docker-compose up -d
   ```
4. Access the services:
   ```bash
   FastAPI Swagger UI: http://localhost:8000/docs
   N8N Orchestration UI: http://localhost:5678
