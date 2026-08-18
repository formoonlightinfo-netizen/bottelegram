"""
Server web del curfew bot: espone un pannello di configurazione protetto da
username/password (accessibile da telefono via l'URL pubblico di Railway) e
fa girare, nello stesso processo, lo scheduler che apre/chiude i gruppi.

Salvare dal pannello scrive direttamente il file di configurazione sul
server: lo scheduler lo rileva entro pochi secondi e si aggiorna da solo,
senza bisogno di redeploy.

Variabili d'ambiente richieste:
    TELEGRAM_BOT_TOKEN  token del bot
    PANEL_PASSWORD      password per accedere al pannello
    PANEL_USERNAME      utente per accedere al pannello (default: "admin")
"""
import asyncio
import json
import logging
import os
import secrets
import shutil
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from telegram import Bot

from curfew_bot import (
    CONFIG_PATH,
    close_group,
    create_scheduler,
    find_group,
    load_config,
    open_group,
    schedule_groups,
    watch_config,
)

log = logging.getLogger("curfew_app")

app = FastAPI()
security = HTTPBasic()
state: dict = {}


def ensure_config_bootstrapped() -> None:
    """Se il file di config non esiste ancora (es. volume vuoto al primo avvio),
    lo inizializza da quello incluso nel repository."""
    if CONFIG_PATH.exists():
        return
    bundled = Path(__file__).parent / "config" / "curfew-config.json"
    if not bundled.exists():
        bundled = Path(__file__).parent / "config" / "curfew-config.example.json"
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if bundled.exists() and bundled.resolve() != CONFIG_PATH.resolve():
        shutil.copy(bundled, CONFIG_PATH)
        log.info("Configurazione inizializzata da %s", bundled)
    else:
        CONFIG_PATH.write_text(
            json.dumps({"timezone": "Europe/Rome", "groups": []}, indent=2),
            encoding="utf-8",
        )


def check_auth(credentials: HTTPBasicCredentials = Depends(security)) -> bool:
    username = os.environ.get("PANEL_USERNAME", "admin")
    password = os.environ.get("PANEL_PASSWORD")
    if not password:
        raise HTTPException(500, "PANEL_PASSWORD non configurata sul server")
    correct_user = secrets.compare_digest(credentials.username, username)
    correct_pass = secrets.compare_digest(credentials.password, password)
    if not (correct_user and correct_pass):
        raise HTTPException(401, "Credenziali non valide", headers={"WWW-Authenticate": "Basic"})
    return True


@app.on_event("startup")
async def startup() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Variabile d'ambiente TELEGRAM_BOT_TOKEN mancante")

    ensure_config_bootstrapped()

    bot = Bot(token=token)
    me = await bot.get_me()
    log.info("Bot avviato come @%s", me.username)

    config = load_config()
    scheduler = create_scheduler(config)
    schedule_groups(scheduler, config, bot)
    scheduler.start()
    log.info("Scheduler avviato")

    state["bot"] = bot
    state["scheduler"] = scheduler
    state["watch_task"] = asyncio.create_task(watch_config(scheduler, bot))


@app.on_event("shutdown")
async def shutdown() -> None:
    task = state.get("watch_task")
    if task:
        task.cancel()
    scheduler = state.get("scheduler")
    if scheduler:
        scheduler.shutdown(wait=False)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    html_path = Path(__file__).parent / "web" / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/api/config")
async def get_config(auth: bool = Depends(check_auth)) -> JSONResponse:
    return JSONResponse(load_config())


@app.post("/api/config")
async def save_config(request: Request, auth: bool = Depends(check_auth)) -> JSONResponse:
    payload = await request.json()
    if "groups" not in payload or not isinstance(payload["groups"], list):
        raise HTTPException(400, "Configurazione non valida: manca 'groups'")
    for group in payload["groups"]:
        if not group.get("chat_id"):
            raise HTTPException(400, f"Il gruppo '{group.get('name', '')}' non ha un Chat ID valido")
    payload.setdefault("timezone", "Europe/Rome")

    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(CONFIG_PATH)
    log.info("Configurazione salvata dal pannello web")
    return JSONResponse({"ok": True})


@app.post("/api/action")
async def manual_action(request: Request, auth: bool = Depends(check_auth)) -> JSONResponse:
    payload = await request.json()
    chat_id = payload.get("chat_id")
    action = payload.get("action")
    if action not in ("open", "close"):
        raise HTTPException(400, "action deve essere 'open' o 'close'")
    config = load_config()
    group = find_group(config, int(chat_id))
    if group is None:
        raise HTTPException(404, "Gruppo non trovato nella configurazione")

    bot = state["bot"]
    if action == "open":
        await open_group(bot, group)
    else:
        await close_group(bot, group)
    return JSONResponse({"ok": True})


@app.get("/api/chat-ids")
async def chat_ids(auth: bool = Depends(check_auth)) -> JSONResponse:
    bot = state["bot"]
    updates = await bot.get_updates()
    seen: dict[int, dict] = {}
    for u in updates:
        chat = None
        for attr in ("message", "channel_post", "my_chat_member", "edited_message"):
            obj = getattr(u, attr, None)
            if obj is not None:
                chat = obj.chat
                break
        if chat is not None and chat.id not in seen:
            seen[chat.id] = {
                "chat_id": chat.id,
                "title": chat.title or chat.username or "n/d",
                "type": chat.type,
            }
    return JSONResponse(list(seen.values()))
