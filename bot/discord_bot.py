"""Discord-часть: привязка по `!link КОД` в ЛС и кнопки подтверждения входа."""
import asyncio
import logging

import discord

from .messages import Messages
from .store import ACCEPTED, DENIED, EXPIRED, Store

log = logging.getLogger("devlogin.bot")


class MinecraftBot(discord.Client):
    def __init__(self, store: Store, messages: Messages):
        intents = discord.Intents.default()
        intents.message_content = True  # нужно для чтения `!link` (включите Message Content Intent в портале)
        intents.dm_messages = True
        super().__init__(intents=intents)
        self.store = store
        self.msg = messages
        self._expire_task = None

    async def setup_hook(self):
        self._expire_task = asyncio.create_task(self._expire_loop())

    async def on_ready(self):
        log.info("Бот запущен: %s", self.user)

    # ---------- привязка ----------
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is not None:
            return
        self.store.record_dm(str(message.author.id))  # статистика: кто пишет боту в ЛС
        text = message.content.strip()
        if not text.lower().startswith("!link"):
            return
        parts = text.split()
        if len(parts) != 2:
            await message.channel.send(self.msg.get("link_usage"))
            return

        discord_id = str(message.author.id)
        code = parts[1].upper()

        owner = self.store.get_link_owner(discord_id)
        if owner:
            await message.channel.send(self.msg.get("link_already_linked", player=owner["name"] or owner["uuid"][:8]))
            return

        result = self.store.consume_code(code, discord_id)
        if result is None:
            await message.channel.send(self.msg.get("link_invalid_code", code=code))
            return
        _, name = result
        await message.channel.send(self.msg.get("link_success", player=name))

    # ---------- подтверждение входа ----------
    async def send_verification(self, vid: str, discord_id: str, player: str, ip: str) -> bool:
        """Отправляет ЛС с кнопками. False — если написать пользователю не удалось."""
        try:
            user = await self.fetch_user(int(discord_id))
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.success, label=self.msg.get("button_accept"),
                custom_id=f"verify:{vid}:accept"))
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.danger, label=self.msg.get("button_deny"),
                custom_id=f"verify:{vid}:deny"))
            text = self.msg.get("verify_header") + "\n\n" + self.msg.get("verify_body", player=player, ip=ip)
            sent = await user.send(text, view=view)
            self.store.set_message(vid, str(sent.id))
            return True
        except (discord.HTTPException, ValueError) as e:
            log.warning("Не удалось отправить ЛС %s: %s", discord_id, e)
            return False

    async def on_interaction(self, interaction: discord.Interaction):
        # Обрабатываем кнопки сами (а не через View), чтобы они работали и после перезапуска бота.
        if interaction.type != discord.InteractionType.component:
            return
        cid = (interaction.data or {}).get("custom_id", "")
        if not cid.startswith("verify:"):
            return
        try:
            _, vid, action = cid.split(":")
        except ValueError:
            return

        v = self.store.get_verification(vid)
        if v is None:
            await interaction.response.send_message(self.msg.get("already_handled"), ephemeral=True)
            return
        if str(interaction.user.id) != v.discord_id:
            await interaction.response.send_message(self.msg.get("not_yours"), ephemeral=True)
            return

        status = ACCEPTED if action == "accept" else DENIED
        if not self.store.set_status(vid, status):
            await interaction.response.edit_message(view=None)
            return
        text = self.msg.get("verify_accept" if status == ACCEPTED else "verify_deny", player=v.name, ip=v.ip)
        await interaction.response.edit_message(content=text, view=None)

    async def _expire_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                for v in self.store.expire_due():
                    await self._edit_expired(v)
            except Exception:  # цикл не должен умирать из-за одной ошибки
                log.exception("Ошибка в цикле истечения запросов")
            await asyncio.sleep(10)

    async def _edit_expired(self, v):
        if not v.message_id:
            return
        try:
            user = await self.fetch_user(int(v.discord_id))
            dm = user.dm_channel or await user.create_dm()
            msg = await dm.fetch_message(int(v.message_id))
            await msg.edit(content=self.msg.get("verify_timeout"), view=None)
        except discord.HTTPException:
            pass

    async def close(self):
        if self._expire_task:
            self._expire_task.cancel()
        await super().close()
