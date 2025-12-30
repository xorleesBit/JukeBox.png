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
                        self.flows.append(flow)
                except Exception as e:
                    logger.error(f"Failed to load flow {filename}: {e}")
        logger.info(f"Loaded {len(self.flows)} flows.")

    async def handle_event(self, event_type: str, initial_data: Dict[str, Any]):
        """Main entry point for events (e.g. on_message)."""
        for flow in self.flows:
            data = flow.get("data", {})
            trigger_conf = data.get("trigger", {})
            
            # 1. Validate Trigger Type
            if trigger_conf.get("type") != event_type: 
                continue

            # 2. Validate Filters
            if event_type == "on_message":
                msg = initial_data.get("message")
                filters = trigger_conf.get("filters", {})
                content_filter = filters.get("content_contains")
                if content_filter and content_filter.lower() not in msg.content.lower():
                    continue

            # 3. Initialize Context
            context = {"trigger": self._serialize_initial_data(initial_data)}
            
            # 4. Find Start Node (The Trigger Node)
            nodes = data.get("nodes", [])
            edges = data.get("edges", [])
            
            start_node = next((n for n in nodes if n["type"] == "trigger"), None)
            if not start_node:
                logger.warning(f"Flow {flow.get('name')} has no trigger node.")
                continue

            # 5. Start Graph Traversal
            # We use a task to not block the event loop
            asyncio.create_task(self._execute_graph(start_node, nodes, edges, context, initial_data))

    async def _execute_graph(self, current_node: dict, nodes: List[dict], edges: List[dict], context: Dict[str, Any], raw_objects: Dict[str, Any]):
        """
        Executes the graph using a queue-based approach.
        """
        queue = [current_node]
        
        # Safety: Prevent infinite loops (max steps)
        steps = 0
        max_steps = 100 

        while queue and steps < max_steps:
            node = queue.pop(0)
            steps += 1
            node_id = node.get("id")
            node_type = node.get("type")
            
            # Execute Node Logic
            success = await self._execute_node_logic(node, context, raw_objects)
            
            if not success:
                continue

            # Find Next Nodes
            outgoing_edges = [e for e in edges if e["source"] == node_id]
            
            # --- Branching Logic ---
            if node_type == "logic_if":
                # Check result in context
                result = context.get(node_id, {}).get("result", False)
                # Filter edges by sourceHandle ('true' or 'false')
                target_handle = "true" if result else "false"
                outgoing_edges = [e for e in outgoing_edges if e.get("sourceHandle") == target_handle]

            for edge in outgoing_edges:
                target_id = edge["target"]
                target_node = next((n for n in nodes if n["id"] == target_id), None)
                if target_node:
                    queue.append(target_node)

    async def _execute_node_logic(self, node: dict, context: Dict[str, Any], raw_objects: Dict[str, Any]) -> bool:
        """Executes a single node. Returns True if successful."""
        node_type = node.get("type")
        node_id = node.get("id")
        params = node.get("data", {})
        
        # Resolve Variables
        resolved_params = self._resolve_params(params, context)
        
        try:
            output = {}
            
            if node_type == "trigger":
                pass

            elif node_type == "action_reply":
                text = resolved_params.get("text", "")
                msg = raw_objects.get("message")
                if msg and text:
                    sent = await msg.reply(text)
                    output = {"sent_message_id": sent.id, "content": sent.content}

            elif node_type == "action_ai":
                prompt = resolved_params.get("prompt", "")
                from bot_app.integrations.ai_client import ask_ai
                
                last_msg = context.get("trigger", {}).get("message", {}).get("content", "")
                full_prompt = f"System: {prompt}\nUser: {last_msg}"
                
                resp = await ask_ai(full_prompt)
                
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

            elif node_type == "logic_if":
                val1 = resolved_params.get("value1")
                op = resolved_params.get("operator", "==")
                val2 = resolved_params.get("value2")
                
                # Simple type casting if numbers
                try:
                    if str(val1).isdigit(): val1 = float(val1)
                    if str(val2).isdigit(): val2 = float(val2)
                except: pass

                res = False
                if op == "==": res = (val1 == val2)
                elif op == "!=": res = (val1 != val2)
                elif op == ">": res = (float(val1) > float(val2))
                elif op == "<": res = (float(val1) < float(val2))
                elif op == "contains": res = (str(val2).lower() in str(val1).lower())
                
                output = {"result": res, "val1": val1, "val2": val2}

            # Save Output
            context[node_id] = output
            context[node_type] = output
            
            return True

        except Exception as e:
            logger.error(f"Node {node_type} ({node_id}) failed: {e}")
            context[f"{node_id}_error"] = str(e)
            return False

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

    def _resolve_params(self, params: dict, context: dict) -> dict:
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
                return match.group(0)

        return re.sub(r'{{(.*?)}}', replacer, text)