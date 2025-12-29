import logging
import discord
import json
import os
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
        """Загружает все JSON файлы из папки flows."""
        new_flows = []
        if not os.path.exists(self.flows_dir):
            return

        for filename in os.listdir(self.flows_dir):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(self.flows_dir, filename), 'r', encoding='utf-8') as f:
                        flow = json.load(f)
                        new_flows.append(flow)
                except Exception as e:
                    logger.error(f"Failed to load flow {filename}: {e}")
        
        self.flows = new_flows
        logger.info(f"Loaded {len(self.flows)} custom flows. Hot-reload complete.")

    async def handle_event(self, event_type: str, context: Dict[str, Any]):
        for flow in self.flows:
            if not flow.get("enabled", True): continue
            
            trigger = flow.get("trigger", {})
            if trigger.get("type") != event_type:
                continue

            if event_type == "on_message":
                if not await self._check_message_filters(flow, context.get("message")):
                    continue

            await self._execute_nodes(flow.get("nodes", []), context)

    async def _check_message_filters(self, flow, message: discord.Message) -> bool:
        if not message or message.author.bot:
            return False
        
        filters = flow.get("trigger", {}).get("filters", {})
        
        # Фильтр по содержимому (регистронезависимый)
        content_contains = filters.get("content_contains")
        if content_contains and content_contains.lower() not in message.content.lower():
            return False
            
        return True

    async def _execute_nodes(self, nodes: List[Dict[str, Any]], context: Dict[str, Any]):
        for node in nodes:
            node_type = node.get("type")
            data = node.get("data", {})

            try:
                # 1. Простой ответ
                if node_type == "action_reply":
                    msg = context.get("message")
                    if msg: await msg.reply(data.get("text", "..."))

                # 2. Начисление XP
                elif node_type == "action_add_xp":
                    msg = context.get("message")
                    if msg and self.db:
                        await self.db.add_xp_and_words(msg.guild.id, msg.author.id, data.get("amount", 0), 0, 0)

                # 3. Выдача роли
                elif node_type == "action_add_role":
                    msg = context.get("message")
                    role_id = data.get("role_id")
                    if msg and role_id:
                        role = msg.guild.get_role(int(role_id))
                        if role: await msg.author.add_roles(role)

                # 4. Ответ через AI (НОВОЕ)
                elif node_type == "action_ai_response":
                    msg = context.get("message")
                    if msg and hasattr(self.bot, 'ai_manager'):
                        from bot_app.integrations.ai_client import ask_ai
                        prompt = data.get("system_prompt", "Ответь как дружелюбный бот.")
                        user_input = msg.content
                        response = await ask_ai(f"System: {prompt}\nUser: {user_input}")
                        await msg.reply(response[:2000])

                # 5. Отправка Embed (НОВОЕ)
                elif node_type == "action_send_embed":
                    msg = context.get("message")
                    if msg:
                        embed = discord.Embed(
                            title=data.get("title"),
                            description=data.get("description"),
                            color=int(data.get("color", "0x3498db"), 16)
                        )
                        await msg.channel.send(embed=embed)

            except Exception as e:
                logger.error(f"Error executing node {node_type}: {e}")