import logging
import discord
import json
import os
import asyncio
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class FlowInterpreter:
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self.flows_dir = "/app/data/flows"
        os.makedirs(self.flows_dir, exist_ok=True)
        self.flows: List[Dict[str, Any]] = []
        self.load_flows()

    def load_flows(self):
        new_flows = []
        if not os.path.exists(self.flows_dir): return
        for filename in os.listdir(self.flows_dir):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(self.flows_dir, filename), 'r', encoding='utf-8') as f:
                        new_flows.append(json.load(f))
                except Exception as e:
                    logger.error(f"Failed to load flow {filename}: {e}")
        self.flows = new_flows
        logger.info(f"Loaded {len(self.flows)} flows.")

    async def handle_event(self, event_type: str, context: Dict[str, Any]):
        for flow in self.flows:
            if not flow.get("enabled", True): continue
            trigger = flow.get("trigger", {})
            if trigger.get("type") != event_type: continue

            if event_type == "on_message":
                if not await self._check_message_filters(flow, context.get("message")):
                    continue

            # Начинаем выполнение с первого узла
            await self._execute_nodes(flow.get("nodes", []), context)

    async def _check_message_filters(self, flow, message: discord.Message) -> bool:
        if not message or message.author.bot: return False
        filters = flow.get("trigger", {}).get("filters", {})
        content_contains = filters.get("content_contains")
        if content_contains and content_contains.lower() not in message.content.lower():
            return False
        return True

    async def _execute_nodes(self, nodes: List[Dict[str, Any]], context: Dict[str, Any]):
        """
        Исполняет узлы. Поддерживает ветвление через рекурсию или проверку условий.
        """
        for node in nodes:
            node_type = node.get("type")
            data = node.get("data", {})

            try:
                # --- УСЛОВИЯ (Branching) ---
                if node_type == "condition_balance":
                    msg = context.get("message")
                    if msg:
                        bal = await self.db.get_balance(msg.guild.id, msg.author.id)
                        required = data.get("amount", 0)
                        # Если условие верно, выполняем "true_nodes"
                        if bal >= required:
                            await self._execute_nodes(node.get("true_nodes", []), context)
                        else:
                            await self._execute_nodes(node.get("false_nodes", []), context)
                    continue # Пропускаем остальные узлы в текущем списке, так как мы ушли в ветку

                # --- ДЕЙСТВИЯ ---
                elif node_type == "action_reply":
                    msg = context.get("message")
                    if msg: await msg.reply(data.get("text", "..."))

                elif node_type == "action_ai_response":
                    msg = context.get("message")
                    if msg:
                        from bot_app.integrations.ai_client import ask_ai
                        prompt = data.get("system_prompt", "")
                        response = await ask_ai(f"System: {prompt}\nUser: {msg.content}")
                        await msg.reply(response[:2000])

                elif node_type == "action_delay":
                    await asyncio.sleep(data.get("seconds", 1))

                elif node_type == "action_add_role":
                    msg = context.get("message")
                    role = msg.guild.get_role(int(data.get("role_id")))
                    if role: await msg.author.add_roles(role)

                elif node_type == "action_set_balance":
                    msg = context.get("message")
                    if msg: await self.db.update_balance(msg.guild.id, msg.author.id, data.get("amount", 0))

            except Exception as e:
                logger.error(f"Node {node_type} error: {e}")
