"""Тексты сообщений бота. Любой ключ можно переопределить в файле messages.json рядом с main.py."""
import json
from pathlib import Path

DEFAULTS = {
    "verify_header": "🔐 **Запрос на вход — Minecraft**",
    "verify_body": (
        "Кто-то входит под ником **{player}**\n"
        "📍 IP: `{ip}`\n\n"
        "Это вы? Нажмите **Разрешить** — иначе **Отклонить** (IP будет заблокирован)."
    ),
    "verify_accept": "✅ Вход разрешён. Добро пожаловать, **{player}**!",
    "verify_deny": "❌ Вход отклонён. IP `{ip}` заблокирован.",
    "verify_timeout": "⏰ Время истекло. Вход отклонён автоматически.",
    "button_accept": "✅ Разрешить",
    "button_deny": "❌ Отклонить",
    "link_already_linked": "❌ Этот Discord уже привязан к игроку **{player}**.\nЧтобы сменить привязку — введите `/discord unlink` в Minecraft.",
    "link_invalid_code": "❌ Код **{code}** не найден или истёк (коды действуют 10 минут).\nЗапросите новый код командой `/discord link` в игре.",
    "link_success": "✅ **Привязка выполнена!**\nАккаунт Minecraft **{player}** теперь защищён.\n\nПри входе с нового IP я буду присылать запрос на подтверждение.",
    "link_usage": "Отправьте `!link КОД` — код выдаёт команда `/discord link` в игре.",
    "not_yours": "❌ Это не ваш запрос на вход.",
    "already_handled": "⚠️ Этот запрос уже истёк или обработан.",
}


class Messages:
    def __init__(self, path: str = "messages.json"):
        self._data = dict(DEFAULTS)
        p = Path(path)
        if p.is_file():
            custom = json.loads(p.read_text(encoding="utf-8"))
            self._data.update({k: v for k, v in custom.items() if k in DEFAULTS})

    def get(self, key: str, **fmt) -> str:
        text = self._data[key]
        for name, value in fmt.items():
            text = text.replace("{" + name + "}", str(value))
        return text
