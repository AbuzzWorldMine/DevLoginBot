"""HTTP API для плагина. Все запросы (кроме /api/health) требуют заголовок X-Api-Key.

POST   /api/link/code     {uuid, name}            -> {linked, code?, expires_in?}
GET    /api/link/{uuid}                           -> {linked, discord_id?}
DELETE /api/link/{uuid}                           -> {removed}
POST   /api/verify        {uuid, name, ip, timeout} -> {id, status}
GET    /api/verify/{id}                           -> {status}   pending|accepted|denied|expired|failed
GET    /api/health                                -> {ok}                       (публично)
GET    /api/latest                                -> {latest_version, download_url}  (публично)
POST   /api/heartbeat     {server_id, plugin_version, mc_version, software, online}
                                                  -> {latest_version, download_url}  (публично, для статистики)
GET    /stats  (и /api/stats)                     -> панель статистики           (пароль ADMIN_PASSWORD)
"""
import base64
import hmac
import logging
import re
import time

from aiohttp import web

from . import dashboard
from .store import CODE_TTL, FAILED, PENDING, Store, norm_uuid

PUBLIC_PATHS = {"/api/health", "/api/latest", "/api/heartbeat"}
ADMIN_PATHS = {"/", "/stats", "/api/stats", "/api/stats/reset"}
HEARTBEAT_MIN_INTERVAL = 50       # чаще раза в ~минуту с одного сервера не записываем
MAX_SERVERS = 20000               # защита базы от мусорных регистраций
_SAFE = re.compile(r"[^A-Za-z0-9._ +-]")


def _clean(value, limit=32) -> str:
    return _SAFE.sub("", str(value or ""))[:limit] or "?"

log = logging.getLogger("devlogin.api")


def create_app(cfg, store: Store, bot) -> web.Application:
    api_key = cfg.api_key

    def admin_ok(request: web.Request) -> bool:
        """Basic-авторизация для панели: логин любой, пароль = ADMIN_PASSWORD."""
        if not cfg.admin_password:
            return False
        header = request.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            password = base64.b64decode(header[6:]).decode("utf-8").partition(":")[2]
        except Exception:
            return False
        return hmac.compare_digest(password.encode(), cfg.admin_password.encode())

    @web.middleware
    async def auth(request: web.Request, handler):
        path = request.path
        if path in ADMIN_PATHS:
            if not cfg.admin_password:
                return web.Response(status=404, text="Панель отключена: задайте ADMIN_PASSWORD")
            if not admin_ok(request):
                return web.Response(status=401, text="Нужен пароль",
                                    headers={"WWW-Authenticate": 'Basic realm="DevLogin stats"'})
        elif path not in PUBLIC_PATHS:
            given = request.headers.get("X-Api-Key", "")
            if not hmac.compare_digest(given.encode(), api_key.encode()):
                return web.json_response({"error": "unauthorized"}, status=401)
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except ValueError as e:
            return web.json_response({"error": "bad_request", "detail": str(e)}, status=400)
        except Exception:
            log.exception("Ошибка обработчика %s", request.path)
            return web.json_response({"error": "internal"}, status=500)

    async def body(request: web.Request) -> dict:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("ожидался JSON-объект")
        return data

    async def health(_):
        return web.json_response({"ok": True, "bot_ready": bot.is_ready()})

    async def link_code(request):
        data = await body(request)
        uuid = norm_uuid(data.get("uuid"))
        if store.get_link(uuid):
            return web.json_response({"linked": True})
        code = store.create_code(uuid, str(data.get("name", ""))[:32])
        return web.json_response({"linked": False, "code": code, "expires_in": CODE_TTL})

    async def link_get(request):
        uuid = norm_uuid(request.match_info["uuid"])
        did = store.get_link(uuid)
        return web.json_response({"linked": did is not None, "discord_id": did})

    async def link_delete(request):
        uuid = norm_uuid(request.match_info["uuid"])
        return web.json_response({"removed": store.remove_link(uuid)})

    async def verify_create(request):
        data = await body(request)
        uuid = norm_uuid(data.get("uuid"))
        did = store.get_link(uuid)
        if did is None:
            return web.json_response({"error": "not_linked"}, status=404)
        timeout = max(10, min(int(data.get("timeout", 60)), 300))
        name = str(data.get("name", ""))[:32]
        ip = str(data.get("ip", "unknown"))[:64]
        vid = store.create_verification(uuid, name, ip, did, timeout)
        if not await bot.send_verification(vid, did, name, ip):
            store.set_status(vid, FAILED)
            return web.json_response({"id": vid, "status": FAILED})
        return web.json_response({"id": vid, "status": PENDING})

    async def verify_get(request):
        v = store.get_verification(request.match_info["id"])
        if v is None:
            return web.json_response({"error": "not_found"}, status=404)
        return web.json_response({"status": v.status})

    def latest_payload() -> dict:
        return {"latest_version": cfg.latest_version or None, "download_url": cfg.download_url or None}

    async def latest(_):
        return web.json_response(latest_payload())

    async def heartbeat(request):
        """Анонимный «пульс» сервера: id, версии, число игроков. Ников и IP не сохраняем."""
        data = await body(request)
        sid = norm_uuid(data.get("server_id"))
        last = store.last_heartbeat(sid)
        too_soon = last is not None and time.time() - last < HEARTBEAT_MIN_INTERVAL
        full = last is None and store.server_count() >= MAX_SERVERS
        if not too_soon and not full:
            try:
                online = max(0, min(int(data.get("online", 0)), 100000))
            except (TypeError, ValueError):
                online = 0
            store.record_heartbeat(sid, _clean(data.get("plugin_version")), _clean(data.get("mc_version")),
                                   _clean(data.get("software")), online)
        return web.json_response(latest_payload())

    async def stats_json(_):
        return web.json_response(store.stats())

    async def stats_reset(_):
        store.reset_stats()
        raise web.HTTPSeeOther("/stats")

    async def stats_page(_):
        html = dashboard.render(store.stats(), cfg.latest_version)
        return web.Response(text=html, content_type="text/html", headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        })

    async def root(_):
        raise web.HTTPFound("/stats")

    app = web.Application(middlewares=[auth], client_max_size=16 * 1024)
    app.add_routes([
        web.get("/", root),
        web.get("/stats", stats_page),
        web.get("/api/stats", stats_json),
        web.post("/api/stats/reset", stats_reset),
        web.get("/api/latest", latest),
        web.post("/api/heartbeat", heartbeat),
        web.get("/api/health", health),
        web.post("/api/link/code", link_code),
        web.get("/api/link/{uuid}", link_get),
        web.delete("/api/link/{uuid}", link_delete),
        web.post("/api/verify", verify_create),
        web.get("/api/verify/{id}", verify_get),
    ])
    return app
