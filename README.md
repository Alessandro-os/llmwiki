# LLMWiki

Fai domande ai tuoi documenti e ricevi risposte in cui ogni affermazione rimanda alle righe
del documento da cui viene, con la citazione **controllata**: ✓ se il testo la sostiene, ⚠ se
no. Funziona con un modello locale (Strata, Ollama, LM Studio, llama.cpp, vLLM) o con Claude.

Serve a due usi con la stessa app:

- **personale**: una cartella di appunti in markdown su cui studiare, facendo domande a cui
  l'app risponde solo con ciò che c'è scritto negli appunti;
- **aziendale**: contratti, policy, verbali in una wiki unica, compilata una volta, a cui i
  colleghi si collegano da browser o da MCP con un token personale.

## Per chi la usa

Installa con `LLMWiki-<versione>-setup.exe`, oppure scarica `LLMWiki-<versione>-windows-x64.zip`,
estrailo dove vuoi e apri `LLMWiki.exe`. Le
istruzioni complete sono in `LEGGIMI.txt` dentro la cartella. In breve: al primo avvio l'app
crea lo spazio *Personale*, collega da sola il modello locale se ne trova uno acceso, e da
*Impostazioni* si scarica il decision model, si creano altri spazi (Studio, Lavoro, Azienda) e
si invitano altre persone.

## Come funziona

Qui sotto c'è il riassunto. La spiegazione completa, passaggio per passaggio, è nella wiki del
progetto: [docs/README.md](docs/README.md).

| Problema delle LLM wiki classiche | Cosa fa LLMWiki |
|---|---|
| Un agente indicizza un documento alla volta | Ogni documento riceve la sua scheda in modo indipendente, in parallelo; se ne possono aggiungere altri mentre l'indicizzazione è in corso |
| Le fonti sono citate ma non verificate | Ogni citazione è (affermazione, documento, righe) e passa da una verifica a cascata |
| Ogni utente deve compilarsi la sua wiki | Un solo computer compila la wiki; gli altri si collegano |
| Oltre qualche centinaio di documenti il grafo si inceppa | Nessun grafo da tenere coerente: schede → sintesi di gruppo → mappa della cartella. Un documento nuovo rigenera un solo ramo |

**Indicizzazione.** Il testo di ogni documento viene estratto a righe numerate. Un modello
scrive la *scheda* del documento (sintesi, punti chiave con le righe, riferimenti). Le schede
di una cartella vengono riassunte a gruppi, poi i riassunti, fino alla *mappa della cartella*.
Ogni nodo ricorda l'hash dei suoi figli e viene riscritto solo se sono cambiati.

**Domande.** Non c'è un grafo precompilato: l'agente parte dalla mappa, scende nelle sintesi e
nelle schede, cerca per parole chiave, legge le righe originali e segue i rimandi tra documenti
(`[[link]]` compresi). Per le domande ampie lancia esploratori in parallelo.

Le risposte arrivano a eventi (`/api/ask/stream`): l'interfaccia mostra i passi dell'agente
mentre avvengono e chiudere la connessione lo ferma. Gli scambi precedenti accompagnano le
domande di approfondimento e restano nella cronologia dello spazio, separata per persona.

**Verifica delle citazioni** (`src/llmwiki/verify.py`):

1. *decision model* dedicato: un modello NLI multilingue che gira sulla CPU (decine di
   millisecondi per una citazione di poche righe, qualche secondo per una molto lunga) e dice
   con che probabilità il testo citato implica l'affermazione;
2. sui casi sotto soglia, un sì/no del modello linguistico (con i logprob, se il server li
   espone);
3. se ancora non basta, il modello rilegge il passaggio con più contesto e, se trova il fatto
   poco più in là, corregge le righe;
4. se fallisce anche questo, la citazione resta con ⚠.

Il decision model è `mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` (MIT). È stato scelto
confrontandolo su citazioni italiane giuste e sbagliate: non ne ha accettata nessuna sbagliata.
Da solo respinge una parte delle citazioni corrette più lunghe, ed è per questo che è il primo
filtro di una cascata e non l'unico giudice.

## Indipendenza dal modello

Il resto del codice parla solo con l'interfaccia `LLM` (`src/llmwiki/llm.py`): cambiare modello
significa cambiare un'impostazione. Due backend coprono tutto: l'SDK di Anthropic per Claude e
il protocollo di OpenAI per tutti gli altri (OpenAI, Gemini, OpenRouter, Mistral, Groq, Ollama,
LM Studio, llama.cpp, vLLM, Strata). Aggiungere un fornitore compatibile è una riga in
`PROVIDERS` (`app.py`).

Ogni capacità che non tutti i modelli hanno ha un ripiego, scelto da solo:

| Se il modello o il server... | l'app... |
|---|---|
| non accetta le chiamate a strumenti, o non le usa | descrive gli strumenti nel prompt e legge le chiamate da un oggetto JSON |
| non segue nemmeno quel protocollo | cerca da sé i passaggi più vicini alla domanda e chiede una risposta fondata solo su quelli |
| non impone uno schema all'uscita | mette lo schema nel prompt e legge la risposta con tolleranza |
| non espone i logprob | usa il verificatore locale e, sui casi dubbi, un punteggio dichiarato dal modello |
| rifiuta un parametro facoltativo (effort, cache, rilancio dei rifiuti) | lo toglie, riprova e non lo manda più |
| ha una finestra di contesto piccola | legge i documenti lunghi a pezzi più corti e alleggerisce la conversazione |
| è spento, sovraccarico o limita le richieste | lascia i documenti in coda e riprova da solo, senza segnarli come errore |

Che cosa è stato provato davvero: il modello locale (Qwen su Strata) sia con le chiamate native
sia costretto al protocollo testuale; tutti gli altri comportamenti contro server finti nei
test. I servizi online (Claude, OpenAI, Gemini, OpenRouter, Mistral, Groq) non sono stati
provati dal vivo, perché servono le rispettive chiavi.

## Misure

Rilevate il 2026-11-14 con `evals/run.py` su un PC con RTX 3080 Ti, modello locale Qwen 3.8
Flash Next servito da Strata (una richiesta alla volta). Sono 9 domande su 10 documenti di
esempio: indicano che il meccanismo funziona, non sono un benchmark.

| Cosa | Risultato |
|---|---|
| Risposte corrette, ragionamento predefinito | 9 su 9 · 41 citazioni, nessuna non confermata · 111 s di media |
| Raccolta difficile: 64 documenti, di cui 16 contratti quasi identici | 23 risposte corrette su 24 · 102 citazioni, 1 non confermata (a ragione: un confronto tra due documenti citato su uno solo) · 110 s di media · indice in 47 minuti |
| Stesse 9 domande senza strumenti nativi (protocollo testuale) | 9 su 9 · 17 citazioni, nessuna non confermata · 150 s di media |
| Risposte corrette, ragionamento ridotto | 9 su 9 · 18 citazioni, nessuna non confermata · 68 s di media |
| Decision model su 32 citazioni italiane | 0 sbagliate accettate, 0 giuste respinte · circa 160 ms l'una sulla CPU |
| Giudice del modello linguistico (logprob) sugli stessi casi | 0 sbagliate accettate, 1 giusta respinta · circa 2,3 s l'una |
| Indicizzazione | circa 45 s a documento (scheda) con questo modello |
| Struttura con 5000 documenti (modello finto) | seconda passata 1,4 s senza chiamate · ricerca 8 ms · un documento nuovo rigenera solo il suo ramo |

### Confronto dei modelli locali (2026-11-15)

Stesso PC (RTX 3080 Ti, 48 GB di RAM). Strata per Qwen 3.8 Flash Next, llama.cpp con 4 posti
paralleli per gli altri. Tutti rispondono sullo **stesso indice**, fatto da Strata IQ3_S, così
si confronta solo chi risponde. Dettagli e scelta in
[docs/11-scelta-del-modello.md](docs/11-scelta-del-modello.md).

| Modello | Esempi (9) | Raccolta difficile (24) | Lunghezza media |
|---|---|---|---|
| Strata IQ3_S, ragionamento predefinito | 9/9 · 104 s | 24/24 · 186 s¹ | 946 caratteri |
| Strata IQ3_S, ragionamento ridotto | 7/9² · 71 s | 24/24 · 63 s | 367 |
| **Strata IQ2_XS** | **9/9 · 20 s** | **24/24 · 16 s** | 488 |
| Gemma 4 12B | 9/9 · 31 s | 24/24 · 28 s | 176 |
| Qwen3.5-9B | 9/9 · 46 s | 24/24 · 26 s | 424 |
| Qwen3.5-9B senza ragionamento | 8/9² · 35 s | 24/24 · 47 s¹ | 330 |
| Qwen3.6-35B-A3B | 9/9 · 57 s | 23/24 · 40 s | 340 |
| Qwen3.6-35B-A3B senza ragionamento | 7/9 · 28 s | 23/24 · 21 s | 337 |

Nessuna citazione falsa mostrata come confermata. Le poche ⚠ (solo Qwen3.6) sono affermazioni
del tipo "in quella cartella non c'è" citate su una cartella intera: la verifica le ha
respinte a ragione.

¹ Una sola domanda pesa sulla media: quella senza risposta nei documenti. IQ3_S ci ha messo
37 minuti (98 s di media senza di lei), Qwen3.5 senza ragionamento 13 minuti.
² Le risposte erano giuste ma scritte in formule (`\frac{5}{2}`, `0{,}40`), che il controllo
automatico non riconosce.

Indice nuovo della raccolta difficile (64 documenti) fatto da ciascun modello, poi le
risposte su quell'indice:

| Modello | Indice | Risposte |
|---|---|---|
| Strata IQ3_S (14 novembre) | 47 min | 23/24 · 110 s |
| **Strata IQ2_XS** | **18 min** | 23/24 · 17 s (l'errore: una riga citata sbagliata, segnata ⚠ dalla verifica) |
| Qwen3.5-9B, schede senza ragionamento | 15 min | 24/24 · 47 s |
| Gemma 4 12B | 33 min | 24/24 · 45 s |
| Qwen3.6-35B-A3B | 61 min | 23/24 · 44 s |
| Qwen3.5-9B | 80 min | 24/24 · 55 s |

### Confronto degli OCR (2026-11-16)

Una pagina di appunti con testo noto: italiano con accenti e formule (η, ΔU, ∮ δQ/T, ω = 2πn/60,
pedici). Due versioni: pulita, e "da scanner" (storta di 1,2°, sfocata, con rumore). RTX 3080 Ti
12 GB. Somiglianza al testo vero dopo aver tolto le coordinate dei riquadri; le formule scritte in
LaTeX (`$\eta = 1 - T_2/T_1$`) contano come differenze, anche se sono giuste.

| OCR | Somiglianza (pulita / scanner) | Accenti | Simboli | Secondi a pagina | Memoria scheda video |
|---|---|---|---|---|---|
| Tesseract 5.4, solo inglese | 0,957 / 0,957 | 1 su 3 | 0 su 6 | 0,3 | nessuna |
| Strata IQ2_XS con la vista (stesso modello delle risposte) | 0,928 / 0,928 | 3 su 3 | 6 su 6 | 5 | già caricato |
| Unlimited OCR 2, transformers su Windows | 0,928 / 0,928 | 3 su 3 | 6 su 6 | 24 | 7,4 GB (Strata spento) |

Unlimited OCR 2 gira su Windows anche senza Triton (lo usa solo se c'è), ma con transformers è
lento: SGLang, consigliato da Baidu, è documentato solo su Linux. Non entra nella scheda insieme a
Strata (11,4 GB). Su questo PC Strata legge le pagine come Unlimited OCR, 5 volte più in fretta e
senza memoria in più. Non misurati: scrittura a mano, tabelle, pagine di libro lunghe.

## Dove stanno i dati

```
<spazio>/wiki.toml                 impostazioni dello spazio
<spazio>/documenti/...             documenti originali
<spazio>/.indice/text/...          testo estratto, a righe numerate (ciò che si cita)
<spazio>/.indice/summaries/...     schede
<spazio>/.indice/tree/...          sintesi di gruppo e mappe delle cartelle
<spazio>/.indice/state.db          stato, albero, indice full-text (SQLite FTS5)

%LOCALAPPDATA%\LLMWiki\app.json    spazi conosciuti, spazio attivo, porta
%LOCALAPPDATA%\LLMWiki\models\     decision model
%LOCALAPPDATA%\LLMWiki\secrets.json  chiavi API (mai dentro gli spazi)
%LOCALAPPDATA%\LLMWiki\logs\       log
```

Uno spazio è una cartella autonoma: si copia, si sposta, si mette in backup così com'è.

## Accessi

- Dal computer su cui gira l'app non serve nessun token e si può amministrare
  (`/api/admin/...`: modelli, spazi, utenti).
- Dagli altri computer serve un token personale e l'amministrazione è chiusa.
- L'app non si espone in rete finché non esiste almeno un utente.
- Il server parla HTTP semplice: su reti non fidate va messo dietro HTTPS o una VPN. Se davanti
  c'è un reverse proxy sulla stessa macchina, impostare `trust_loopback = false` in `[server]`.

## MCP

`http://HOST:8765/mcp` (Streamable HTTP) espone `wiki_list_folder`, `wiki_read_node`,
`wiki_read_summary`, `wiki_read_document`, `wiki_search`, `wiki_find_documents`,
`wiki_verify_citation`, `wiki_ask`, `wiki_status`. Un modello collegato può navigare la wiki
da solo e far verificare le proprie citazioni, oppure chiamare `wiki_ask` e ricevere la
risposta già verificata.

```bash
claude mcp add --transport http llmwiki http://HOST:8765/mcp --header "Authorization: Bearer TOKEN"
```

## Per chi sviluppa

```bash
uv sync
```

```bash
uv run pytest
```

```bash
uv run llmwiki app
```

Server senza interfaccia desktop, su una cartella con il suo `wiki.toml`:

```bash
uv run llmwiki init
```

```bash
uv run llmwiki serve
```

Altri comandi: `index`, `ask "domanda"`, `status`, `user add <nome>`, `mcp` (stdio),
`model install`. Demo senza modello: `uv run llmwiki -c examples/wiki.demo.toml serve`.

Banco di prova (decision model, risposte sui documenti di esempio, tenuta con molti documenti):

```bash
uv run python evals/run.py judge
```

```bash
uv run python evals/run.py answers --config percorso/wiki.toml
```

```bash
uv run python evals/run.py scale --docs 5000
```

Con `answers --suite difficile` le domande girano su 64 documenti generati apposta per
confondere (sedici contratti con la stessa struttura e numeri diversi), con risposte note.

Pacchetto distribuibile: cartella `dist/LLMWiki`, zip e, se Inno Setup è installato
(`winget install JRSoftware.InnoSetup`), `LLMWiki-<versione>-setup.exe`. La build collauda
l'eseguibile prima di impacchettarlo:

```bash
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Codice in `src/llmwiki/`:

| File | Cosa contiene |
|---|---|
| `indexer.py` | schede in parallelo e albero di riassunti incrementale |
| `tools.py` | strumenti di navigazione (usati da agente, API e MCP) |
| `agent.py` | agente che risponde con citazioni, esploratori in parallelo |
| `verify.py`, `nli.py` | verifica a cascata e decision model |
| `llm.py` | backend: Claude, OpenAI-compatibile, mock |
| `server.py`, `mcp_server.py` | API, interfaccia web, MCP |
| `app.py`, `apphome.py` | spazi, cartella dell'app, cambio di impostazioni a caldo |
| `desktop.py` | app desktop (finestra, icona, primo avvio) |

I test usano il provider `mock` e finti endpoint HTTP: non servono credenziali né modelli.
`LICENSES.md` elenca i componenti di terze parti.
