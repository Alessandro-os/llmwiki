# 6. Server, accessi e MCP

[← Indice](README.md) · codice: `server.py`, `mcp_server.py`, `app.py`

## 6.1 Un processo, una porta

LLMWiki è un solo processo che ascolta su una porta (8765, o un'altra se è occupata) e da lì
serve tre cose:

- l'**interfaccia** (una pagina sola, `web/index.html`, all'indirizzo `/`);
- le **API** (`/api/...`), usate dall'interfaccia e utilizzabili da altri programmi;
- il **server MCP** (`/mcp`), per i modelli esterni.

La finestra dell'app è questa stessa pagina aperta senza la barra del browser. Un collega in
rete apre la stessa pagina dal suo browser.

Dentro il processo c'è un oggetto, lo **Hub**, che tiene aperto lo spazio attivo: archivio,
modello, lettore dei documenti, agente. Quando cambi impostazioni o spazio, l'Hub ferma il
lettore, chiude lo spazio e lo riapre con la nuova configurazione, senza riavviare l'app. Se
la nuova configurazione non si apre, torna a quella di prima.

## 6.2 Le rotte per usare la wiki

| Rotta | Che cosa fa |
|---|---|
| `GET /api/status` | Conteggi dei documenti per stato, nodi dell'albero, se sta lavorando, perché è in attesa, modello, giudice in uso, spazi |
| `GET /api/folder?path=` | Come lo strumento `list_folder` |
| `GET /api/node?id=` | Una sintesi di gruppo |
| `GET /api/summary?doc=` | La scheda di un documento |
| `GET /api/document?doc=&start=&end=` | Le righe originali numerate |
| `GET /api/search?q=&folder=&limit=` | Ricerca per parole |
| `POST /api/upload` | Carica file in una cartella dello spazio; i formati non leggibili sono respinti; la lettura parte subito |
| `POST /api/ask` | Domanda, risposta completa alla fine |
| `POST /api/ask/stream` | Domanda, con gli eventi mentre avvengono |
| `POST /api/verify` | Verifica di una singola citazione |
| `GET /api/history`, `DELETE /api/history` | La propria cronologia |

## 6.3 Le rotte di amministrazione

Tutte sotto `/api/admin/`, raggiungibili solo dal computer su cui gira l'app.

| Rotta | Che cosa fa |
|---|---|
| `GET settings`, `POST settings` | Legge e cambia le impostazioni modificabili (elenco a [pagina 8](08-impostazioni.md)); salva `wiki.toml` e riapre lo spazio |
| `GET detect` | Cerca i modelli accesi sul computer |
| `POST models` | Elenco dei modelli del fornitore indicato nel modulo |
| `POST test-model` | La prova di "Salva e prova" |
| `POST secret` | Salva o toglie una chiave |
| `POST model/download` | Avvia lo scaricamento del decision model |
| `GET errors`, `POST retry-errors` | Documenti non letti; li rimette in coda |
| `POST open-folder` | Apre la cartella dei documenti in Esplora file |
| `POST users`, `DELETE users/{nome}` | Crea una persona e restituisce il suo token una volta sola; la rimuove |
| `POST spaces`, `POST spaces/switch`, `DELETE spaces/{id}` | Crea, cambia, toglie uno spazio |
| `POST quit` | Chiude l'app |

## 6.4 Chi può fare cosa

Prima che una richiesta arrivi a qualunque rotta, o al server MCP, passa da un controllo
unico (`AccessMiddleware`) che stabilisce chi sta chiamando.

**Sei "locale"** se valgono tutte e tre:

1. `server.trust_loopback` è attivo (lo è per impostazione predefinita);
2. la connessione arriva dal computer stesso (127.0.0.1 o ::1);
3. l'indirizzo richiesto è anch'esso locale (`127.0.0.1`, `localhost`).

La terza condizione chiude una porta d'ingresso precisa: una pagina web malevola che fa
puntare un nome di dominio al tuo computer per parlare con l'app attraverso il tuo browser
(DNS rebinding).

| Chi | Che cosa può fare |
|---|---|
| Locale | Tutto, senza token, amministrazione compresa. Nella cronologia è l'utente `locale`. |
| Dalla rete con un token valido | Usare la wiki: leggere, cercare, caricare, chiedere, MCP. Non amministrare. |
| Dalla rete senza token | Solo scaricare la pagina dell'interfaccia, che chiede il token. Ogni altra richiesta riceve 401. |

Altri due controlli:

- **Richieste da altre origini.** Una richiesta che modifica qualcosa (non GET) e dichiara di
  venire da una pagina di un altro sito viene respinta con 403. Impedisce a un sito aperto
  nel tuo browser di comandare l'app.
- **Token.** Sono confrontati in tempo costante. Ogni persona ha il suo (32 caratteri
  casuali), salvato in `wiki.toml` nella sezione `[server.users]`; rimuovere la persona lo
  revoca.

## 6.5 Condividere in rete

L'app ascolta solo sul computer stesso (`127.0.0.1`) finché non decidi altrimenti. Per farla
usare ad altri:

1. Impostazioni → "Usarla con altre persone" → aggiungi una persona. Il token compare una
   volta: va copiato e consegnato.
2. Spunta "Rendi l'app raggiungibile dagli altri computer della rete" e salva. L'app
   ascolterà su tutte le interfacce (`0.0.0.0`) **dal prossimo avvio**.
3. Gli altri aprono `http://NOME-DEL-COMPUTER:8765` nel browser e inseriscono il proprio
   token (pulsante "Token" in alto).

Quattro punti del codice impediscono di esporre l'app senza utenti: l'interfaccia non lascia
spuntare la casella, le impostazioni rifiutano il salvataggio, l'app all'avvio ripiega su
`127.0.0.1`, e togliendo l'ultima persona l'app torna da sola a `127.0.0.1`.

Che cosa vedono gli altri: lo stesso spazio attivo, gli stessi documenti, ciascuno la propria
cronologia. Non ci sono permessi per cartella.

Il traffico è HTTP in chiaro: va bene in una rete di casa o d'ufficio fidata. Fuori da lì
serve mettere davanti HTTPS (un reverse proxy) o una VPN. Con un reverse proxy sulla stessa
macchina va impostato `trust_loopback = false`, altrimenti tutte le richieste sembrano
locali.

## 6.6 MCP: collegare un altro modello

MCP è il protocollo con cui un modello esterno (Claude Code, Claude Desktop, LM Studio, Open
WebUI e altri) usa strumenti offerti da un server. LLMWiki ne offre nove:

| Strumento | Che cosa fa |
|---|---|
| `wiki_list_folder`, `wiki_read_node`, `wiki_read_summary`, `wiki_read_document`, `wiki_search`, `wiki_find_documents` | Gli stessi strumenti di lettura dell'agente interno |
| `wiki_verify_citation` | Verifica una citazione con la cascata di [pagina 4](04-verifica-delle-citazioni.md) |
| `wiki_ask` | Fa svolgere tutta la ricerca all'agente del server e restituisce la risposta già verificata |
| `wiki_status` | Stato della lettura dei documenti |

Ci sono quindi due modi di usarla:

- **Il modello esterno naviga da sé.** Usa gli strumenti di lettura, spende i propri token,
  scrive la propria risposta e fa controllare le citazioni con `wiki_verify_citation`. Utile
  quando il modello esterno è più capace di quello collegato all'app.
- **Il modello esterno delega.** Chiama `wiki_ask` e riceve il testo con ✓ e ⚠. Il lavoro lo
  fa il modello collegato all'app.

Il server MCP legge sempre lo spazio attivo: se nell'app cambi spazio, MCP lo segue. Gli
errori previsti (percorso sbagliato, scheda non pronta, modello non raggiungibile) arrivano
al modello esterno con il loro messaggio, così può correggersi.

Collegamento via rete (Streamable HTTP), con le stesse regole di accesso del resto:

```
claude mcp add --transport http llmwiki http://HOST:8765/mcp --header "Authorization: Bearer TOKEN"
```

Dal computer stesso il token non serve. Per i programmi che avviano un processo locale invece
di collegarsi a un indirizzo c'è `llmwiki mcp`, che parla MCP su stdio.
