import discord
from bot_app.features.ai_manager import PRESETS
from bot_app.core.state import ai_manager

class ProviderSelect(discord.ui.Select):
    def __init__(self, current_val):
        options = []
        for pid, pdata in PRESETS.items():
            is_def = (pid == current_val)
            options.append(discord.SelectOption(label=pdata['name'], value=pid, default=is_def, description=pdata['base_url'][:50]))
        
        super().__init__(placeholder="Выберите провайдера...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        ai_manager.set_provider(self.values[0])
        await ai_manager.save()
        await interaction.response.edit_message(embed=build_ai_embed(), view=AIConfigView())

class ModelSelect(discord.ui.Select):
    def __init__(self, provider_id, current_model):
        options = []
        if provider_id in PRESETS:
            models = PRESETS[provider_id]['models']
            for m in models:
                is_def = (m == current_model)
                label = m.split('/')[-1] if '/' in m else m
                options.append(discord.SelectOption(label=label[:100], value=m, default=is_def, description=m[:100]))
        
        if not options:
            options.append(discord.SelectOption(label="Custom Model", value="custom"))

        super().__init__(placeholder="Выберите модель...", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        ai_manager.set_model(self.values[0])
        await ai_manager.save()
        await interaction.response.edit_message(embed=build_ai_embed(), view=AIConfigView())

class AIConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(ProviderSelect(ai_manager.current_provider))
        self.add_item(ModelSelect(ai_manager.current_provider, ai_manager.current_model))

    @discord.ui.button(label="Проверить", style=discord.ButtonStyle.success, row=2)
    async def test_btn(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True)
        from bot_app.integrations.ai_client import ask_ai
        res = await ask_ai("Say 'Hello' only.", retries=1)
        await interaction.followup.send(f"🤖 Ответ: {res}", ephemeral=True)

def build_ai_embed():
    p = ai_manager.current_provider
    m = ai_manager.current_model
    u = ai_manager.current_url
    
    e = discord.Embed(title="🧠 Настройки AI", color=discord.Color.gold())
    e.add_field(name="Провайдер", value=PRESETS.get(p, {}).get('name', p), inline=True)
    e.add_field(name="Модель", value=f"`{m}`", inline=True)
    e.add_field(name="URL", value=f"`{u}`", inline=False)
    
    # Check Key
    k_status = "✅ Задан" if ai_manager.current_key else "❌ НЕ ЗАДАН (Проверьте .env)"
    e.add_field(name="API Key", value=k_status, inline=True)
    
    if p == "openrouter":
        e.set_footer(text="OpenRouter Free модели могут иметь очередь.")
    
    return e
