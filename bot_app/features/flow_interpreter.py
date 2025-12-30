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
        """Main entry point for events."""
        for flow in self.flows:
            data = flow.get("data", {})
            trigger_conf = data.get("trigger", {})
            
            if trigger_conf.get("type") != event_type: 
                continue

            # Фильтрация по содержимому (для сообщений)
            if "on_message" in event_type:
                msg = initial_data.get("message")
                filters = trigger_conf.get("filters", {})
                content_filter = filters.get("content_contains")
                if content_filter and content_filter.lower() not in msg.content.lower():
                    continue

            # Инициализация контекста
            context = {"trigger": self._serialize_obj(initial_data)}
            
            nodes = data.get("nodes", [])
            edges = data.get("edges", [])
            
            start_node = next((n for n in nodes if n["type"] == "trigger"), None)
            if not start_node: continue

            asyncio.create_task(self._execute_graph(start_node, nodes, edges, context, initial_data))

    async def _execute_graph(self, current_node: dict, nodes: List[dict], edges: List[dict], context: Dict[str, Any], raw_objects: Dict[str, Any]):
        queue = [current_node]
        steps = 0
        max_steps = 100 

        while queue and steps < max_steps:
            node = queue.pop(0)
            steps += 1
            node_id = node.get("id")
            node_type = node.get("type")
            
            success = await self._execute_node_logic(node, context, raw_objects)
            if not success: continue

            outgoing_edges = [e for e in edges if e["source"] == node_id]
            
            if node_type == "logic_if":
                result = context.get(node_id, {}).get("result", False)
                target_handle = "true" if result else "false"
                outgoing_edges = [e for e in outgoing_edges if e.get("sourceHandle") == target_handle]

            for edge in outgoing_edges:
                target_node = next((n for n in nodes if n["id"] == edge["target"]), None)
                if target_node: queue.append(target_node)

    async def _execute_node_logic(self, node: dict, context: Dict[str, Any], raw_objects: Dict[str, Any]) -> bool:
        node_type = node.get("type")
        node_id = node.get("id")
        params = node.get("data", {})
        resolved_params = self._resolve_params(params, context)
        
        try:
            output = {}
            
            if node_type == "trigger":
                output = context.get("trigger", {})

            elif node_type == "action_reply":
                text = resolved_params.get("text", "")
                msg = raw_objects.get("message")
                if msg and text:
                    sent = await msg.reply(text)
                    output = {"sent_message_id": sent.id, "content": sent.content}

            elif node_type == "action_ai":
                prompt = resolved_params.get("prompt", "")
                from bot_app.integrations.ai_client import ask_ai
                
                user_input = context.get("trigger", {}).get("message", {}).get("content", "No content")
                resp = await ask_ai(f"System: {prompt}\nUser: {user_input}")
                
                msg = raw_objects.get("message")
                if msg: await msg.reply(resp)
                output = {"response": resp}

            elif node_type == "logic_code":
                # Внедряем узел Code (Python)
                code = params.get("code", "")
                # Ограниченное окружение для безопасности
                exec_globals = {"context": context, "discord": discord, "result": {}}
                
                # Выполняем в отдельном потоке, чтобы не вешать бота (если код сложный)
                def run_code():
                    exec(code, exec_globals)
                    return exec_globals.get("result", {})

                output = await asyncio.to_thread(run_code)

            elif node_type == "logic_if":
                val1 = resolved_params.get("value1")
                op = resolved_params.get("operator", "==")
                val2 = resolved_params.get("value2")
                
                res = False
                try:
                    # Попытка сравнения чисел
                    v1, v2 = float(val1), float(val2)
                    if op == "==": res = (v1 == v2)
                    elif op == "!=": res = (v1 != v2)
                    elif op == ">": res = (v1 > v2)
                    elif op == "<": res = (v1 < v2)
                except:
                    # Сравнение строк
                    if op == "==": res = (str(val1) == str(val2))
                    elif op == "!=": res = (str(val1) != str(val2))
                    elif op == "contains": res = (str(val2).lower() in str(val1).lower())
                
                output = {"result": res}

            # Сохраняем в контекст под ID узла и типом
            context[node_id] = output
            context[node_type] = output
            return True

        except Exception as e:
            logger.error(f"Node {node_type} ({node_id}) failed: {e}")
            context[f"{node_id}_error"] = str(e)
            return False

    def _serialize_obj(self, data):
        """Превращает объекты Discord в словари для доступа в шаблонах."""
        res = {}
        if "message" in data:
            m = data["message"]
            res["message"] = {
                "id": m.id,
                "content": m.content,
                "author": {"id": m.author.id, "name": m.author.name, "mention": m.author.mention},
                "guild": {"id": m.guild.id, "name": m.guild.name} if m.guild else None,
                "channel_id": m.channel.id
            }
        if "member" in data:
            m = data["member"]
            res["member"] = {"id": m.id, "name": m.name, "mention": m.mention}
        if "guild" in data:
            g = data["guild"]
            res["guild"] = {"id": g.id, "name": g.name}
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
        def replacer(match):
            path = match.group(1).strip().split('.')
            val = context
            try:
                for part in path: val = val[part]
                return str(val)
            except: return match.group(0)
        return re.sub(r'{{(.*?)}}', replacer, text)
