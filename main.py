"""Точка входа: запускает HTTP API для плагина и Discord-бота в одном процессе."""
import asyncio
import logging

from aiohttp import web

from bot.api import create_app
from bot.config import Config
from bot.discord_bot import MinecraftBot
from bot.messages import Messages
from bot.store import Store


async def run() -> None:
    cfg = Config.load()
    store = Store(cfg.db_path)
    bot = MinecraftBot(store, Messages())

    runner = web.AppRunner(create_app(cfg, store, bot))
    await runner.setup()
    await web.TCPSite(runner, cfg.host, cfg.port).start()
    log = logging.getLogger("devlogin")
    log.info("API слушает %s:%s", cfg.host, cfg.port)
    if cfg.admin_password:
        log.info("Панель статистики: /stats")
    else:
        log.info("ADMIN_PASSWORD не задан — панель статистики отключена.")

    try:
        async with bot:
            await bot.start(cfg.token)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
