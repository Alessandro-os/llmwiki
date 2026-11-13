# 4. Verifica delle citazioni

[← Indice](README.md) · codice: `verify.py`, `nli.py`, `llm.py`

## 4.1 Che cosa viene verificato

Una citazione è composta da quattro cose: documento, riga iniziale, riga finale, affermazione.
La verifica risponde a una sola domanda: **le righe citate sostengono l'affermazione?**

Si confrontano sempre due testi: l'affermazione scritta dall'agente e le righe del documento,
rilette dal file `.indice/text/...`. Non conta che cosa l'agente "ricorda" di aver letto.

Tutte le citazioni di una risposta vengono verificate insieme, fino a 8 alla volta.

## 4.2 La cascata

```
 citazione
    │
    ▼
 0. controlli preliminari ───────────── affermazione vuota, documento inesistente ──► ⚠
    │
    ▼
 1. decision model (NLI, sulla CPU, 100-200 ms) ── confidenza ≥ soglia ──► ✓ verified
    │ sotto soglia
    ▼
 2. sì/no del modello linguistico ──────────────── confidenza ≥ soglia ──► ✓ verified
    │ sotto soglia
    ▼
 3. ricontrollo: il modello rilegge le righe         supportata ─────────► ✓ rechecked
    con 20 righe di contesto prima e dopo            non supportata ─────► ⚠ warning
```

La soglia è `verify.threshold` (0,6).

### Passo 0: controlli preliminari

- Affermazione vuota: ⚠ "citazione senza affermazione da verificare".
- Documento non trovato o testo non disponibile: ⚠ "fonte non trovata".
- Le righe vengono riportate dentro il documento (una riga 500 in un documento di 80 diventa
  80) e una citazione più lunga di 150 righe (`verify.max_passage_lines`) viene tagliata.

### Passo 1: il decision model

È `mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`: un modello di *inferenza testuale*
addestrato su 2,7 milioni di coppie in 27 lingue. Non genera testo. Riceve una premessa (le
righe citate) e un'ipotesi (l'affermazione) e restituisce tre probabilità: la premessa
implica l'ipotesi, è neutra, la contraddice. La confidenza della citazione è la prima.

Gira sul processore con ONNX Runtime, usa circa 1,5 GB di memoria e viene caricato alla prima
domanda. Non dipende dal modello linguistico collegato: funziona allo stesso modo con Claude,
con Qwen o con qualunque altro.

Come viene usato, in dettaglio:

1. Davanti alle righe citate si mette il titolo del documento ("Documento: Policy ferie.").
   L'agente scrive "la policy sulle ferie prevede…", e nelle sole righe citate quel contesto
   spesso manca.
2. L'affermazione è tagliata a 160 token.
3. I modelli di questo tipo sono addestrati su premesse brevi: con molto testo irrilevante
   attorno smettono di riconoscere un fatto anche quando c'è. Per questo il passaggio viene
   presentato in più modi:
   - intero, se sta in 200 token; altrimenti in finestre di 200 token sovrapposte per metà;
   - a gruppi di 1, 2 e 3 frasi consecutive (al massimo 240 gruppi).
4. Tutte le varianti sono valutate a blocchi di 16. Vale la probabilità più alta: basta che
   una finestra o un gruppo di frasi sostenga l'affermazione.

Scelto per misura, su 32 citazioni italiane giuste e sbagliate: nessuna sbagliata accettata,
nessuna giusta respinta, circa 160 ms l'una. Scartati la versione compressa a 8 bit dello
stesso modello e LettuceDetect v2, entrambi meno accurati sugli stessi casi.

Il suo limite, visto sulle risposte vere di un agente: respinge una parte delle citazioni
giuste quando l'affermazione è lunga o molto riformulata. È severo, non permissivo. Per
questo è il primo filtro e non l'unico giudice.

### Passo 2: il sì/no del modello linguistico

Il modello del giudice (`llm.judge_model`) riceve le regole, l'affermazione e il passaggio
preceduto da un'intestazione: titolo del documento, righe citate, righe totali, e se le righe
citate sono l'intero documento. Le regole dicono: il passaggio supporta l'affermazione solo se
contiene esplicitamente i fatti affermati (numeri, date, nomi, condizioni); lo stesso
argomento non basta; le conoscenze esterne non contano.

La confidenza si ottiene in due modi, secondo ciò che il server offre:

- **Con le probabilità dei token (logprob).** Il modello deve rispondere con una sola parola,
  YES o NO. L'app non guarda la parola scelta ma la probabilità che il modello assegnava a
  ciascuna: confidenza = P(yes) / (P(yes) + P(no)). È una misura più fine di un sì o un no
  secco. Con i modelli che ragionano prima di rispondere l'app prova tre modi (ragionamento
  spento; risposta breve; risposta lunga guardando la prima parola dopo il ragionamento) e
  ricorda quello che funziona.
- **Senza.** Il modello risponde con un oggetto `{supported, confidence}` in cui dichiara da
  sé la probabilità. È meno affidabile di una probabilità misurata, ma funziona ovunque. Claude
  usa questa strada.

Se il server risponde ma non espone i logprob, l'app lo ricorda e non riprova a ogni
citazione. Se il server non risponde affatto, non lo scambia per "senza logprob": l'errore
resta un errore.

Misurato con Qwen (logprob) sugli stessi 32 casi: nessuna sbagliata accettata, una giusta
respinta, circa 2,3 secondi l'una.

### Passo 3: il ricontrollo

Il modello principale (`llm.agent_model`) rilegge le righe citate con 20 righe di contesto
prima e dopo (`verify.context_lines`), numerate, e risponde con: `supported`, una frase di
motivazione, e le righe che sostengono davvero l'affermazione.

- Se è supportata: stato `rechecked`. Se le righe indicate sono diverse da quelle citate e
  stanno nel tratto mostrato, **la citazione viene corretta** con le righe giuste. È il caso
  tipico dell'agente che ha citato la riga accanto.
- Se non lo è: ⚠, con la motivazione come nota.
- Se il ricontrollo non riesce (modello non raggiungibile): ⚠ "ricontrollo non riuscito".

## 4.3 Gli esiti

| Stato | Segno | Significato |
|---|---|---|
| `verified` | ✓ | Confermata da un giudice veloce (decision model o sì/no). |
| `rechecked` | ✓ | Confermata al ricontrollo; le righe possono essere state corrette. |
| `warning` | ⚠ | Non confermata. La nota dice perché. La citazione resta visibile. |

Ogni citazione porta anche la confidenza (da 0 a 1) e il metodo: `nli`, `nli+logprobs`,
`nli+llm-json`, `nli+logprobs+recheck`, e così via. Cliccando una citazione l'interfaccia
mostra che cosa afferma la risposta, che cosa dice il documento e l'esito; da lì si apre il
documento con le righe evidenziate.

## 4.4 Due casi che richiedono attenzione

**Affermazioni di assenza.** "L'Allegato B non prevede penali" non si può confermare
guardando tre righe. Regola: un'assenza è supportata se le righe citate sono l'intero
documento, o l'intera parte in cui quella cosa dovrebbe trovarsi, e lì non compare. Per
questo all'agente si chiede di citare tutto il documento, e al giudice viene detto quante
righe sono citate su quante.

**Confronti tra documenti.** "Il fatturato 2026 è più alto del 2025" non è sostenuto da
nessuno dei due documenti preso da solo. All'agente si chiede di spezzarlo in due citazioni,
una per documento, ciascuna con il solo fatto che quel documento contiene. Nella prova sulla
raccolta difficile l'unico ⚠ su 102 citazioni era di questo tipo, ed era giustificato.

## 4.5 Quale giudice è in uso

Impostazione `verify.judge`:

| Valore | Con il decision model installato | Senza |
|---|---|---|
| `auto` (predefinito) | decision model, poi sì/no del modello, poi ricontrollo | sì/no del modello, poi ricontrollo |
| `nli` | decision model, poi ricontrollo | sì/no del modello, poi ricontrollo |
| `llm` | sì/no del modello, poi ricontrollo | uguale |

Il decision model si scarica una volta (1,1 GB) dal primo avvio o da Impostazioni. Lo
scaricamento riprende da dove si era interrotto e ogni file è controllato con la sua impronta
SHA-256 prima di essere usato. Appena è completo entra in uso, senza riavviare.

Con `verify.enabled = false` la verifica non parte e le citazioni restano senza esito.

## 4.6 Che cosa la verifica non garantisce

- Controlla che le righe citate sostengano l'**affermazione** della citazione. Non controlla
  che il testo della risposta dica la stessa cosa dell'affermazione: le scrive lo stesso
  modello nello stesso momento, e di norma coincidono, ma nessuno le confronta.
- Una frase senza marcatore `[n]` non viene controllata.
- ✓ significa "il documento dice questo", non "questo è vero" né "questa è tutta la risposta".
  Se un documento importante non è stato trovato, le citazioni presenti sono comunque ✓.
- ⚠ significa "non sono riuscito a confermarla", non "è falsa".
