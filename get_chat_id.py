"""
Recupera il chat_id reale di un gruppo Telegram.

Il link di invito (t.me/+...) NON contiene il chat_id: bisogna leggerlo dagli
aggiornamenti ricevuti dal bot. Procedura:
  1. Assicurati che il bot sia già stato aggiunto al gruppo.
  2. Scrivi un messaggio qualsiasi nel gruppo (o rimuovi/riaggiungi il bot).
  3. Esegui questo script: python get_chat_id.py

Richiede la variabile d'ambiente TELEGRAM_BOT_TOKEN.
"""
import os
import sys

import requests


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Imposta la variabile d'ambiente TELEGRAM_BOT_TOKEN prima di eseguire questo script.")
        sys.exit(1)

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("ok"):
        print("Errore API Telegram:", data)
        sys.exit(1)

    updates = data.get("result", [])
    if not updates:
        print("Nessun aggiornamento trovato.")
        print("Scrivi un messaggio nel gruppo (il bot deve essere già membro) e riesegui questo script.")
        return

    seen = set()
    print("Chat trovate negli ultimi aggiornamenti:\n")
    for update in updates:
        chat = None
        for key in ("message", "channel_post", "my_chat_member", "edited_message"):
            payload = update.get(key)
            if payload:
                chat = payload.get("chat")
                break
        if not chat:
            continue
        chat_id = chat.get("id")
        if chat_id in seen:
            continue
        seen.add(chat_id)
        print(f"  chat_id: {chat_id}")
        print(f"  titolo:  {chat.get('title', chat.get('username', 'n/d'))}")
        print(f"  tipo:    {chat.get('type')}")
        print("-" * 40)

    if not seen:
        print("Nessuna chat di gruppo trovata negli aggiornamenti recenti.")


if __name__ == "__main__":
    main()
