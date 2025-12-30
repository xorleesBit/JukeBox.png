import logging
import discord
import json
import os
import asyncio
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class FlowInterpreter:
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self.flows_dir = "/app/data/flows"
        self.flows = []
        self.load_flows()

    def load_flows(self):
        self.flows = []
        if not os.path.exists(self.flows_dir): return
        for filename in os.listdir(self.flows_dir):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(self.flows_dir, filename), 'r', encoding='utf-8') as f:
                        flow = json.load(f)
                        # Index nodes by ID for fast lookup if needed
                        self.flows.append(flow)
                except Exception as e:
                    logger.error(f"Failed to load flow {filename}: {e}")
        logger.info(f"Loaded {len(self.flows)} flows.")

    async def handle_event(self, event_type: str, initial_data: Dict[str, Any]):
        """Main entry point for events (e.g. on_message)."""
        for flow in self.flows:
            trigger = flow.get("data", {}).get("trigger", {})
            if trigger.get("type") != event_type: continue

            # Filter Check
            if event_type == "on_message":
                msg = initial_data.get("message")
                filters = trigger.get("filters", {})
                if filters.get("content_contains") and filters.get("content_contains").lower() not in msg.content.lower():
                    continue

            # Start Execution
            # We assume linear execution for now based on 'nodes' list order from save
            # In a graph engine, we would traverse edges.
            context = {"trigger": self._serialize_initial_data(initial_data)}
            
            await self._execute_sequence(flow.get("data", {}).get("nodes", []), context, initial_data)

    def _serialize_initial_data(self, data):
        """Converts Discord objects to JSON-serializable dict for context."""
        res = {}
        if "message" in data:
            m = data["message"]
            res["message"] = {
                "id": m.id,
                "content": m.content,
                "author": {"id": m.author.id, "name": m.author.name, "display_name": m.author.display_name},
                "channel_id": m.channel.id,
                "guild_id": m.guild.id if m.guild else None
            }
        return res

    async def _execute_sequence(self, nodes: List[dict], context: Dict[str, Any], raw_objects: Dict[str, Any]):
        """Executes a list of nodes sequentially, passing context."""
        
        for i, node in enumerate(nodes):
            node_type = node.get("type")
            node_id = node.get("id", f"step_{i}") # Fallback ID
            params = node.get("data", {})

            # 1. Resolve Variables (e.g. {{trigger.message.content}})
            resolved_params = self._resolve_params(params, context)

            try:
                output = {}
                
                # --- ACTIONS ---
                if node_type == "action_reply":
                    text = resolved_params.get("text", "")
                    msg = raw_objects.get("message")
                    if msg and text:
                        sent = await msg.reply(text)
                        output = {"sent_message_id": sent.id, "content": sent.content}

                elif node_type == "action_ai_response":
                    prompt = resolved_params.get("system_prompt", "")
                    from bot_app.integrations.ai_client import ask_ai
                    # Inject last user message context automatically
                    last_msg = context.get("trigger", {}).get("message", {}).get("content", "")
                    full_prompt = f"System: {prompt}\nUser: {last_msg}"
                    
                    resp = await ask_ai(full_prompt)
                    
                    # Auto-reply if implicit
                    msg = raw_objects.get("message")
                    if msg: await msg.reply(resp)
                    output = {"response": resp}

                elif node_type == "action_delay":
                    sec = float(resolved_params.get("seconds", 1))
                    await asyncio.sleep(sec)
                    output = {"slept": sec}

                elif node_type == "action_role":
                    rid = int(resolved_params.get("role_id", 0))
                    msg = raw_objects.get("message")
                    if msg and rid:
                        role = msg.guild.get_role(rid)
                        if role:
                            await msg.author.add_roles(role)
                            output = {"added_role": role.name}
                        else:
                            output = {"error": "Role not found"}

                # 2. Save Output to Context
                context[node_type] = output # Simple namespacing by type (better by ID in future)
                context[f"step_{i}"] = output

            except Exception as e:
                logger.error(f"Node {node_type} failed: {e}")
                context[f"step_{i}_error"] = str(e)

    def _resolve_params(self, params: dict, context: dict) -> dict:
        """Recursively replaces {{key.path}} strings with values from context."""
        resolved = {}
        for k, v in params.items():
            if isinstance(v, str):
                resolved[k] = self._replace_variables(v, context)
            else:
                resolved[k] = v
        return resolved

    def _replace_variables(self, text: str, context: dict) -> str:
        """Replaces {{ trigger.message.content }} -> 'Hello'."""
        def replacer(match):
            path = match.group(1).strip().split('.')
            val = context
            try:
                for part in path:
                    val = val[part]
                return str(val)
            except (KeyError, TypeError, AttributeError):
                return match.group(0) # Keep original if not found

        return re.sub(r'{{(.*?)}}', replacer, text)