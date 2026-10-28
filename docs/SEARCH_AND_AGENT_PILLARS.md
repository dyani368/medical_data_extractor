# Pillar 1 & Pillar 2 Guide: Search, Retrieval & Agentic Tool Calling

A complete revision document covering **Hybrid Search (RRF)**, **Memory Optimization**, **Conversation Evidence Reloading**, **Verified ID Filtering**, **Agentic Tool Calling**, and **Production Guardrails**.

---

## PART 1: Pillar 1 – Hybrid Search, Retrieval & Memory Architecture

### 1. High-Level Concept: Why Not Pure Vector Search?
- **Vector Search (`pgvector`)**: Excellent at conceptual semantics (e.g. matching *"renal failure"* with *"kidney impairment"*). Fails at exact alphanumeric codes, drug product numbers (`20120124`), and specific patient IDs (`PT-1044`).
- **Full-Text Lexical Search (PostgreSQL `to_tsvector`)**: Matches exact words, IDs, and pharmaceutical codes via stemming and term frequency. Fails when users describe symptoms using synonyms.
- **The Solution (Hybrid Search)**: Query both simultaneously, then fuse their rankings using **Reciprocal Rank Fusion (RRF)**.

```
                    User Query: "What was the dose for PT-1044?"
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
       VECTOR SEARCH                                   KEYWORD SEARCH
(pgvector Cosine Distance)                     (PostgreSQL to_tsvector @@ tsquery)
   Finds: Concepts & Semantics                     Finds: Exact "PT-1044" & "dose"
   Scores: Distance (e.g. 0.18, 0.32)              Scores: BM25/Density (e.g. 0.08, 0.04)
              │                                               │
              └───────────────────────┬───────────────────────┘
                                      ▼
                        RECIPROCAL RANK FUSION (RRF)
                   RRF Score = Σ [ 1 / (60 + rank_in_list) ]
                                      │
                                      ▼
                           Top 5 Fused Candidates
```

---

### 2. How Reciprocal Rank Fusion (RRF) Works in Code
- **File:** `app/services/doc_search.py`
- Scores in vector search (cosine distance) and keyword search (BM25) cannot be mathematically added because their units are completely different.
- **RRF only looks at relative position (Rank 1, Rank 2, Rank 3...)**:

$$\text{RRF Score}(doc) = \sum_{r \in \{\text{vector, keyword}\}} \frac{1}{60 + \text{rank}_r}$$

```python
def fuse_rankings(vector_docs, keyword_docs, limit):
    scores, documents = {}, {}
    # Loops over BOTH lists!
    for ranking in (vector_docs, keyword_docs):
        for rank, doc in enumerate(ranking, start=1):
            documents[doc.id] = doc
            scores[doc.id] = scores.get(doc.id, 0.0) + 1.0 / (60 + rank)
    ordered = sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))
    return [documents[doc_id] for doc_id in ordered[:limit]]
```

#### Why It Works (The Math Example):
Suppose a user searches for *"Dosage for PT-1044"*:
- **Doc #101** (general dosage text): Rank 1 in vector ($\frac{1}{61} \approx 0.01639$), but **not present** in keyword $\rightarrow$ **Total = 0.01639**
- **Doc #105** (has exact "PT-1044" table): Rank 2 in vector ($\frac{1}{62} \approx 0.01612$) AND Rank 1 in keyword ($\frac{1}{61} \approx 0.01639$) $\rightarrow$ **Total = 0.03251**
- **Winner:** **Doc #105** doubles its score because it was confirmed by both search methods!

---

### 3. Detailed Explanations of Key Architecture Decisions

#### A. The Memory Architecture: The Private `/embed` Worker Endpoint
- **The Problem:** PyTorch and `SentenceTransformer('all-MiniLM-L6-v2')` consume ~350MB–500MB of RAM. If both FastAPI and the Background Worker load the model in Docker on a small cloud computer (e.g., AWS EC2 `t3.medium` with only 4GB of RAM), the server runs out of memory (OOM crash).
- **The Solution (`app/worker.py` & `app/core/embeddings.py`):**
  - **Only the Worker loads the model into RAM.**
  - The worker runs an internal HTTP server on port `8001` with one route: `POST /embed` (authenticated with a shared secret header `X-Worker-Key`).
  - When a user submits a search, FastAPI does NOT load the model. It sends an internal HTTP POST to `http://worker:8001/embed`.
  - **Tradeoff:** Saves >500MB of host RAM at the cost of a sub-millisecond local network hop.

```
   [ AWS EC2 Instance (4GB RAM) ]
   ┌──────────────────────────────────────────────┐
   │ FastAPI Web Container (0 MB ML Weights)      │
   │  │                                           │
   │  └──► POST http://worker:8001/embed          │
   │            (Internal Docker Network)         │
   │            │                                 │
   │            ▼                                 │
   │ Worker Container                             │
   │  └── Loads PyTorch + MiniLM (500 MB RAM)     │
   │  └── Serves /embed endpoint to FastAPI       │
   └──────────────────────────────────────────────┘
   Result: Saved >500MB of RAM; prevented OOM crash!
```

---

#### B. Indexing Strategy: Exact Scan vs. HNSW Index (The Honesty Trap)
- **The Question:** *"Did you use HNSW or IVFFlat indexes in pgvector?"*
- **The Truth in Code:** No index is configured; it computes exact cosine distance at query time:
  ```python
  stmt = select(Document).where(
      Document.user_id == user_id,
      Document.embedding.is_not(None)
  ).order_by(distance).limit(20)
  ```
- **Why this is the correct engineering choice:**
  1. **Corpus Size:** Each tenant's personal document library contains hundreds to a few thousand passages, not millions.
  2. **Speed:** Exact cosine distance over ~2,000 vectors runs in under 3 milliseconds in PostgreSQL memory.
  3. **No Recall Loss:** Approximate Nearest Neighbor (ANN) indexes like HNSW drop 5%–10% of true nearest neighbors to gain speed. Exact scan has 100% recall.
  4. **When to upgrade:** If a single tenant grew beyond 50,000+ passages, add an HNSW index partitioned by `user_id`.

---

#### C. Follow-up Conversations: Evidence Reloading (`load_previous_evidence`)
- **File:** `app/services/agent_service.py` (lines 55–67)
- **The Problem:** In multi-turn chat, how does the model remember previous documents without hallucinating?
  - A naive system just passes the conversational chat history back to the LLM. But LLM generated text can contain slight inaccuracies, and relying on its own previous conversational output causes compound hallucinations over time.
- **The Solution:**
  1. The server inspects previous messages for tool outputs matching `[doc:ID]`.
  2. It pulls the real IDs and **re-queries PostgreSQL from scratch**:
     ```python
     select(Document).where(
         Document.user_id == user_id, 
         Document.id.in_(sorted(ids))
     )
     ```
  3. It re-injects the verified, ground-truth text into the prompt under `role: "system"`.
  4. **Principle:** *"Never trust assistant prose as evidence; always reload source records from the database."*

---

#### D. The ID Verifying Step (`cited_sources` & Grounding)
- **File:** `app/services/agent_service.py` (lines 49–53)
- **The Threat Vectors:**
  1. **Hallucinated Citations:** The model makes up numbers out of thin air (e.g., claiming a fact and appending `[doc:9999]`).
  2. **Prompt Injection / Cross-Tenant Leaks:** A malicious prompt attempts to guess or cite another user's document ID (e.g. `[doc:42]`).
  3. **Irrelevant Clutter:** Search retrieved 5 documents, but the model only used 1. Sending all 5 to the UI confuses the user.
- **How the Code Verifies Citations:**
  ```python
  def cited_sources(answer, candidates):
      # 1. Regex extracts every citation the LLM wrote in its answer
      ids = {int(match) for match in re.findall(r"(?:\[doc:|【(?:doc:)?)(\d+)(?:\]|】)", answer or "")}
      
      # 2. Strict intersection with candidates retrieved for THIS authenticated user
      return list({source["document_id"]: source for source in candidates if source["document_id"] in ids}.values())
  ```
- **The Dual Guard:**
  - If an ID is in the text but **not** in `candidates` $\rightarrow$ **Discarded!** (Blocks hallucinations & cross-tenant access).
  - If an ID is in `candidates` but **not** mentioned in the answer $\rightarrow$ **Discarded!** (Removes clutter).
  - Only confirmed, owned sources become clickable badges in the UI that highlight the PDF page and bounding box.

---

#### E. Removing the Fixed Cosine Cutoff Threshold
- **File:** `app/services/doc_search.py` (lines 20–23)
- **Why it was removed:** A fixed cutoff (e.g. `distance <= 0.3`) rejected true clinical answers. SentenceTransformer models often score dense clinical sentences or table excerpts around `0.35–0.45` distance. A hard threshold creates severe false negatives. Instead, we remove the threshold, fetch the top 20 candidates from both vector and keyword engines, fuse them with RRF to top 5, and let the LLM verify whether the evidence answers the prompt.

---

## PART 2: Pillar 2 – Agentic RAG & Tool Calling

### 1. The Core Architecture
Instead of naive RAG (blindly stuffing search chunks into every prompt), an **Agentic Loop** lets the LLM choose tools, query data iteratively, and verify answers.

```
User Question ──► FastAPI (Tenant Authentication)
                       │
                       ▼
                 LLM Turn 1
         (Forced Tool Execution on Cold Start)
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
   LLM chooses Tool:         LLM chooses Tool:
search_medical_records     get_extraction_result
          │                         │
          └────────────┬────────────┘
                       ▼
             Server Executes Tool
        (Injects user_id from JWT token)
                       │
                       ▼
              Evidence Returned
                       │
                       ▼
                 LLM Turn 2
        (Synthesizes answer with citations)
                       │
                       ▼
             Verified ID Filter
        (Regex match against owned IDs)
                       │
                       ▼
        Streamed SSE Tokens to Browser
```

---

### 2. The 3 Tools Registered with the Model
- **File:** `app/providers/tools.py`, `app/services/agent_tools.py`

| Tool Name | Parameters | Purpose |
| :--- | :--- | :--- |
| **`search_medical_records`** | `query: str` | Runs Hybrid Search + RRF across all of the authenticated user's documents. |
| **`get_extraction_result`** | `document_id: int` | Fetches the pre-calculated summary, category, and JSON key entities for a document. |
| **`get_related_document_chunks`** | `document_id: int` | Fetches adjacent chunks ($N-2$ through $N+2$) from the same PDF if a sentence was split across boundaries. |

---

### 3. The 4 Production Guardrails

#### Guardrail 1: Forced Tool Execution on Cold Starts (Zero-Hallucination Guard)
- **Problem:** When asked a factual question, a model might answer from its pre-training memory instead of consulting the patient's records.
- **Implementation (`agent_service.py:246`):**
  ```python
  response_message = await llm_provider.run_agent(
      messages, 
      require_tool=None if previous_sources else True
  )
  ```
  On turn 1 without prior evidence, `require_tool=True` is enforced. The LLM is **forbidden from responding directly** until it calls a search tool.

#### Guardrail 2: Hard Tool Limits (Infinite Loop & Cost Defense)
- **Problem:** Agents can loop indefinitely if search results are ambiguous.
- **Implementation:**
  - `MAX_AGENT_TOOL_ROUNDS = 3`
  - `MAX_AGENT_TOOL_CALLS = 6`
  - If the agent hits the limit, the server forces one final answer turn with `require_tool=False`.

#### Guardrail 3: Server-Side Tenant Injection
- **Problem:** A prompt injection could attempt: `search_medical_records(user_id=42)`.
- **Implementation:** The model is never allowed to specify `user_id`. The server ignores model-supplied metadata and injects `current_user.id` from the verified JWT.

#### Guardrail 4: Streaming Answers via SSE (Server-Sent Events)
- Tool calling happens **synchronously** before streaming starts.
- Once evidence is gathered, FastAPI streams the final response token-by-token:
  1. `event: fragment` (text tokens for live typing UI)
  2. `event: sources` (verified citation objects for clickable badges)
  3. `event: complete` (finished payload)
- **Nginx Config:** `proxy_buffering off;` is mandatory in `nginx.conf`, otherwise Nginx holds chunks in memory and flushes them all at once at the end.
