# Curfew Bot — coprifuoco automatico per gruppi Telegram

Apre e chiude automaticamente (o manualmente) i permessi di scrittura in uno o
più gruppi Telegram privati, inviando un messaggio di annuncio quando il
gruppo si apre e quando si chiude.

## Componenti

- **`curfew_bot.py`** — lo scheduler che gira in continuo su un server: legge
  la configurazione e, agli orari programmati, chiude/apre i permessi del
  gruppo e invia i messaggi di annuncio. Supporta anche l'apertura/chiusura
  manuale via riga di comando.
- **`web/index.html`** — pannello di configurazione statico (nessuna build
  richiesta): gestisci gruppi, orari e messaggi, esporta `curfew-config.json`
  e usa i pulsanti "Apri ora / Chiudi ora" per agire subito su un gruppo.
- **`get_chat_id.py`** — script per recuperare il chat_id reale di un gruppo.

## 1. Creare il bot

1. Parla con [@BotFather](https://t.me/BotFather) su Telegram, crea un bot e
   copia il token (`123456789:AA...`).
2. Aggiungi il bot al gruppo e promuovilo amministratore con il permesso
   **"Blocca utenti" / "Ban users"** (`can_restrict_members`): è l'unico
   permesso necessario per cambiare i permessi di scrittura del gruppo
   (`setChatPermissions`), non serve per bannare singoli utenti.

## 2. Trovare il Chat ID del gruppo

Il link di invito (`t.me/+...`) **non** è il chat_id. Per recuperarlo:

1. Scrivi un messaggio qualsiasi nel gruppo (il bot deve essere già membro).
2. Esegui:
   ```bash
   export TELEGRAM_BOT_TOKEN="il-tuo-token"
   python get_chat_id.py
   ```
   oppure apri `web/index.html` in un browser, inserisci il token e premi
   "Recupera Chat ID dagli ultimi messaggi".
3. Il chat_id dei gruppi è un numero negativo lungo, tipo `-1001234567890`.

## 3. Configurare gruppi, orari e messaggi

Copia l'esempio e personalizzalo:

```bash
cp config/curfew-config.example.json config/curfew-config.json
```

Oppure apri `web/index.html`, compila i gruppi con i loro orari e messaggi, e
premi "Esporta curfew-config.json" — salva il file scaricato in
`config/curfew-config.json`.

Schema del file:

```jsonc
{
  "timezone": "Europe/Rome",
  "groups": [
    {
      "name": "Gruppo Famiglia",
      "chat_id": -1001234567890,
      "enabled": true,
      "schedules": [
        { "days": ["mon","tue","wed","thu","fri"], "open_time": "07:00", "close_time": "22:00" },
        { "days": ["sat","sun"], "open_time": "08:00", "close_time": "23:30" }
      ],
      "open_message": "🔓 Buongiorno! Il gruppo è aperto.",
      "close_message": "🔒 Buonanotte! Il gruppo è chiuso fino a domattina."
    }
  ]
}
```

Un gruppo può avere più fasce orarie (es. orari diversi nel weekend). I
giorni usano i codici a 3 lettere: `mon tue wed thu fri sat sun`.

## 4. Eseguire in locale

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="il-tuo-token"
python curfew_bot.py
```

Comandi utili:

```bash
python curfew_bot.py --list              # elenca i gruppi configurati
python curfew_bot.py --open -1001234567890   # apre subito un gruppo
python curfew_bot.py --close -1001234567890  # chiude subito un gruppo
```

Lo scheduler ricontrolla il file di configurazione ogni 30 secondi: se lo
modifichi mentre il bot è in esecuzione, la pianificazione si aggiorna senza
bisogno di riavviarlo.

## 5. Deploy su Railway (esecuzione continua)

1. Crea un repository GitHub con questi file e collegalo a un nuovo progetto
   Railway ("Deploy from GitHub repo").
2. In Railway, imposta le variabili d'ambiente:
   - `TELEGRAM_BOT_TOKEN` = il token del bot (in Secrets, non nel codice).
   - In alternativa a un volume persistente per `config/curfew-config.json`,
     puoi impostare `CURFEW_CONFIG_JSON` con l'intero contenuto del file JSON
     come variabile d'ambiente: più semplice da gestire su Railway, ma per
     applicare modifiche serve un redeploy (non c'è hot-reload da file).
3. Comando di avvio: `python curfew_bot.py`.
4. Railway installa automaticamente le dipendenze da `requirements.txt`.

Il processo resta in esecuzione e attiva apertura/chiusura agli orari
configurati, indipendentemente dal fatto che tu abbia il browser aperto.

## Note su "Apri ora / Chiudi ora" dal pannello web

I pulsanti in `web/index.html` chiamano `api.telegram.org` direttamente dal
browser: funzionano quando la pagina è servita come sito normale (in locale
con un file `.html`, o pubblicata es. su GitHub Pages). Se li usi dentro un
ambiente sandbox che blocca le richieste di rete verso host esterni (come un
artifact generato in una chat), le richieste falliscono con un errore di
fetch generico — non è un problema del token o del chat_id. In quel caso usa
`python curfew_bot.py --open/--close CHAT_ID` dal server, che è anche il modo
più affidabile per azioni manuali.
