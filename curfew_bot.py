"""
Bot di coprifuoco per gruppi Telegram.

Legge una configurazione (file JSON o variabile d'ambiente CURFEW_CONFIG_JSON)
che elenca gruppi, orari di apertura/chiusura e messaggi di annuncio, e apre/
chiude i permessi di scrittura inviando i messaggi agli orari programmati.

Pensato per girare come "tick" periodico (es. ogni 15 minuti via GitHub
Actions, completamente gratuito): ogni esecuzione confronta l'orario
corrente con l'ultimo controllo salvato in config/state.json ed esegue le
azioni che sarebbero dovute scattare nel frattempo.

Uso:
    python curfew_bot.py --tick            # esegue le azioni dovute dall'ultimo tick ed esce
    python curfew_bot.py --open CHAT_ID    # apre subito un gruppo ed esce
    python curfew_bot.py --close CHAT_ID   # chiude subito un gruppo ed esce
    python curfew_bot.py --list            # elenca i gruppi configurati
"""
import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import Bot, ChatPermissions
from telegram.error import TelegramError
from telegram.request import HTTPXRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("curfew_bot")

CONFIG_PATH = Path(os.environ.get("CURFEW_CONFIG_PATH", "config/curfew-config.json"))
STATE_PATH = Path(os.environ.get("CURFEW_STATE_PATH", "config/state.json"))
DEFAULT_TIMEZONE = "Europe/Rome"
DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Quando il gruppo è chiuso, tutti i permessi di scrittura sono revocati.
CLOSED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=True,
    can_pin_messages=False,
)

DEFAULT_OPEN_PERMISSIONS = {
    "can_send_messages": True,
    "can_send_audios": True,
    "can_send_documents": True,
    "can_send_photos": True,
    "can_send_videos": True,
    "can_send_video_notes": True,
    "can_send_voice_notes": True,
    "can_send_polls": True,
    "can_send_other_messages": True,
    "can_add_web_page_previews": True,
}


def load_config() -> dict:
    inline = os.environ.get("CURFEW_CONFIG_JSON")
    if inline:
        return json.loads(inline)
    if not CONFIG_PATH.exists():
        log.error(
            "File di configurazione non trovato: %s "
            "(copia config/curfew-config.example.json e personalizzalo, "
            "oppure imposta CURFEW_CONFIG_JSON)",
            CONFIG_PATH,
        )
        raise SystemExit(1)
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_config(config: dict) -> None:
    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(CONFIG_PATH)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def write_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def find_group(config: dict, chat_id: int) -> Optional[dict]:
    for group in config.get("groups", []):
        if int(group["chat_id"]) == chat_id:
            return group
    return None


def open_permissions_for(group: dict) -> ChatPermissions:
    perms = {**DEFAULT_OPEN_PERMISSIONS, **group.get("open_permissions", {})}
    return ChatPermissions(
        **perms,
        can_invite_users=True,
        can_pin_messages=False,
        can_change_info=False,
    )


async def _retry_telegram_call(coro_factory, *, attempts: int = 3, base_delay: float = 3.0):
    """Riprova una chiamata Telegram su errori di rete transitori (es. timeout).

    coro_factory è una funzione senza argomenti che restituisce la coroutine
    da eseguire, così ogni tentativo crea una nuova richiesta HTTP pulita.
    """
    for attempt in range(1, attempts + 1):
        try:
            return await coro_factory()
        except TelegramError as e:
            if attempt == attempts:
                raise
            log.warning("Chiamata Telegram fallita (tentativo %d/%d): %s. Riprovo...", attempt, attempts, e)
            await asyncio.sleep(base_delay * attempt)


async def open_group(bot: Bot, group: dict) -> None:
    chat_id = group["chat_id"]
    name = group.get("name", str(chat_id))
    try:
        await _retry_telegram_call(
            lambda: bot.set_chat_permissions(chat_id=chat_id, permissions=open_permissions_for(group))
        )
        log.info("Gruppo '%s' aperto", name)
        message = group.get("open_message")
        if message:
            await _retry_telegram_call(lambda: bot.send_message(chat_id=chat_id, text=message))
    except TelegramError as e:
        log.error("Errore durante l'apertura del gruppo '%s' (%s): %s", name, chat_id, e)


async def close_group(bot: Bot, group: dict) -> None:
    chat_id = group["chat_id"]
    name = group.get("name", str(chat_id))
    try:
        await _retry_telegram_call(
            lambda: bot.set_chat_permissions(chat_id=chat_id, permissions=CLOSED_PERMISSIONS)
        )
        log.info("Gruppo '%s' chiuso", name)
        message = group.get("close_message")
        if message:
            await _retry_telegram_call(lambda: bot.send_message(chat_id=chat_id, text=message))
    except TelegramError as e:
        log.error("Errore durante la chiusura del gruppo '%s' (%s): %s", name, chat_id, e)


def parse_time(value: str) -> tuple[int, int]:
    hh, mm = value.split(":")
    return int(hh), int(mm)


def _parse_pause_datetime(value: Optional[str], group: dict, default_tz: str) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(group.get("timezone", default_tz)))
    return dt


def parse_pause_window(group: dict, default_tz: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """(pause_from, pause_until): finestra di sospensione del gruppo.

    pause_from assente/None = la chiusura è (o era) immediata, non programmata.
    pause_until assente/None = nessuna sospensione attiva o programmata.
    """
    pause_from = _parse_pause_datetime(group.get("pause_from"), group, default_tz)
    pause_until = _parse_pause_datetime(group.get("pause_until"), group, default_tz)
    return pause_from, pause_until


def _due_action_times(action: dict, tz: ZoneInfo, window_start: datetime, window_end: datetime) -> list[datetime]:
    """Istanti in cui questa azione ricorrente cade dentro (window_start, window_end]."""
    hour, minute = parse_time(action["time"])
    due = []
    day = window_end.astimezone(tz).date()
    # Il tick gira ogni ~15 minuti: due giorni di margine bastano a coprire
    # qualunque ritardo ragionevole del cron senza rischiare doppie esecuzioni
    # (l'intervallo (window_start, window_end] resta comunque il filtro reale).
    for offset in range(0, 2):
        candidate_date = day - timedelta(days=offset)
        if DAY_CODES[candidate_date.weekday()] not in action["days"]:
            continue
        candidate = datetime(
            candidate_date.year, candidate_date.month, candidate_date.day, hour, minute, tzinfo=tz
        )
        if window_start < candidate <= window_end:
            due.append(candidate)
    return due


async def run_tick(bot: Bot, config: dict) -> None:
    """Esegue tutte le azioni che sarebbero dovute scattare dall'ultimo tick."""
    state = load_state()
    now = datetime.now(timezone.utc)
    default_tz = config.get("timezone", DEFAULT_TIMEZONE)
    config_changed = False

    for group in config.get("groups", []):
        if not group.get("enabled", True):
            continue
        chat_id = group["chat_id"]
        name = group.get("name", str(chat_id))
        tz = ZoneInfo(group.get("timezone", default_tz))

        last_check_raw = state.get(str(chat_id))
        # Primo tick per questo gruppo: stabilisce solo il punto di partenza,
        # senza eseguire retroattivamente azioni passate.
        window_start = datetime.fromisoformat(last_check_raw) if last_check_raw else now

        pause_from, pause_until = parse_pause_window(group, default_tz)

        if pause_from and window_start < pause_from <= now:
            log.info("Gruppo '%s': scatta la chiusura programmata", name)
            await close_group(bot, group)

        if pause_until and window_start < pause_until <= now:
            log.info("Gruppo '%s': sospensione terminata, riapro", name)
            group["pause_from"] = None
            group["pause_until"] = None
            await open_group(bot, group)
            config_changed = True
            pause_from, pause_until = None, None

        currently_paused = bool(pause_until) and pause_until > now and (pause_from is None or pause_from <= now)

        if not currently_paused:
            for action in group.get("actions", []):
                for _ in _due_action_times(action, tz, window_start, now):
                    if action["action"] == "open":
                        await open_group(bot, group)
                    else:
                        await close_group(bot, group)

        state[str(chat_id)] = now.isoformat()

    write_state(state)
    if config_changed:
        write_config(config)


async def run_manual_action(bot: Bot, config: dict, chat_id: int, action: str) -> None:
    group = find_group(config, chat_id)
    if group is None:
        log.error("Nessun gruppo con chat_id=%s nella configurazione", chat_id)
        raise SystemExit(1)
    if action == "open":
        await open_group(bot, group)
    else:
        await close_group(bot, group)


def list_groups(config: dict) -> None:
    groups = config.get("groups", [])
    if not groups:
        print("Nessun gruppo configurato.")
        return
    for group in groups:
        status = "attivo" if group.get("enabled", True) else "disattivato"
        print(f"- {group.get('name', 'senza nome')} (chat_id: {group['chat_id']}, {status})")
        for action in group.get("actions", []):
            print(f"    {action['action']} alle {action['time']} — giorni: {', '.join(action['days'])}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", metavar="CHAT_ID", type=int, help="Apre subito il gruppo indicato ed esce")
    parser.add_argument("--close", metavar="CHAT_ID", type=int, help="Chiude subito il gruppo indicato ed esce")
    parser.add_argument("--list", action="store_true", help="Elenca i gruppi configurati ed esce")
    parser.add_argument("--tick", action="store_true", help="Esegue le azioni dovute dall'ultimo tick ed esce")
    args = parser.parse_args()

    if args.list:
        list_groups(load_config())
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        log.error("Variabile d'ambiente TELEGRAM_BOT_TOKEN mancante")
        raise SystemExit(1)

    config = load_config()
    request = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0, write_timeout=20.0, pool_timeout=20.0)
    bot = Bot(token=token, request=request)
    try:
        me = await bot.get_me()
        log.info("Bot avviato come @%s", me.username)
    except TelegramError as exc:
        # Non essenziale: se Telegram risponde lento solo su questa verifica
        # non ha senso far fallire l'intero tick, si procede comunque.
        log.warning("Verifica identità bot fallita (%s), procedo comunque", exc)

    if args.open is not None:
        await run_manual_action(bot, config, args.open, "open")
        return
    if args.close is not None:
        await run_manual_action(bot, config, args.close, "close")
        return

    await run_tick(bot, config)


if __name__ == "__main__":
    asyncio.run(main())
