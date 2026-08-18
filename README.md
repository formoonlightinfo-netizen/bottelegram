# Curfew Bot — coprifuoco automatico per gruppi Telegram

Apre e chiude automaticamente (o manualmente) i permessi di scrittura in uno o
più gruppi Telegram privati, inviando un messaggio di annuncio quando il
gruppo si apre e quando si chiude. Include un pannello web protetto da
password, raggiungibile da telefono, per modificare gruppi/orari/messaggi e
per aprire/chiudere un gruppo al volo.

## Componenti

- **`app.py`** — il servizio che gira in continuo su Railway: espone il
  pannello web (protetto da username/password) e, nello stesso processo, fa
  girare lo scheduler che apre/chiude i gruppi agli orari programmati.
  Salvare dal pannello scrive subito il file di configurazione sul server:
  lo scheduler lo rileva entro pochi secondi, senza bisogno di redeploy.
- **`curfew_bot.py`** — la stessa logica di scheduling, utilizzabile anche
  da riga di comando (utile per test in locale o azioni manuali via
  terminale). `app.py` importa le funzioni da qui.
- **`web/index.html`** — il pannello, servito da `app.py`: gestisci gruppi,
  orari e messaggi, premi "Salva modifiche", e usa "Apri ora / Chiudi ora"
  per agire subito su un gruppo.
- **`get_chat_id.py`** — script per recuperare il chat_id di un gruppo da
  terminale (in alternativa al pulsante "Recupera Chat ID" nel pannello).

## 1. Creare il bot

1. Parla con [@BotFather](https://t.me/BotFather) su Telegram, crea un bot e
   copia il token (`123456789:AA...`).
2. Aggiungi il bot al gruppo e promuovilo amministratore con il permesso
   **"Blocca utenti" / "Ban users"** (`can_restrict_members`): è l'unico
   permesso necessario per cambiare i permessi di scrittura del gruppo
   (`setChatPermissions`), non serve per bannare singoli utenti.

## 2. Deploy su Railway

1. Crea un repository GitHub con questi file e collegalo a un nuovo progetto
   Railway ("Deploy from GitHub repo").
2. In Railway, scheda **Variables**, imposta:
   - `TELEGRAM_BOT_TOKEN` = il token del bot.
   - `PANEL_USERNAME` = l'utente per accedere al pannello (es. `admin`).
   - `PANEL_PASSWORD` = una password per accedere al pannello.
3. (Consigliato) Aggiungi un **Volume** al servizio (scheda "Settings" →
   "Volumes"), mount path `/data`, e imposta la variabile
   `CURFEW_CONFIG_PATH=/data/curfew-config.json`. Senza volume, le modifiche
   salvate dal pannello vengono perse al prossimo redeploy del codice; con il
   volume restano permanenti indipendentemente dai futuri aggiornamenti del
   codice. Al primo avvio il file viene creato automaticamente copiando
   `config/curfew-config.json` incluso nel repository.
4. Railway rileva `Procfile` e `requirements.txt` e avvia da solo con
   `uvicorn app:app --host 0.0.0.0 --port $PORT`.
5. Scheda **Settings** → **Networking** → **Generate Domain**, per ottenere
   un link pubblico tipo `https://tuoprogetto.up.railway.app`. Aprilo, inserisci
   utente e password quando richiesti dal browser: quello è il pannello,
   accessibile anche da telefono.

## 3. Usare il pannello

- Apri il link pubblico del progetto Railway (salvalo tra i preferiti del
  telefono per accedervi rapidamente).
- **"+ Aggiungi gruppo"** per aggiungerne uno nuovo, senza toccare quelli
  esistenti.
- **"Recupera Chat ID dagli ultimi messaggi"** per trovare il chat_id di un
  gruppo appena aggiunto (il bot deve essere già membro e deve esserci
  almeno un messaggio recente nel gruppo — il link d'invito `t.me/+...`
  **non** è il chat_id).
- Ogni gruppo ha una lista di **azioni** indipendenti (apri/chiudi), ognuna
  con i propri giorni e il proprio orario — non devono per forza combaciare
  (es. chiude il sabato, riapre solo la domenica sera).
- **Chiusura programmata** (es. ferie, evento speciale): scegli quando chiude
  e quando riapre — anche entrambe nel futuro (es. "chiude mercoledì
  prossimo, riapre tra due settimane"). Se lasci vuoto "Chiude il", chiude
  subito. Nella finestra tra chiusura e riapertura gli orari automatici
  settimanali vengono ignorati; alla data di riapertura il gruppo si riapre
  da solo. "Annulla e riapri subito" cancella la programmazione e riapre
  immediatamente.
- **"Salva modifiche"** scrive la configurazione sul server: il bot si
  aggiorna da solo entro pochi secondi.
- **"Apri ora / Chiudi ora"** applica subito l'azione al gruppo (utile per
  ferie o cambi last-minute), indipendentemente dagli orari programmati.

## 4. Eseguire in locale (facoltativo, per test)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="il-tuo-token"
export PANEL_PASSWORD="una-password-a-scelta"
uvicorn app:app --reload
```

Il pannello sarà su `http://localhost:8000`.

In alternativa, solo lo scheduler da riga di comando, senza pannello web:

```bash
python curfew_bot.py --list              # elenca i gruppi configurati
python curfew_bot.py --open -1001234567890   # apre subito un gruppo
python curfew_bot.py --close -1001234567890  # chiude subito un gruppo
python curfew_bot.py                     # avvia solo lo scheduler
```

## Schema della configurazione

```jsonc
{
  "timezone": "Europe/Rome",
  "groups": [
    {
      "name": "Gruppo Famiglia",
      "chat_id": -1001234567890,
      "enabled": true,
      "actions": [
        { "action": "close", "days": ["sat"], "time": "12:00" },
        { "action": "open", "days": ["sun"], "time": "20:00" }
      ],
      "open_message": "🔓 Buongiorno! Il gruppo è aperto.",
      "close_message": "🔒 Buonanotte! Il gruppo è chiuso fino a domattina."
    }
  ]
}
```

I giorni usano i codici a 3 lettere: `mon tue wed thu fri sat sun`. Il file
`config/curfew-config.json` incluso nel repository è usato come punto di
partenza al primo avvio (o se non usi un volume); da lì in poi il pannello è
il modo pensato per modificarlo.
