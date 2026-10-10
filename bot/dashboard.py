"""HTML-панель статистики (одна страница без внешних библиотек)."""
import time
from html import escape

CSS = """
:root{--bg:#0f1115;--card:#181b22;--line:#262a34;--text:#e6e8ee;--dim:#8b92a3;--a:#5b8def;--g:#3ecf8e;--r:#ef5b5b;--y:#f0b429}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 60px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 12px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
.sub{color:var(--dim);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .n{font-size:28px;font-weight:700}.card .l{color:var(--dim);font-size:13px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;overflow-x:auto}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--dim);font-weight:500}.mono{font-family:ui-monospace,Consolas,monospace}
.row{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:14px}.row .k{width:90px;color:var(--dim)}
.row .bar{flex:1;background:var(--line);border-radius:6px;height:10px;overflow:hidden}.row .bar i{display:block;height:100%;background:var(--a)}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;background:var(--line)}
.ok{color:var(--g)}.bad{color:var(--r)}
.top{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap}
.reset{background:transparent;border:1px solid var(--r);color:var(--r);border-radius:8px;padding:6px 12px;
  font-size:13px;cursor:pointer}
.reset:hover{background:var(--r);color:#fff}
"""


def _num(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def _ago(ts: float) -> str:
    d = max(0, int(time.time() - ts))
    if d < 90:
        return "только что"
    if d < 3600:
        return f"{d // 60} мин назад"
    if d < 86400:
        return f"{d // 3600} ч назад"
    return f"{d // 86400} дн назад"


def _card(value, label) -> str:
    return f'<div class="card"><div class="n">{_num(value)}</div><div class="l">{escape(label)}</div></div>'


def _bars(days, values, color) -> str:
    """Столбчатый график на SVG; подпись при наведении — «дата: значение»."""
    w, h, pad = 560, 130, 18
    peak = max(values) if values and max(values) > 0 else 1
    step = w / max(len(values), 1)
    parts = []
    for i, (d, v) in enumerate(zip(days, values)):
        bh = (h - pad - 14) * v / peak
        x = i * step + 4
        y = h - pad - bh
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{step - 8:.1f}" height="{max(bh, 1):.1f}" rx="3" fill="{color}">'
            f"<title>{escape(d)}: {v}</title></rect>"
        )
        if v:
            parts.append(f'<text x="{x + (step - 8) / 2:.1f}" y="{y - 3:.1f}" fill="#8b92a3" font-size="10" text-anchor="middle">{v}</text>')
        if i % 2 == 0:
            parts.append(f'<text x="{x + (step - 8) / 2:.1f}" y="{h - 4}" fill="#8b92a3" font-size="9" text-anchor="middle">{escape(d[5:])}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">{"".join(parts)}</svg>'


def _dist(title, data: dict) -> str:
    total = sum(data.values()) or 1
    rows = "".join(
        f'<div class="row"><span class="k mono">{escape(str(k))}</span>'
        f'<span class="bar"><i style="width:{v / total * 100:.0f}%"></i></span><span>{v}</span></div>'
        for k, v in sorted(data.items(), key=lambda kv: (-kv[1], kv[0]))
    ) or '<span class="sub">пока нет данных</span>'
    return f'<div class="panel"><b>{escape(title)}</b>{rows}</div>'


def render(stats: dict, latest_version: str = "") -> str:
    d, v, s, daily = stats["discord"], stats["verifications"], stats["servers"], stats["daily"]
    days, series = daily["days"], daily["series"]

    def ser(kind):
        return series.get(kind, [0] * len(days))

    cards_discord = "".join([
        _card(d["dm_users"], "Людей написало боту"),
        _card(d["dm_users_7d"], "…из них за 7 дней"),
        _card(d["dm_messages"], "Сообщений боту"),
        _card(d["linked_accounts"], "Связано аккаунтов"),
        _card(d["link_codes"], "Кодов привязки выдано"),
        _card(d["unlinks"], "Отвязок"),
    ])
    decided = v["accepted"] + v["denied"]
    rate = f"{v['accepted'] / decided * 100:.0f}%" if decided else "—"
    cards_verify = "".join([
        _card(v["created"], "Запросов входа"),
        _card(v["accepted"], "Разрешено"),
        _card(v["denied"], "Отклонено"),
        _card(v["expired"], "Истекло"),
        _card(v["failed"], "Не доставлено в ЛС"),
    ]) + f'<div class="card"><div class="n">{rate}</div><div class="l">Доля разрешённых</div></div>'
    cards_servers = "".join([
        _card(s["total"], "Серверов всего"),
        _card(s["active_24h"], "Активны за 24 ч"),
        _card(s["active_7d"], "Активны за 7 дней"),
        _card(s["online_now"], "На связи сейчас"),
        _card(s["players_now"], "Игроков на них онлайн"),
    ])

    rows = "".join(
        "<tr>"
        f'<td class="mono">{escape(r["server_id"][:8])}…</td>'
        f'<td>{escape(r["plugin_version"] or "?")}</td>'
        f'<td>{escape(r["mc_version"] or "?")}</td>'
        f'<td>{escape(r["software"] or "?")}</td>'
        f'<td>{int(r["online"])}</td>'
        f'<td>{_ago(r["last_seen"])}</td>'
        f'<td>{_ago(r["first_seen"])}</td>'
        "</tr>"
        for r in s["list"][:100]
    ) or '<tr><td colspan="7" class="sub">Пока ни один сервер не отправил данные</td></tr>'

    outdated = ""
    if latest_version:
        old = sum(c for ver, c in s["plugin_versions"].items() if ver != latest_version)
        outdated = f'<span class="pill">Последняя версия: {escape(latest_version)} · на старых: {old}</span>'

    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevLogin — статистика</title><style>{CSS}</style>
<script>
function resetStats(){{
  if(!confirm('Обнулить всю статистику? Привязки Discord-аккаунтов сохранятся. Отменить это нельзя.')) return;
  fetch('/api/stats/reset',{{method:'POST'}}).then(()=>location.reload());
}}
setTimeout(()=>location.reload(), 60000);
</script></head><body><main>
<div class="top"><div>
<h1>DevLogin — статистика</h1>
<div class="sub">Обновлено: {escape(stats["generated"])} UTC · страница обновляется сама раз в минуту {outdated}</div>
</div><button class="reset" onclick="resetStats()">Сбросить статистику</button></div>

<h2>Discord-бот</h2><div class="grid">{cards_discord}</div>
<h2>Подтверждения входа</h2><div class="grid">{cards_verify}</div>
<h2>Серверы с плагином</h2><div class="grid">{cards_servers}</div>

<h2>Последние {len(days)} дней</h2>
<div class="cols">
 <div class="panel"><b>Новые привязки</b>{_bars(days, ser("link_done"), "#3ecf8e")}</div>
 <div class="panel"><b>Запросы подтверждения входа</b>{_bars(days, ser("verify_created"), "#5b8def")}</div>
 <div class="panel"><b>Новые люди написали боту</b>{_bars(days, ser("dm_new_user"), "#f0b429")}</div>
</div>

<h2>Версии (серверы, активные за 7 дней)</h2>
<div class="cols">{_dist("Версии плагина", s["plugin_versions"])}{_dist("Версии Minecraft", s["mc_versions"])}</div>

<h2>Серверы</h2>
<div class="panel"><table><tr><th>ID</th><th>Плагин</th><th>Minecraft</th><th>Ядро</th><th>Онлайн</th><th>Был на связи</th><th>Впервые</th></tr>{rows}</table></div>
<p class="sub">ID сервера — случайный идентификатор, который плагин создаёт сам; ников и IP здесь нет.</p>
</main></body></html>"""
