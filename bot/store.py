"""Хранилище на SQLite: привязки, коды привязки и запросы подтверждения входа."""
import datetime
import secrets
import sqlite3
import time
import uuid as uuidlib
from dataclasses import dataclass
from typing import Optional

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_TTL = 10 * 60

PENDING, ACCEPTED, DENIED, EXPIRED, FAILED = "pending", "accepted", "denied", "expired", "failed"


def norm_uuid(value: str) -> str:
    """Приводит UUID к одному виду; бросает ValueError на мусоре."""
    return str(uuidlib.UUID(str(value)))


@dataclass
class Verification:
    id: str
    uuid: str
    name: str
    ip: str
    discord_id: str
    status: str
    expires: float
    message_id: Optional[str]


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS links (
                uuid TEXT PRIMARY KEY, discord_id TEXT NOT NULL UNIQUE, name TEXT);
            CREATE TABLE IF NOT EXISTS codes (
                code TEXT PRIMARY KEY, uuid TEXT NOT NULL, name TEXT, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS verifications (
                id TEXT PRIMARY KEY, uuid TEXT NOT NULL, name TEXT, ip TEXT,
                discord_id TEXT NOT NULL, status TEXT NOT NULL, expires REAL NOT NULL,
                message_id TEXT);
            CREATE TABLE IF NOT EXISTS events (
                day TEXT NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (day, kind));
            CREATE TABLE IF NOT EXISTS dm_users (
                discord_id TEXT PRIMARY KEY, first_seen REAL NOT NULL,
                last_seen REAL NOT NULL, messages INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS servers (
                server_id TEXT PRIMARY KEY, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
                plugin_version TEXT, mc_version TEXT, software TEXT,
                online INTEGER NOT NULL DEFAULT 0, pulses INTEGER NOT NULL DEFAULT 0);
            """
        )
        try:  # миграция старых баз: дата привязки
            self.db.execute("ALTER TABLE links ADD COLUMN created REAL")
        except sqlite3.OperationalError:
            pass
        self.db.commit()

    # ---------- статистика ----------
    @staticmethod
    def _today() -> str:
        return datetime.datetime.now(datetime.timezone.utc).date().isoformat()

    def bump(self, kind: str, n: int = 1) -> None:
        """Увеличивает дневной счётчик события (для графиков)."""
        self.db.execute(
            "INSERT INTO events (day, kind, n) VALUES (?,?,?) "
            "ON CONFLICT(day, kind) DO UPDATE SET n = n + excluded.n",
            (self._today(), kind, n),
        )
        self.db.commit()

    def record_dm(self, discord_id: str) -> None:
        """Любое личное сообщение боту: считаем уникальных пользователей и сообщения."""
        now = time.time()
        row = self.db.execute("SELECT 1 FROM dm_users WHERE discord_id=?", (discord_id,)).fetchone()
        if row:
            self.db.execute("UPDATE dm_users SET last_seen=?, messages=messages+1 WHERE discord_id=?", (now, discord_id))
        else:
            self.db.execute("INSERT INTO dm_users VALUES (?,?,?,1)", (discord_id, now, now))
            self.bump("dm_new_user")
        self.bump("dm_message")
        self.db.commit()

    def record_heartbeat(self, server_id: str, plugin_version: str, mc_version: str,
                         software: str, online: int) -> None:
        now = time.time()
        self.db.execute(
            """INSERT INTO servers (server_id, first_seen, last_seen, plugin_version, mc_version, software, online, pulses)
               VALUES (?,?,?,?,?,?,?,1)
               ON CONFLICT(server_id) DO UPDATE SET last_seen=excluded.last_seen,
                 plugin_version=excluded.plugin_version, mc_version=excluded.mc_version,
                 software=excluded.software, online=excluded.online, pulses=pulses+1""",
            (server_id, now, now, plugin_version, mc_version, software, online),
        )
        self.db.commit()

    def reset_stats(self) -> None:
        """Полный сброс статистики: счётчики, сообщения боту, флот серверов и текущие верификации.
        Привязки Discord-аккаунтов (links) и активные коды привязки НЕ трогаются — это не статистика,
        а рабочие данные, нужные игрокам для входа."""
        self.db.executescript(
            "DELETE FROM events; DELETE FROM dm_users; DELETE FROM servers; DELETE FROM verifications;"
        )
        self.db.commit()

    def server_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM servers").fetchone()[0]

    def last_heartbeat(self, server_id: str) -> Optional[float]:
        row = self.db.execute("SELECT last_seen FROM servers WHERE server_id=?", (server_id,)).fetchone()
        return row["last_seen"] if row else None

    def stats(self, days: int = 14) -> dict:
        """Сводка для панели: итоги, серверы, графики за последние дни."""
        now = time.time()
        q = self.db.execute

        totals = {r["kind"]: r["total"] for r in q("SELECT kind, SUM(n) AS total FROM events GROUP BY kind")}

        today = datetime.datetime.now(datetime.timezone.utc).date()
        day_list = [(today - datetime.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
        series = {}
        for r in q("SELECT day, kind, n FROM events WHERE day>=?", (day_list[0],)):
            series.setdefault(r["kind"], {})[r["day"]] = r["n"]
        daily = {kind: [vals.get(d, 0) for d in day_list] for kind, vals in series.items()}

        def count(sql, *args):
            return q(sql, args).fetchone()[0]

        servers = [dict(r) for r in q("SELECT * FROM servers ORDER BY last_seen DESC LIMIT 200")]
        versions, mc_versions = {}, {}
        for r in q("SELECT plugin_version, COUNT(*) c FROM servers WHERE last_seen>? GROUP BY plugin_version", (now - 7 * 86400,)):
            versions[r["plugin_version"] or "?"] = r["c"]
        for r in q("SELECT mc_version, COUNT(*) c FROM servers WHERE last_seen>? GROUP BY mc_version", (now - 7 * 86400,)):
            mc_versions[r["mc_version"] or "?"] = r["c"]

        return {
            "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "discord": {
                "dm_users": count("SELECT COUNT(*) FROM dm_users"),
                "dm_users_7d": count("SELECT COUNT(*) FROM dm_users WHERE last_seen>?", now - 7 * 86400),
                "dm_messages": totals.get("dm_message", 0),
                "linked_accounts": count("SELECT COUNT(*) FROM links"),
                "link_codes": totals.get("link_code", 0),
                "links_done": totals.get("link_done", 0),
                "unlinks": totals.get("unlink", 0),
            },
            "verifications": {
                "created": totals.get("verify_created", 0),
                "accepted": totals.get("verify_accepted", 0),
                "denied": totals.get("verify_denied", 0),
                "expired": totals.get("verify_expired", 0),
                "failed": totals.get("verify_failed", 0),
            },
            "servers": {
                "total": count("SELECT COUNT(*) FROM servers"),
                "active_24h": count("SELECT COUNT(*) FROM servers WHERE last_seen>?", now - 86400),
                "active_7d": count("SELECT COUNT(*) FROM servers WHERE last_seen>?", now - 7 * 86400),
                "online_now": count("SELECT COUNT(*) FROM servers WHERE last_seen>?", now - 4 * 3600),
                "players_now": count("SELECT COALESCE(SUM(online),0) FROM servers WHERE last_seen>?", now - 4 * 3600),
                "plugin_versions": versions,
                "mc_versions": mc_versions,
                "list": servers,
            },
            "daily": {"days": day_list, "series": daily},
        }

    # ---------- привязки ----------
    def get_link(self, uuid: str) -> Optional[str]:
        row = self.db.execute("SELECT discord_id FROM links WHERE uuid=?", (uuid,)).fetchone()
        return row["discord_id"] if row else None

    def get_link_owner(self, discord_id: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT uuid, name FROM links WHERE discord_id=?", (discord_id,)).fetchone()

    def remove_link(self, uuid: str) -> bool:
        cur = self.db.execute("DELETE FROM links WHERE uuid=?", (uuid,))
        self.db.execute("DELETE FROM codes WHERE uuid=?", (uuid,))
        self.db.commit()
        if cur.rowcount > 0:
            self.bump("unlink")
        return cur.rowcount > 0

    # ---------- коды ----------
    def create_code(self, uuid: str, name: str) -> str:
        now = time.time()
        self.db.execute("DELETE FROM codes WHERE expires<=?", (now,))
        row = self.db.execute("SELECT code FROM codes WHERE uuid=?", (uuid,)).fetchone()
        if row:
            self.db.execute("UPDATE codes SET expires=?, name=? WHERE code=?", (now + CODE_TTL, name, row["code"]))
            self.db.commit()
            return row["code"]
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            if not self.db.execute("SELECT 1 FROM codes WHERE code=?", (code,)).fetchone():
                break
        self.db.execute("INSERT INTO codes VALUES (?,?,?,?)", (code, uuid, name, now + CODE_TTL))
        self.db.commit()
        self.bump("link_code")
        return code

    def consume_code(self, code: str, discord_id: str):
        """Возвращает (uuid, name) при успехе и привязывает аккаунт, иначе None."""
        row = self.db.execute("SELECT * FROM codes WHERE code=?", (code.upper().strip(),)).fetchone()
        if not row or row["expires"] <= time.time():
            return None
        self.db.execute("DELETE FROM codes WHERE code=?", (row["code"],))
        self.db.execute(
            "INSERT OR REPLACE INTO links (uuid, discord_id, name, created) VALUES (?,?,?,?)",
            (row["uuid"], discord_id, row["name"], time.time()),
        )
        self.db.commit()
        self.bump("link_done")
        return row["uuid"], row["name"]

    # ---------- подтверждение входа ----------
    def create_verification(self, uuid: str, name: str, ip: str, discord_id: str, ttl: int) -> str:
        vid = secrets.token_urlsafe(12)
        self.db.execute(
            "INSERT INTO verifications VALUES (?,?,?,?,?,?,?,NULL)",
            (vid, uuid, name, ip, discord_id, PENDING, time.time() + ttl),
        )
        self.db.commit()
        self.bump("verify_created")
        return vid

    def get_verification(self, vid: str) -> Optional[Verification]:
        row = self.db.execute("SELECT * FROM verifications WHERE id=?", (vid,)).fetchone()
        if not row:
            return None
        v = Verification(**dict(row))
        if v.status == PENDING and v.expires <= time.time():
            self.set_status(vid, EXPIRED)
            v.status = EXPIRED
        return v

    def set_status(self, vid: str, status: str) -> bool:
        """Меняет статус только у ещё ожидающего запроса (защита от двойного нажатия)."""
        cur = self.db.execute(
            "UPDATE verifications SET status=? WHERE id=? AND status=?", (status, vid, PENDING)
        )
        self.db.commit()
        if cur.rowcount > 0:
            self.bump("verify_" + status)
        return cur.rowcount > 0

    def set_message(self, vid: str, message_id: str) -> None:
        self.db.execute("UPDATE verifications SET message_id=? WHERE id=?", (message_id, vid))
        self.db.commit()

    def expire_due(self) -> list:
        """Помечает просроченные запросы и возвращает их, чтобы бот обновил сообщения."""
        rows = self.db.execute(
            "SELECT * FROM verifications WHERE status=? AND expires<=?", (PENDING, time.time())
        ).fetchall()
        result = []
        for row in rows:
            if self.set_status(row["id"], EXPIRED):
                result.append(Verification(**{**dict(row), "status": EXPIRED}))
        self.db.execute("DELETE FROM verifications WHERE status!=? AND expires<?", (PENDING, time.time() - 3600))
        self.db.commit()
        return result
