from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands

from .discord_adapter import (
    DiscordAdapterError,
    DiscordAllowlist,
    DiscordAttachmentPayload,
    DiscordContext,
    DiscordController,
    DiscordSessionLinkStore,
    DiscordWorkflowApiClient,
    RenderedDiscordResult,
    render_outcome_for_discord,
    render_status_for_discord,
)


def _parse_id_set(value: str | None) -> frozenset[int]:
    items: set[int] = set()
    for raw in (value or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        items.add(int(raw))
    return frozenset(items)


def allowlist_from_env() -> DiscordAllowlist:
    return DiscordAllowlist(
        guild_ids=_parse_id_set(os.getenv("DISCORD_ALLOWED_GUILD_IDS")),
        user_ids=_parse_id_set(os.getenv("DISCORD_ALLOWED_USER_IDS")),
        channel_ids=_parse_id_set(os.getenv("DISCORD_ALLOWED_CHANNEL_IDS")),
    )


def discord_context(interaction: discord.Interaction) -> DiscordContext:
    if interaction.channel_id is None:
        raise DiscordAdapterError("Discord channel is required")
    return DiscordContext(
        external_thread_id=str(interaction.channel_id),
        guild_id=interaction.guild_id,
        channel_id=int(interaction.channel_id),
        user_id=int(interaction.user.id),
    )


async def attachment_payload(attachment: discord.Attachment | None) -> DiscordAttachmentPayload | None:
    if attachment is None:
        return None
    data = await attachment.read(use_cached=True)
    return DiscordAttachmentPayload(
        filename=attachment.filename,
        data=data,
        content_type=attachment.content_type,
    )


async def _send_rendered(interaction: discord.Interaction, rendered: RenderedDiscordResult) -> None:
    for message in rendered.messages:
        await interaction.followup.send(message)
    if rendered.filename and rendered.file_bytes is not None:
        await interaction.followup.send(
            file=discord.File(io.BytesIO(rendered.file_bytes), filename=rendered.filename)
        )


class AgentWorkflowDiscordBot(commands.Bot):
    def __init__(self, controller: DiscordController) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.controller = controller
        self._commands_synced = False

    async def setup_hook(self) -> None:
        self._register_commands()
        await self.tree.sync()
        self._commands_synced = True

    def _register_commands(self) -> None:
        @self.tree.command(name="aws_start", description="새 Agent Workflow Session과 Run을 시작합니다.")
        @app_commands.describe(workflow_id="Local UI에서 만든 Workflow ID", prompt="실행할 요청", title="Session 제목")
        async def aws_start(
            interaction: discord.Interaction,
            workflow_id: str,
            prompt: str,
            title: str = "",
        ) -> None:
            await interaction.response.defer(thinking=True)
            try:
                outcome = await self.controller.start(
                    discord_context(interaction),
                    workflow_id=workflow_id,
                    prompt=prompt,
                    title=title,
                )
                await _send_rendered(interaction, render_outcome_for_discord(outcome))
            except DiscordAdapterError as exc:
                await interaction.followup.send(f"요청을 처리하지 못했습니다: {exc}")

        @self.tree.command(name="aws_status", description="현재 Discord Channel/Thread에 연결된 Run 상태를 확인합니다.")
        async def aws_status(interaction: discord.Interaction) -> None:
            await interaction.response.defer(thinking=True)
            try:
                payload = await self.controller.status(discord_context(interaction))
                await _send_rendered(interaction, render_status_for_discord(payload))
            except DiscordAdapterError as exc:
                await interaction.followup.send(f"상태를 확인하지 못했습니다: {exc}")

        @self.tree.command(name="aws_reply", description="Agent가 WAITING_FOR_USER일 때 답변하고 같은 Run을 재개합니다.")
        @app_commands.describe(answer="Agent 질문에 대한 답변")
        async def aws_reply(interaction: discord.Interaction, answer: str) -> None:
            await interaction.response.defer(thinking=True)
            try:
                outcome = await self.controller.reply(discord_context(interaction), answer=answer)
                await _send_rendered(interaction, render_outcome_for_discord(outcome))
            except DiscordAdapterError as exc:
                await interaction.followup.send(f"답변을 반영하지 못했습니다: {exc}")

        @self.tree.command(name="aws_resume", description="PAUSED Run을 수동으로 재개합니다.")
        async def aws_resume(interaction: discord.Interaction) -> None:
            await interaction.response.defer(thinking=True)
            try:
                outcome = await self.controller.resume(discord_context(interaction))
                await _send_rendered(interaction, render_outcome_for_discord(outcome))
            except DiscordAdapterError as exc:
                await interaction.followup.send(f"Run을 재개하지 못했습니다: {exc}")

        @self.tree.command(name="aws_followup", description="완료 결과에 후속 요청과 파일을 제출합니다.")
        @app_commands.describe(
            message="Manager 완료 결과에 대한 후속 요청",
            attachment1="후속 근거 파일 1",
            attachment2="후속 근거 파일 2",
            attachment3="후속 근거 파일 3",
        )
        async def aws_followup(
            interaction: discord.Interaction,
            message: str,
            attachment1: discord.Attachment | None = None,
            attachment2: discord.Attachment | None = None,
            attachment3: discord.Attachment | None = None,
        ) -> None:
            await interaction.response.defer(thinking=True)
            try:
                uploads = []
                for attachment in (attachment1, attachment2, attachment3):
                    payload = await attachment_payload(attachment)
                    if payload is not None:
                        uploads.append(payload)
                outcome = await self.controller.follow_up(
                    discord_context(interaction),
                    content=message,
                    attachments=uploads,
                )
                await _send_rendered(interaction, render_outcome_for_discord(outcome))
            except DiscordAdapterError as exc:
                await interaction.followup.send(f"Follow-up을 처리하지 못했습니다: {exc}")


def build_bot_from_env() -> tuple[AgentWorkflowDiscordBot, DiscordSessionLinkStore]:
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")
    api_base = os.getenv("AWS2_API_BASE_URL", "http://127.0.0.1:8000")
    data_root = Path(os.getenv("AWS2_DATA_DIR", "data")).expanduser().resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    links = DiscordSessionLinkStore.from_sqlite(str(data_root / "domain.sqlite"))
    api = DiscordWorkflowApiClient(api_base)
    controller = DiscordController(api, links, allowlist=allowlist_from_env())
    return AgentWorkflowDiscordBot(controller), links


def run_bot_from_env() -> None:
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")
    bot, links = build_bot_from_env()
    try:
        bot.run(token, log_handler=None)
    finally:
        links.close()
