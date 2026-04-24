# Agentix — Real-time Autonomous Software Engineering System

A real-time, chat-driven autonomous software engineering system that turns natural language into fully running applications through a controlled **planning → coding → execution → debugging** loop, visible live in a web interface.

Think of it as a software engineering team that lives inside a chat window — it writes real code, runs it, debugs it, and modifies it live while talking to you like a human developer.

---

## ✨ Features

- 💬 **Conversational Engineer Interface** — chat with an AI senior dev that understands follow-ups
- 🧠 **Conversation → Code Translator** — turns vague natural language into structured engineering tasks
- ⚙️ **Orchestrated Agent System** — Planner, Coder, Tester, and Debugger agents coordinated by an Orchestrator
- 🧪 **Execution Sandbox** — runs actual code in a subprocess, captures stdout/stderr/errors
- 🔁 **Self-correcting loop** — automatically detects errors and retries with AI-generated fixes
- 🖥️ **Real-time visual interface** — live chat, streaming terminal logs, file tree, and project plan

---

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/xWisprrr/XxandrixX-Agentix-Style-AI-Engineer.git
cd XxandrixX-Agentix-Style-AI-Engineer
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### 3. Run

```bash
python run.py
```

Open **http://localhost:8000** in your browser.

---

## 🏗️ Architecture

```
.
├── backend/
│   ├── main.py                # FastAPI app + WebSocket endpoint
│   ├── models.py              # Shared Pydantic data models
│   ├── agents/
│   │   ├── orchestrator.py    # Central coordination loop
│   │   ├── planner.py         # Architecture planning agent
│   │   ├── coder.py           # Code generation agent
│   │   └── debugger.py        # Error analysis & fixing agent
│   ├── sandbox/
│   │   └── executor.py        # Subprocess sandbox runner
│   └── llm/
│       └── client.py          # OpenAI API wrapper
├── frontend/
│   ├── index.html             # Main UI (chat + terminal + file tree)
│   ├── style.css              # Dark engineering theme
│   └── app.js                 # WebSocket client + UI logic
├── projects/                  # Generated projects stored here (git-ignored)
├── requirements.txt
├── .env.example
└── run.py                     # Entry point
```

### The core loop

```
User sends message
       ↓
  Orchestrator
       ↓
   Planner → creates structured plan (4–8 steps)
       ↓
   Coder   → generates real source files per step
       ↓
  Executor → runs code in subprocess
       ↓
  [Error?] → Debugger analyzes + fixes → re-run
       ↓
  [Success] → reports completion to user
```

Every step streams real-time updates to the browser via WebSocket.

---

## ⚙️ Configuration

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | Your OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base URL (supports Azure OpenAI / local LLMs) |
| `LLM_MODEL` | `gpt-4o` | Model to use |
| `PROJECTS_DIR` | `projects` | Directory for generated projects |
| `MAX_DEBUG_ATTEMPTS` | `3` | Max auto-debug attempts per run |
| `EXECUTION_TIMEOUT` | `30` | Seconds before killing the sandbox process |
| `PORT` | `8000` | Server port |

---

## 💡 Example prompts

- *"Build a REST API with JWT authentication using FastAPI"*
- *"Create a CLI todo app in Python with file persistence"*
- *"Make a web scraper that extracts headlines from a news site"*
- *"Build a SaaS dashboard with user management"*
- *"Write a Python Flask app with a SQLite database"*

---

## 🔒 Security note

The execution sandbox runs generated code in a subprocess on your machine. For production use, wrap the executor in a Docker container or use a proper sandboxing solution (e.g., gVisor, Firecracker).
