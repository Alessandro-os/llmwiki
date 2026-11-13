# 8. Impostazioni

[← Indice](README.md) · codice: `config.py`, `server.py` (`EDITABLE`)

Ogni spazio ha il suo `wiki.toml`. Lo scrive sempre l'app; si può anche modificare a mano con
l'app chiusa. Una voce che l'app non conosce (un refuso, o una voce scritta da una versione
più recente) viene ignorata con un avviso nel log: non blocca l'avvio.

La colonna **App** dice se la voce si cambia dall'interfaccia (sì), solo tramite le API di
amministrazione (API), o solo nel file (file).

## [paths]

| Voce | Predefinito | Effetto |
|---|---|---|
| `docs` | `documenti` negli spazi creati dall'app | Cartella dei documenti, relativa a `wiki.toml` |
| `wiki` | `.indice` negli spazi creati dall'app | Cartella dell'indice |

Con `llmwiki init` da riga di comando i predefiniti sono `data/docs` e `data/wiki`.

## [llm]

| Voce | Predefinito | App | Effetto |
|---|---|---|---|
| `provider` | `anthropic` | sì | `anthropic`, `openai` (qualunque server compatibile) oppure `mock` (dimostrazione) |
| `agent_model` | `claude-opus-5-5` | sì | Modello che naviga, risponde e fa il ricontrollo |
| `summary_model` | `claude-opus-5-5` | sì | Modello per schede, sintesi e mappe |
| `judge_model` | `claude-haiku-5-5` | sì | Modello per il sì/no sulle citazioni |
| `base_url` | `http://localhost:11434/v1` | sì | Indirizzo del server (solo `openai`) |
| `api_key_env` | `OPENAI_API_KEY` | sì | Nome con cui è salvata la chiave (solo `openai`) |
| `agent_effort` | `high` | sì | Livello di ragionamento per le risposte |
| `summary_effort` | `medium` | sì | Livello di ragionamento per i riassunti |
| `judge_effort` | `low` | file | Livello di ragionamento per il giudice |
| `send_reasoning_effort` | `false` | sì | Solo `openai`: manda i livelli al server come `reasoning_effort` |
| `tool_mode` | `auto` | sì | `auto`, `native`, `text`: come l'agente usa gli strumenti |
| `context_tokens` | `0` | sì | Finestra del modello in token; 0 = non nota, nessun limite applicato in anticipo |
| `refusal_fallbacks` | `true` | file | Solo Claude: rilancio lato server dei rifiuti dei classificatori |
| `timeout` | `600` | file | Secondi massimi per una richiesta al modello |

Al primo avvio l'app non usa questi predefiniti: collega il modello locale che trova, oppure
imposta `mock`.

## [index]

| Voce | Predefinito | App | Effetto |
|---|---|---|---|
| `concurrency` | `8` (2 con un modello locale collegato dall'app) | sì | Documenti in lettura insieme e richieste al modello aperte insieme. Da 1 a 64 |
| `fanout` | `8` | API | Elementi riassunti da ogni sintesi o mappa. Da 2 a 64. Cambiarlo rifà l'albero |
| `chunk_chars` | `24000` | file | Oltre questa lunghezza un documento viene letto a pezzi |
| `watch_seconds` | `20` | file | Ogni quanto l'app ricontrolla la cartella dei documenti |

## [verify]

| Voce | Predefinito | App | Effetto |
|---|---|---|---|
| `enabled` | `true` | API | Se spento, le citazioni non vengono verificate |
| `judge` | `auto` | sì | `auto`, `nli`, `llm`: chi controlla ([pagina 4](04-verifica-delle-citazioni.md), 4.5) |
| `threshold` | `0.6` | sì | Confidenza minima per confermare. Tra 0 e 1, estremi esclusi |
| `context_lines` | `20` | file | Righe di contesto prima e dopo, mostrate al ricontrollo |
| `max_passage_lines` | `150` | file | Una citazione più lunga viene tagliata |

Alzare la soglia manda più citazioni al controllo successivo (più lento, più severo);
abbassarla ne conferma di più al primo colpo.

## [agent]

| Voce | Predefinito | App | Effetto |
|---|---|---|---|
| `max_steps` | `24` | file | Passi al massimo per una domanda |
| `explorers` | `4` | file | Esploratori che lavorano insieme |
| `explorer_steps` | `12` | file | Passi al massimo per un esploratore |

## [server]

| Voce | Predefinito | App | Effetto |
|---|---|---|---|
| `host` | `127.0.0.1` | sì | `0.0.0.0` espone l'app in rete; richiede almeno una persona. Vale dal prossimo avvio |
| `port` | `8765` | API | Porta. Nell'app desktop vale quella salvata in `app.json` |
| `trust_loopback` | `true` | file | Chi si collega dal computer stesso non ha bisogno di token e può amministrare. Da mettere a `false` dietro un reverse proxy sulla stessa macchina |

## [server.users]

Una riga per persona: `nome = "token"`. Si gestisce da Impostazioni → "Usarla con altre
persone" o con `llmwiki user add <nome>`. Il nome può contenere lettere, cifre, `_` e `-`,
fino a 40 caratteri.

## Che cosa succede quando salvi dall'interfaccia

1. L'app rilegge `wiki.toml` dal disco e vi applica solo le voci ricevute.
2. Controlla i valori (fornitore noto, soglia tra 0 e 1, parallelismo tra 1 e 64, niente rete
   senza persone). Se uno non va, non salva nulla e mostra il motivo.
3. Scrive il file in modo atomico.
4. Riapre lo spazio con la nuova configurazione. La lettura dei documenti riprende da dove
   era; una domanda in corso in quel momento può interrompersi con un errore, quindi conviene
   salvare quando nessuno sta chiedendo.
