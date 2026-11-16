# 9. Per chi sviluppa

[← Indice](README.md)

Questa pagina dice com'è fatto il codice e come si prova. Il metodo di lavoro (principi,
ciclo, qualità, resoconto) sta in [AGENTS.md](../AGENTS.md), che leggono anche Claude Code,
opencode e pi.

## 9.1 Mappa del codice

Tutto in `src/llmwiki/`. Le frecce dicono chi usa chi; nessun modulo in basso conosce quelli
sopra.

```
 desktop.py  cli.py                 punti d'ingresso: app desktop, riga di comando
      │        │
      ▼        ▼
 server.py ── mcp_server.py         API, interfaccia, accessi · strumenti MCP
      │
      ▼
 app.py                             Wiki (uno spazio aperto) e Hub (cambio a caldo), fornitori, chiavi
      │
      ├── indexer.py                schede in parallelo, albero incrementale
      ├── agent.py ── verify.py ── nli.py     agente · cascata di verifica · decision model
      ├── tools.py                  strumenti di navigazione
      ├── llm.py                    interfaccia unica verso i modelli e ripieghi
      ├── store.py                  file su disco + SQLite (stato, albero, ricerca, cronologia)
      ├── extract.py ── ocr.py      da file a righe numerate · qualunque OCR (server o Tesseract)
      │       └── minicpm.py        MiniCPM-OCR gestito dall'app: scaricamento, accensione, strisce
      ├── prompts.py                tutti i prompt di sistema
      ├── config.py                 wiki.toml: voci, predefiniti, lettura e scrittura
      ├── update.py ── download.py  aggiornamenti da GitHub · scaricamento verificato (anche nli.py)
      ├── apphome.py                cartella dell'app, registro degli spazi
      └── icon.py                   l'icona: area di notifica, finestra, eseguibile
 web/index.html                     l'interfaccia: una pagina, senza dipendenze né build
```

| Se vuoi cambiare… | Guarda in… |
|---|---|
| come sono scritte schede, sintesi, mappe, o le regole dell'agente | `prompts.py` |
| come si raggruppano i documenti o quando si aggiorna l'albero | `indexer.py` |
| che cosa può fare l'agente | `tools.py` (lo strumento) e `agent.py` (il ciclo) |
| l'ordine o la severità dei controlli sulle citazioni | `verify.py` |
| il supporto a un formato di file | `extract.py` |
| un tipo di OCR | una nuova classe `Ocr` in `ocr.py` e una voce in `make_ocr` |
| un nuovo fornitore compatibile OpenAI | una riga in `PROVIDERS`, `app.py` |
| un fornitore con un protocollo suo | una nuova classe `LLM` in `llm.py` e una voce in `make_llm` |
| una nuova impostazione | il campo in `config.py`; se va nell'interfaccia, anche `EDITABLE` in `server.py` |

## 9.2 Ambiente

Python 3.11 o successivo, gestito con `uv`.

```bash
uv sync
```

```bash
uv run llmwiki app
```

```bash
uv run ruff check
```

Prova senza nessun modello, con i documenti di esempio:

```bash
uv run llmwiki -c examples/wiki.demo.toml serve
```

Riga di comando: `init`, `index`, `status`, `ask "domanda"`, `serve`, `mcp`, `app`,
`model install|status`, `user add <nome>`. L'opzione `-c` indica un `wiki.toml`.

## 9.3 Test

```bash
uv run pytest
```

I test non richiedono né modelli né chiavi: usano il fornitore `mock` e server HTTP finti.
Ogni test gira con `LLMWIKI_HOME` puntato a una cartella temporanea, quindi non tocca gli
spazi veri.

| File | Che cosa copre |
|---|---|
| `test_pipeline.py` | Albero e aggiornamento incrementale, file spostati, file modificati durante la lettura, lettura in parallelo, documenti lunghi a pezzi, risposta con citazioni verificate, percorsi che non possono uscire dallo spazio, caricamento e accessi dal server, MCP via rete con token |
| `test_extract.py` | PDF, Word, HTML, codifiche, righe lunghe, nomi di file accentati |
| `test_backends.py` | I due protocolli contro server finti: strumenti, giudice senza logprob, parametri facoltativi rifiutati da Claude, server spento non scambiato per server senza logprob |
| `test_independence.py` | Modello che rifiuta o ignora gli strumenti, modalità testuale forzata, contesto piccolo, lettura che aspetta il modello invece di fallire, chiave sbagliata segnalata senza riprovare all'infinito |
| `test_app.py` | Configurazione, spazi, persone e impostazioni dall'interfaccia, qualunque fornitore, avanzamento in diretta, cronologia e approfondimenti, amministrazione solo locale, chiavi fuori dallo spazio, cascata del decision model |
| `test_ocr.py` | OCR contro server finti: lettura, errori come per i modelli, prova con l'immagine nota, ricerca (prima chi legge), PDF scansionato con OCR e senza, documento in attesa se l'OCR manca o è spento, impostazioni dall'interfaccia; modo automatico e modo per documento (caricamento, "Rileggi"); strisce che non tagliano le righe; ripetizioni interrotte; MiniCPM-OCR sulla scheda video o sul processore e scaricamento verificato; Tesseract vero se installato |
| `test_update.py` | Aggiornamenti contro un GitHub finto: versione nuova, nessuna novità, rete assente, impronta sbagliata (file cancellato, niente installazione), pulizia degli installatori usati |
| `test_evals.py` | Coerenza dei file del banco di prova; il decision model mantiene la qualità misurata (se installato) |

## 9.4 Banco di prova

I test dicono se il codice funziona; il banco di prova (`evals/run.py`) dice **quanto bene**
risponde con un modello vero. Va rieseguito prima e dopo ogni modifica a prompt, verifica o
ricerca.

```bash
uv run python evals/run.py judge
```

Valuta il giudice delle citazioni su `evals/judge_cases.json`: 32 coppie italiane
(affermazione, passaggio) di cui si sa se sono giuste o sbagliate. Riporta quante sbagliate
sono state accettate e quante giuste respinte. Con `--config` prova anche il giudice del
modello linguistico; `--threshold` cambia la soglia (0,6).

```bash
uv run python evals/run.py answers --config percorso/wiki.toml
```

Indicizza i documenti di `examples/docs` in una cartella di lavoro e pone le 9 domande di
`evals/questions.json`. Per ogni domanda controlla: che la risposta contenga i valori attesi
(`must_contain`), che citi il documento giusto (`must_cite`), e, per la domanda senza
risposta, che l'agente dica che l'informazione non c'è. Riporta tempi, citazioni, ⚠ e metodi
di verifica. Opzioni: `--suite difficile`, `--limit N`, `--fresh` (rifà l'indice),
`--work CARTELLA` (cartella di lavoro dentro `evals/`, per tenere separati gli indici di
modelli diversi), `--out FILE` (nome del rapporto, salvato nella cartella di lavoro).

Il rapporto JSON contiene le impostazioni usate, il tempo dell'indice e, per ogni domanda, il
testo della risposta, i passi dell'agente e degli aiutanti, le deleghe e il tempo della
verifica: serve a capire dove va il tempo e a rileggere le risposte, non solo a contarle.
Per confrontare chi risponde a parità di indice si copia una cartella di lavoro già fatta e la
si passa con `--work` a ogni configurazione, senza `--fresh`.

La suite `difficile` (`evals/corpus.py`) genera 64 documenti fatti per confondere, tra cui 16
contratti con la stessa struttura e numeri diversi, e 24 domande con risposta nota.

```bash
uv run python evals/run.py scale --docs 5000
```

Con il modello finto misura la tenuta della struttura: tempo di una seconda passata senza
novità, tempo di ricerca, e che un documento nuovo rigeneri solo il suo ramo. `--folders`
indica in quante cartelle distribuire i documenti (10).

Risultati registrati: tabella "Misure" nel `README.md` della radice.

## 9.5 Costruire il pacchetto

```bash
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Lo script, nell'ordine:

1. `uv sync`;
2. genera l'icona (`packaging/llmwiki.ico`) dal disegno in `icon.py`, lo stesso che il server
   usa come favicon della finestra e l'app per l'area di notifica;
3. PyInstaller con `packaging/llmwiki.spec`: due eseguibili nella stessa cartella,
   `LLMWiki.exe` (senza console) e `llmwiki-cli.exe` (riga di comando);
4. copia `LEGGIMI.txt` e l'elenco delle licenze;
5. **collaudo dell'eseguibile** (`packaging/smoke_test.py`). Se non passa, niente pacchetti;
6. zip `dist\LLMWiki-<versione>-windows-x64.zip`;
7. se Inno Setup è installato, `dist\LLMWiki-<versione>-setup.exe`.

Il collaudo avvia l'eseguibile vero in una cartella dati usa e getta, con il modello finto, e
controlla undici cose: si avvia e risponde; indicizza un documento caricato; conferma una
citazione giusta; segnala una citazione sbagliata; risponde con l'avanzamento in diretta;
ricorda la cronologia; espone gli strumenti MCP; apre le impostazioni; serve l'interfaccia;
si chiude a comando; non lascia errori nel log.

## 9.6 Versioni

Il numero di versione sta in due posti da tenere uguali: `pyproject.toml` e
`src/llmwiki/__init__.py`. Le novità si scrivono in `CHANGELOG.md`, divise tra "per chi la
usa" e "per chi sviluppa". Le cose in sospeso stanno in `DA_FARE.md`.

Il progetto sta su GitHub in un repository privato, `Alessandro-os/llmwiki`. Ogni versione ha
la sua etichetta (`v0.5.0`) e una release con l'installatore e lo zip.
`.github/workflows/ci.yml` esegue lint e test a ogni caricamento.
