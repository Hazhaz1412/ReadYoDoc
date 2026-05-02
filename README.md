# 🤖 AI RAG — Document Assistant

Ask questions about your documents using **100% private, self-hosted AI**. No data leaves your network.

Built with **FastAPI** + **ChromaDB** + **Ollama** (qwen3.5:9b + bge-m3).

## Features

- 📄 Upload PDF, DOCX, TXT, MD documents
- 🔍 Semantic search with vector embeddings (bge-m3)
- 💬 Streaming chat answers with source citations
- 🧠 Optional "thinking mode" for complex queries
- 🔒 100% private — everything runs locally
- 🐳 Docker/Podman ready

## Quick Start

### Prerequisites

- **Ollama** running at `http://192.168.1.92:11434` (or update `.env`)
- Pull required models:
  ```bash
  ollama pull qwen3.5:9b
  ollama pull bge-m3
  ```

### Option 1: Docker / Podman (Recommended)

```bash
# Docker
docker compose up --build

# Podman
podman-compose up --build
```

Open http://localhost:8000

### Option 2: Local Development

```bash
# Create venv and install deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# Start server
cd backend
python run.py
```

Open http://localhost:8000

## Architecture

```
User → Frontend (HTML/CSS/JS)
         ↓
      FastAPI Backend
         ↓
   ┌─────┴─────┐
   │            │
ChromaDB    Ollama Server
(vectors)   (LLM + Embeddings)
```

**RAG Flow**: Upload → Parse → Chunk → Embed → Store → Query → Retrieve → Generate

## API Endpoints

| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/api/documents/upload` | Upload documents |
| `GET` | `/api/documents` | List all documents |
| `DELETE` | `/api/documents/{id}` | Delete a document |
| `POST` | `/api/chat` | Chat with streaming (SSE) |
| `POST` | `/api/chat/search` | Search similar chunks |
| `GET` | `/api/health` | System health check |

## Configuration

All settings via `.env` or environment variables:

| Variable | Default | Description |
|:---|:---|:---|
| `OLLAMA_BASE_URL` | `http://192.168.1.92:11434` | Ollama server URL |
| `LLM_MODEL` | `qwen3.5:9b` | LLM model name |
| `EMBEDDING_MODEL` | `bge-m3` | Embedding model name |
| `CHUNK_SIZE` | `1000` | Characters per chunk |
| `CHUNK_OVERLAP` | `200` | Overlap between chunks |
| `MAX_FILE_SIZE_MB` | `50` | Max upload file size |

## Tech Stack

- **Backend**: FastAPI, Uvicorn, Python 3.12
- **Vector DB**: ChromaDB (persistent, cosine similarity)
- **Embeddings**: bge-m3 via Ollama (multilingual)
- **LLM**: qwen3.5:9b via Ollama (streaming)
- **Frontend**: Vanilla HTML/CSS/JS (dark theme)
- **Metadata DB**: SQLite (aiosqlite)
