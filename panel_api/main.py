from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import docker
import psutil
import httpx
from typing import List

app = FastAPI(title="LogerBot Panel API")

BOT_API_URL = "http://bot:8081" # Внутренний адрес в Docker

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
FLOWS_DIR = "/app/data/flows"
BOT_CONTAINER_NAME = "logerbot_app"

os.makedirs(FLOWS_DIR, exist_ok=True)

# --- Dependencies ---
async def verify_token(authorization: str = Header(None)):
    print(f"[DEBUG] Auth Header: {authorization}") # DEBUG
    print(f"[DEBUG] Expected Key: {MASTER_KEY}")   # DEBUG

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != 'bearer':
             raise HTTPException(status_code=401, detail="Invalid scheme")
        if token != MASTER_KEY:
            print(f"[DEBUG] Token mismatch! Got '{token}', expected '{MASTER_KEY}'")
            raise HTTPException(status_code=403, detail="Invalid Token")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Authorization Header format")

# --- Routes ---

@app.get("/status", dependencies=[Depends(verify_token)])
async def get_status():
    """Returns basic server stats and live bot stats."""
    vm = psutil.virtual_memory()
    server_stats = {
        "cpu_percent": psutil.cpu_percent(),
        "ram_percent": vm.percent,
        "ram_used_mb": vm.used // (1024 * 1024),
        "ram_total_mb": vm.total // (1024 * 1024)
    }
    
    # Try to get live data from bot
    bot_stats = {"status": "offline"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BOT_API_URL}/stats", timeout=1.0)
            if resp.status_code == 200:
                bot_stats = resp.json()
    except:
        pass
        
    return {"server": server_stats, "bot": bot_stats}

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

@app.get("/bot/docker-logs", dependencies=[Depends(verify_token)])
def get_docker_logs():
    """Returns recent stdout/stderr from the bot container."""
    try:
        client = docker.from_env()
        container = client.containers.get(BOT_CONTAINER_NAME)
        # Tail last 100 lines
        logs = container.logs(tail=100).decode('utf-8', errors='replace')
        return {"logs": logs}
    except Exception as e:
        raise HTTPException(500, f"Error getting docker logs: {str(e)}")

@app.get("/bot/guilds", dependencies=[Depends(verify_token)])
async def get_guilds():
    """Fetches list of guilds from Bot Sidecar."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BOT_API_URL}/guilds", timeout=5.0)
            return resp.json()
    except Exception as e:
        raise HTTPException(500, f"Bot Sidecar error: {str(e)}")

# --- Commands & Settings ---

@app.get("/bot/commands", dependencies=[Depends(verify_token)])
async def get_commands():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BOT_API_URL}/commands")
        return resp.json()

class ToggleCommandRequest(BaseModel):
    name: str
    enabled: bool

@app.post("/bot/commands/toggle", dependencies=[Depends(verify_token)])
async def toggle_command(req: ToggleCommandRequest):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BOT_API_URL}/commands/toggle", json=req.dict())
        return resp.json()

@app.get("/bot/settings/{guild_id}", dependencies=[Depends(verify_token)])
async def get_settings(guild_id: int):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BOT_API_URL}/settings?guild_id={guild_id}")
        return resp.json()

class UpdateSettingRequest(BaseModel):
    guild_id: int
    key: str
    value: str | int | bool

@app.post("/bot/settings/update", dependencies=[Depends(verify_token)])
async def update_setting(req: UpdateSettingRequest):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BOT_API_URL}/settings/update", json=req.dict())
        return resp.json()

# --- User Management ---

@app.get("/users/{guild_id}", dependencies=[Depends(verify_token)])
async def get_users(guild_id: int):
    """Fetches top users for a guild via Bot Sidecar."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BOT_API_URL}/db/users?guild_id={guild_id}", timeout=5.0)
            return resp.json()
    except Exception as e:
        raise HTTPException(500, f"Bot Sidecar error: {str(e)}")

class UpdateUserRequest(BaseModel):
    guild_id: int
    user_id: int
    balance: int = None
    xp: int = None

@app.post("/users/update", dependencies=[Depends(verify_token)])
async def update_user(req: UpdateUserRequest):
    """Updates user stats via Bot Sidecar."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{BOT_API_URL}/db/users/update", json=req.dict(), timeout=5.0)
            return resp.json()
    except Exception as e:
        raise HTTPException(500, f"Bot Sidecar error: {str(e)}")

# --- Flow Management (n8n style) ---

@app.get("/bot/flows/list", dependencies=[Depends(verify_token)])
async def list_flows():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BOT_API_URL}/flows/list")
        return resp.json()

@app.get("/bot/flows/get", dependencies=[Depends(verify_token)])
async def get_flow(name: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BOT_API_URL}/flows/get?name={name}")
        return resp.json()

@app.post("/bot/nodes/test", dependencies=[Depends(verify_token)])
async def test_node(req: dict):
    # AI generation takes time, so we need a long timeout
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{BOT_API_URL}/nodes/test", json=req)
        return resp.json()

class SaveFlowRequest(BaseModel):
    name: str
    data: dict

@app.post("/flows/save", dependencies=[Depends(verify_token)])
async def save_flow(req: SaveFlowRequest):
    """Saves flow and tells bot to reload."""
    if "trigger" not in req.data or "nodes" not in req.data:
        raise HTTPException(400, "Invalid flow structure")
    
    # We can save directly since we share volume, or proxy.
    # Let's save locally to share volume, then reload bot.
    safe_name = "".join(c for c in req.name if c.isalnum() or c in (' ', '_')).rstrip()
    path = os.path.join(FLOWS_DIR, f"{safe_name}.json")
    
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(req.data, f, indent=2, ensure_ascii=False)
        
        # Notify bot to reload flows
        async with httpx.AsyncClient() as client:
            await client.get(f"{BOT_API_URL}/reload", timeout=2.0)
            
        return {"status": "success", "reloaded": True}
    except Exception as e:
        return {"status": "success", "reloaded": False, "error": str(e)}


@app.delete("/flows/{name}", dependencies=[Depends(verify_token)])
def delete_flow(name: str, dependencies=[Depends(verify_token)]):
    """Deletes a flow file."""
    path = os.path.join(FLOWS_DIR, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)
        return {"status": "deleted"}
    raise HTTPException(404, "Flow not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
