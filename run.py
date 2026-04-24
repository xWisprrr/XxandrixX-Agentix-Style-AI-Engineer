"""
Agentix entry point — load .env then launch the FastAPI server.
"""
import os

from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True, log_level="info")
