import os
import json
import logging
from typing import TypedDict, Dict, List

logger = logging.getLogger(__name__)

class AIProvider(TypedDict):
    name: str
    base_url: str
    env_key_var: str # Name of env var holding the key (e.g. "OPENROUTER_KEY")
    models: List[str]
    default_model: str

PRESETS: Dict[str, AIProvider] = {
    "chutes": {
        "name": "Chutes.ai",
        "base_url": "https://chutes.ai/api/v1",
        "env_key_var": "CHUTES_API_KEY", # Falls back to AI_API_KEY if not found
        "models": ["chutes-llama-3.3-70b", "nvidia/Llama-3.1-Nemotron-70B-Instruct-HF"],
        "default_model": "chutes-llama-3.3-70b"
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key_var": "OPENROUTER_API_KEY",
        "models": [
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-chat:free",
            "google/gemini-2.0-flash-exp", # Paid/Limitless
            "anthropic/claude-3.5-sonnet",
            "openai/gpt-4o"
        ],
        "default_model": "google/gemini-2.0-flash-exp:free"
    }
}

class AIManager:
    def __init__(self, db):
        self.db = db
        # Defaults from .env (Legacy support)
        self.current_provider = "custom"
        self.current_model = os.getenv("AI_MODEL", "chutes-llama-3.3-70b")
        self.current_url = os.getenv("AI_BASE_URL", "https://chutes.ai/api/v1")
        self.current_key = os.getenv("AI_API_KEY", "")

    async def load(self):
        """Loads AI config from DB (global persistent state)."""
        # We need a place to store global bot config.
        # We'll use a special key in 'guild_configs' with ID 0 (Global) or persistent_state
        # Let's check persistent_state table... it has guild_id PK. 
        # We'll use guild_id=0 for global bot settings.
        
        try:
            row = await self.db.pool.fetchrow("SELECT settings FROM guild_configs WHERE guild_id=0")
            if row and row['settings']:
                data = json.loads(row['settings'])
                ai_cfg = data.get("ai_config", {})
                
                if ai_cfg:
                    self.current_provider = ai_cfg.get("provider", "custom")
                    self.current_model = ai_cfg.get("model", self.current_model)
                    self._apply_provider_settings(self.current_provider)
                    logger.info(f"AI Manager loaded: {self.current_provider} / {self.current_model}")
                    return
        except Exception:
            pass
        
        # If no DB config, try to detect from env
        if "openrouter" in self.current_url:
            self.current_provider = "openrouter"
        elif "chutes" in self.current_url:
            self.current_provider = "chutes"

    async def save(self):
        """Saves current config to DB."""
        data = {
            "ai_config": {
                "provider": self.current_provider,
                "model": self.current_model
            }
        }
        await self.db.set_config_value(0, "ai_config", data["ai_config"])

    def set_provider(self, provider_id: str):
        if provider_id not in PRESETS:
            return
        
        self.current_provider = provider_id
        self._apply_provider_settings(provider_id)
        
    def _apply_provider_settings(self, provider_id: str):
        if provider_id == "custom":
            return # Keep existing custom settings
            
        preset = PRESETS[provider_id]
        self.current_url = preset["base_url"]
        
        # Try to find specific key, fallback to generic AI_API_KEY
        specific_key = os.getenv(preset["env_key_var"])
        self.current_key = specific_key if specific_key else os.getenv("AI_API_KEY", "")
        
        # If current model is not in new provider's list, reset to default
        if self.current_model not in preset["models"]:
            self.current_model = preset["default_model"]

    def set_model(self, model: str):
        self.current_model = model
