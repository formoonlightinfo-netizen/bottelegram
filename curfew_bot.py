"""
Bot di coprifuoco per gruppi Telegram.

Legge una configurazione (file JSON o variabile d'ambiente CURFEW_CONFIG_JSON)
che elenca gruppi, orari di apertura/chiusura e messaggi di annuncio, e usa
APScheduler per applicare i permessi di scrittura e inviare i messaggi agli
orari programmati. Pensato per girare in continuo su un server (es. Railway).

Uso:
    python curfew_bot.py                  # avvia lo scheduler e resta in esecuzione
    python curfew_bot.py --open CHAT_ID    # apre subito un gruppo ed esce
    python curfew_bot.py --close CHAT_ID   # chiude subito un gruppo ed esce
    python curfew_bot.py --list            # elenca i gruppi configurati
"""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot, ChatPermissions
from telegram.error import TelegramError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("curfew_bot")

CONFIG_PATH = Path(os.environ.get("CURFEW_CONFIG_PATH", "config/curfew-config.json"))
DEFAULT_TIMEZONE = "Europe/Rome"
CONFIG_POLL_SECONDS = 30

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


async def open_group(bot: Bot, group: dict) -> None:
    chat_id = group["chat_id"]
    name = group.get("name", str(chat_id))
    try:
        await bot.set_chat_permissions(chat_id=chat_id, permissions=open_permissions_for(group))
        log.info("Gruppo '%s' aperto", name)
        message = group.get("open_message")
        if message:
            await bot.send_message(chat_id=chat_id, text=message)
    except TelegramError as e:
        log.error("Errore durante l'apertura del gruppo '%s' (%s): %s", name, chat_id, e)


async def close_group(bot: Bot, group: dict) -> None:
    chat_id = group["chat_id"]
    name = group.get("name", str(chat_id))
    try:
        await bot.set_chat_permissions(chat_id=chat_id, permissions=CLOSED_PERMISSIONS)
        log.info("Gruppo '%s' chiuso", name)
        message = group.get("close_message")
        if message:
            await bot.send_message(chat_id=chat_id, text=message)
    except TelegramError as e:
        log.error("Errore durante la chiusura del gruppo '%s' (%s): %s", name, chat_id, e)


def parse_time(value: str) -> tuple[int, int]:
    hh, mm = value.split(":")
    return int(hh), int(mm)


def create_scheduler(config: dict) -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=config.get("timezone", DEFAULT_TIMEZONE))


def schedule_groups(scheduler: AsyncIOScheduler, config: dict, bot: Bot) -> None:
    default_tz = config.get("timezone", DEFAULT_TIMEZONE)
    job_count = 0
    for group in config.get("groups", []):
        if not group.get("enabled", True):
            continue
        name = group.get("name", str(group.get("chat_id")))
        for idx, rule in enumerate(group.get("schedules", [])):
            days = ",".join(rule["days"])
            open_h, open_m = parse_time(rule["open_time"])
            close_h, close_m = parse_time(rule["close_time"])
            tz = rule.get("timezone", default_tz)

            scheduler.add_job(
                open_group,
                CronTrigger(day_of_week=days, hour=open_h, minute=open_m, timezone=tz),
                args=[bot, group],
                id=f"open-{group['chat_id']}-{idx}",
                replace_existing=True,
            )
            scheduler.add_job(
                close_group,
                CronTrigger(day_of_week=days, hour=close_h, minute=close_m, timezone=tz),
                args=[bot, group],
                id=f"close-{group['chat_id']}-{idx}",
                replace_existing=True,
            )
            job_count += 2
            log.info(
                "Gruppo '%s': apertura %s, chiusura %s (giorni: %s, tz: %s)",
                name, rule["open_time"], rule["close_time"], days, tz,
            )
    log.info("Pianificati %d job su %d gruppi", job_count, len(config.get("groups", [])))


async def watch_config(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    """Ricarica la pianificazione se il file di configurazione cambia (polling)."""
    if os.environ.get("CURFEW_CONFIG_JSON"):
        # Con configurazione inline via env var non c'è un file da monitorare:
        # per applicare modifiche serve un riavvio del processo (es. redeploy).
        while True:
            await asyncio.sleep(3600)

    try:
        last_mtime = CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        last_mtime = None

    while True:
        await asyncio.sleep(CONFIG_POLL_SECONDS)
        try:
            mtime = CONFIG_PATH.stat().st_mtime
        except FileNotFoundError:
            continue
        if mtime != last_mtime:
            last_mtime = mtime
            log.info("Configurazione modificata, ricarico la pianificazione...")
            try:
                config = load_config()
            except (json.JSONDecodeError, SystemExit) as e:
                log.error("Configurazione non valida, mantengo la pianificazione precedente: %s", e)
                continue
            scheduler.remove_all_jobs()
            schedule_groups(scheduler, config, bot)


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
        for rule in group.get("schedules", []):
            print(f"    apertura {rule['open_time']} / chiusura {rule['close_time']} — giorni: {', '.join(rule['days'])}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", metavar="CHAT_ID", type=int, help="Apre subito il gruppo indicato ed esce")
    parser.add_argument("--close", metavar="CHAT_ID", type=int, help="Chiude subito il gruppo indicato ed esce")
    parser.add_argument("--list", action="store_true", help="Elenca i gruppi configurati ed esce")
    args = parser.parse_args()

    if args.list:
        list_groups(load_config())
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        log.error("Variabile d'ambiente TELEGRAM_BOT_TOKEN mancante")
        raise SystemExit(1)

    config = load_config()
    bot = Bot(token=token)
    me = await bot.get_me()
    log.info("Bot avviato come @%s", me.username)

    if args.open is not None:
        await run_manual_action(bot, config, args.open, "open")
        return
    if args.close is not None:
        await run_manual_action(bot, config, args.close, "close")
        return

    scheduler = create_scheduler(config)
    schedule_groups(scheduler, config, bot)
    scheduler.start()
    log.info("Scheduler avviato, in attesa degli orari programmati (Ctrl+C per uscire)")

    try:
        await watch_config(scheduler, bot)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
