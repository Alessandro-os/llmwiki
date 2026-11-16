# 10. Limiti noti

[← Indice](README.md)

Che cosa l'app non fa o non garantisce nella versione 0.5.0. Gli sviluppi possibili sono in
`DA_FARE.md`.

## Non provato

- **Servizi online.** Claude, OpenAI, Gemini, OpenRouter, Mistral e Groq non sono stati
  provati dal vivo: mancavano le chiavi. Il codice è provato contro server finti che ne
  imitano i comportamenti.
- **Altri sistemi operativi.** L'app è costruita e provata su Windows 11. Il server e la riga
  di comando non hanno nulla di specifico di Windows; la finestra, l'icona e l'installer sì.
- **Raccolte grandi con un modello vero.** La struttura è provata con 5.000 documenti e il
  modello finto. Con un modello vero la prova più grande è di 64 documenti.

## Risposte

- **Velocità con un modello locale.** Con Qwen su Strata una risposta richiede circa due
  minuti e una scheda circa 45 secondi, perché il server elabora una richiesta alla volta.
- **La ricerca è per parole.** Un sinonimo non scritto nel testo non viene trovato dalla
  ricerca. Rimediano le mappe e l'agente che riformula; sulla raccolta difficile il documento
  giusto è stato trovato 24 volte su 24. Con migliaia di documenti molto simili potrebbe non
  bastare.
- **La risposta può essere incompleta.** L'agente si ferma quando ritiene di avere abbastanza.
  Le citazioni presenti sono controllate; l'assenza di un documento che non ha aperto no.
- **La modalità "ricerca diretta"** (per i modelli che non sanno usare gli strumenti) non
  segue i rimandi tra documenti.
- **La verifica ha i confini descritti a [pagina 4](04-verifica-delle-citazioni.md), 4.6.**

## Documenti

- **Scansioni e appunti a mano.**
  - **Formati:** si leggono con l'OCR solo i PDF; le immagini sciolte (.png, .jpg) no.
  - **Scrittura a mano:** MiniCPM-OCR ne legge circa la metà delle parole (45% su sei pagine
    di prova). Il resto esce storpiato, in modo riconoscibile: le citazioni su quelle righe di
    solito non vengono confermate.
  - **Installazione a mano:** l'app non scarica l'OCR; va scaricato una volta, seguendo la
    [guida](12-installare-un-ocr.md) (circa 1,8 GB per MiniCPM-OCR con llama.cpp).
  - **Velocità:** senza scheda video libera, 30-50 secondi a pagina.
  - **Non verificato:** le misure sono state fatte con llama.cpp in versione CUDA; le versioni
    Vulkan e solo processore non sono state provate su questo PC.
  - **Ricerca:** gli OCR locali si cercano fino a 6 livelli di cartelle sotto quelle note; un
    modello più in profondità va indicato con la sua cartella in "Altre cartelle dove cercare".
  - **Cambio di modo:** cambiando il modo dello spazio, i documenti già letti non si rileggono
    da soli; si rileggono uno per uno con "Rileggi".
- **Immagini, tabelle complesse, formule in immagine** dentro PDF e Word non vengono lette.
  Delle tabelle Word si legge il testo delle celle.
- **Fogli di calcolo e presentazioni** (`.xlsx`, `.pptx`) non sono supportati; i `.csv` sì.
- **Un documento modificato viene riletto per intero**, anche se è cambiata una riga.

## Condivisione

- **HTTP in chiaro.** Fuori da una rete fidata servono HTTPS o una VPN davanti.
- **Nessun permesso per cartella.** Chi ha un token vede tutto lo spazio attivo.
- **Uno spazio attivo alla volta.** Tutte le persone collegate vedono lo stesso; cambiarlo
  dall'app lo cambia per tutti.
- **Nessun registro di chi ha chiesto cosa**, oltre alla cronologia personale.
- **Chiavi e token sono salvati in chiaro** in `secrets.json` e in `wiki.toml`, protetti solo
  dai permessi del profilo utente.

## Distribuzione

- **Eseguibile non firmato:** su altri PC Windows mostra l'avviso SmartScreen al primo avvio.
- **Aggiornamento solo su richiesta e solo nell'app desktop per Windows:** l'app avvisa ma non
  si aggiorna da sola. Il controllo dipende da GitHub: senza rete, o se il repository
  `Alessandro-os/llmwiki` non è pubblico, il tasto non compare.
- **Licenza del software non ancora scelta**, anche se il repository è pubblico.
