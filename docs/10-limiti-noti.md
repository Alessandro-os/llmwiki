# 10. Limiti noti

[← Indice](README.md)

Che cosa l'app non fa o non garantisce nella versione 0.4.0. Gli sviluppi possibili sono in
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

- **PDF scansionati.** Senza testo estraibile vengono segnalati come non letti: manca l'OCR.
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
- **Nessun aggiornamento automatico:** una versione nuova si installa sopra la precedente.
- **Licenza del software non ancora scelta.**
