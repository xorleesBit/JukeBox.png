from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import docker
import psutil
from typing import List

app = FastAPI(title="LogerBot Panel API")

# CORS (Allow requests from your local React app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, lock this down or use SSH tunnel
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Config ---
MASTER_KEY = os.getenv("MASTER_KEY", "default_insecure_key")
LOGS_DIR = "/app/logs"
BOT_CONTAINER_NAME = "logerbot_app"

# --- Dependencies ---
async def verify_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != 'bearer':
             raise HTTPException(status_code=401, detail="Invalid scheme")
        if token != MASTER_KEY:
            raise HTTPException(status_code=403, detail="Invalid Token")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Authorization Header format")

# --- Routes ---

@app.get("/status", dependencies=[Depends(verify_token)])
def get_status():
    """Returns basic server stats."""
    vm = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(),
        "ram_percent": vm.percent,
        "ram_used_mb": vm.used // (1024 * 1024),
        "ram_total_mb": vm.total // (1024 * 1024)
    }

# --- Logs ---
@app.get("/logs", dependencies=[Depends(verify_token)])
def list_logs():
    """Lists all files in the logs directory."""
    if not os.path.exists(LOGS_DIR):
        return []
    
    file_tree = []
    for root, dirs, files in os.walk(LOGS_DIR):
        rel_path = os.path.relpath(root, LOGS_DIR)
        if rel_path == ".": rel_path = ""
        
        for file in files:
            full_path = os.path.join(root, file)
            size = os.path.getsize(full_path)
            file_tree.append({
                "path": os.path.join(rel_path, file).replace("\\", "/"),
                "size_kb": round(size / 1024, 2)
            })
    return file_tree

class LogRequest(BaseModel):
    path: str

@app.post("/logs/read", dependencies=[Depends(verify_token)])
def read_log(req: LogRequest):
    """Reads the content of a specific log file."""
    # Security: Prevent Path Traversal
    safe_path = os.path.normpath(os.path.join(LOGS_DIR, req.path))
    if not safe_path.startswith(os.path.normpath(LOGS_DIR)):
        raise HTTPException(403, "Access Denied: Path traversal detected")
    
    if not os.path.exists(safe_path):
        raise HTTPException(404, "File not found")
        
    try:
        # Read last 2000 lines max to prevent crash
        with open(safe_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            return {"content": "".join(lines[-2000:])}
    except Exception as e:
        raise HTTPException(500, f"Error reading file: {str(e)}")

# --- Docker Control ---
@app.post("/bot/restart", dependencies=[Depends(verify_token)])
def restart_bot():
    """Restarts the bot container."""
    try:
        client = docker.from_env()
        container = client.containers.get(BOT_CONTAINER_NAME)
        container.restart()
        return {"status": "success", "message": "Bot container restarting..."}
    except docker.errors.NotFound:
        raise HTTPException(404, "Bot container not found")
    except Exception as e:
        raise HTTPException(500, f"Docker error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
