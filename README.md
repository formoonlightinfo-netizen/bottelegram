# Curfew Bot — coprifuoco automatico per gruppi Telegram

Apre e chiude automaticamente (o manualmente) i permessi di scrittura in uno o
più gruppi Telegram privati, inviando un messaggio di annuncio quando il
gruppo si apre e quando si chiude.

**Completamente gratuito**: gira su GitHub Actions (nessun server a
pagamento, nessuna carta di credito) e il pannello di controllo è una pagina
statica che parla direttamente con Telegram e con GitHub dal browser.

## Componenti

- **`curfew_bot.py`** — la logica di apertura/chiusura. In modalità
  `--tick` confronta l'ora attuale con l'ultimo controllo salvato in
  `config/state.json` ed esegue le azioni dovute nel frattempo; supporta
  anche `--open/--close/--list` da riga di comando.
- **`.github/workflows/scheduler.yml`** — fa girare `curfew_bot.py --tick`
  ogni ~15 minuti su GitHub Actions (gratuito), e salva lo stato aggiornato
  nel repository.
- **`docs/index.html`** — il pannello di controllo, una pagina statica senza
  server: gestisci gruppi/orari/messaggi e premi "Salva modifiche" (scrive
  direttamente su GitHub), oppure agisci subito con "Apri ora/Chiudi ora"
  (chiama Telegram direttamente dal browser).
- **`get_chat_id.py`** — script da terminale per recuperare il chat_id di un
  gruppo (in alternativa al pulsante nel pannello).

## 1. Creare il bot

1. Parla con [@BotFather](https://t.me/BotFather) su Telegram, crea un bot e
   copia il token (`123456789:AA...`).
2. Aggiungi il bot al gruppo e promuovilo amministratore con il permesso
   **"Blocca utenti" / "Ban users"** (`can_restrict_members`): è l'unico
   permesso necessario per cambiare i permessi di scrittura del gruppo
   (`setChatPermissions`), non serve per bannare singoli utenti.

## 2. Attivare lo scheduler gratuito (GitHub Actions)

1. Nel repository GitHub, vai su **Settings → Secrets and variables →
   Actions → New repository secret**.
2. Crea un secret chiamato `TELEGRAM_BOT_TOKEN` con il token del bot.
3. Fatto — il workflow in `.github/workflows/scheduler.yml` parte da solo
   ogni ~15 minuti. Per testarlo subito senza aspettare: scheda **Actions**
   del repository → "Curfew scheduler tick" → **Run workflow**.

Ogni esecuzione dura pochi secondi ed è ben dentro i limiti gratuiti di
GitHub Actions (2000 minuti/mese sui repository privati, illimitati su
quelli pubblici) — nessun addebito, nessuna carta di credito richiesta.

## 3. Pubblicare il pannello (GitHub Pages, gratuito)

1. Nel repository, **Settings → Pages**.
2. In "Source" scegli **"Deploy from a branch"**, branch
   `claude/telegram-curfew-bot-e6zdgp`, cartella **`/docs`**.
3. Salva: dopo un minuto GitHub mostra il link pubblico, del tipo
   `https://formoonlightinfo-netizen.github.io/bottelegram/`. Salvalo nei
   preferiti del telefono.

## 4. Usare il pannello

Alla prima apertura, inserisci due codici (restano salvati solo su quel
browser/telefono, non li vede nessun altro):

- **Token del bot Telegram** (lo stesso di sempre) — serve per i pulsanti
  "Apri ora/Chiudi ora" e per recuperare i Chat ID, chiamando Telegram
  direttamente dal browser.
- **Token GitHub** — serve solo per leggere/scrivere
  `config/curfew-config.json` in questo repository quando premi "Salva
  modifiche". Si crea una volta sola: GitHub → foto profilo → **Settings →
  Developer settings → Personal access tokens → Fine-grained tokens →
  Generate new token** → seleziona solo questo repository → permesso
  **"Contents: Read and write"** → Generate token, poi incollalo nel
  pannello.

Poi:

- **"+ Aggiungi gruppo"** per aggiungerne uno nuovo, senza toccare quelli
  esistenti.
- **"Recupera Chat ID dagli ultimi messaggi"** per trovare il chat_id di un
  gruppo appena aggiunto (il bot deve essere già membro e deve esserci
  almeno un messaggio recente nel gruppo — il link d'invito `t.me/+...`
  **non** è il chat_id).
- Ogni gruppo ha una lista di **azioni** settimanali indipendenti
  (apri/chiudi), ognuna con i propri giorni e il proprio orario — non
  devono per forza combaciare (es. chiude il sabato, riapre solo la
  domenica sera). Scattano entro ~15 minuti dall'orario scelto.
- **Chiusura da calendario** (es. ferie, evento speciale): scegli quando
  chiude e quando riapre — anche entrambe nel futuro (es. "chiude mercoledì
  prossimo, riapre tra due settimane"). Se lasci vuoto "Chiude il", chiude
  subito. Nella finestra tra chiusura e riapertura gli orari settimanali
  vengono ignorati; alla data di riapertura il gruppo si riapre da solo.
  "Annulla e riapri subito" cancella la programmazione e riapre
  immediatamente.
- **"Salva modifiche"** scrive la configurazione su GitHub: il prossimo
  tick (entro ~15 minuti) la applica, senza bisogno di fare nient'altro.
- **"Apri ora / Chiudi ora"** applica subito l'azione al gruppo,
  indipendentemente dagli orari programmati.

## 5. Eseguire in locale (facoltativo, per test)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="il-tuo-token"

python curfew_bot.py --list              # elenca i gruppi configurati
python curfew_bot.py --open -1001234567890   # apre subito un gruppo
python curfew_bot.py --close -1001234567890  # chiude subito un gruppo
python curfew_bot.py --tick               # esegue le azioni dovute dall'ultimo tick
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
      "close_message": "🔒 Buonanotte! Il gruppo è chiuso fino a domattina.",
      "pause_from": null,
      "pause_until": null
    }
  ]
}
```

I giorni usano i codici a 3 lettere: `mon tue wed thu fri sat sun`.
`pause_from`/`pause_until` sono gestiti dal pannello (sezione "Chiusura da
calendario") e normalmente non vanno modificati a mano.
