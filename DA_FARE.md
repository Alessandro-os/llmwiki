# Cose da fare

Elenco unico delle cose rimaste in sospeso. Quelle in alto aspettano una tua azione o una tua
decisione; quelle in basso sono sviluppi possibili.

## Aspettano te

- [ ] **Mettere il progetto su GitHub.** Il repository locale è pronto (ramo `main`, nessun
  segreto nei file, il tuo file dei comandi è escluso). Mancano solo l'accesso e la scelta
  privato/pubblico. Quando puoi:
  1. crea su github.com un repository vuoto chiamato `llmwiki` (consigliato: privato, perché
     la licenza non è scelta e i commit portano il tuo indirizzo email come autore);
  2. nella cartella del progetto esegui i due comandi qui sotto: al primo `push` si apre una
     finestra di GitHub per autorizzare git su questo PC.

  ```
  git remote add origin https://github.com/TUO-UTENTE/llmwiki.git
  git push -u origin main
  ```

  In alternativa dimmi quando hai fatto l'accesso a GitHub nel pannello Browser e lo faccio io.
  Il file `.github/workflows/ci.yml` è già pronto: al primo caricamento GitHub eseguirà da
  solo lint e test a ogni modifica.
- [ ] **Scegliere la licenza del software** (per esempio MIT se vuoi che chiunque possa usarlo,
  oppure nessuna licenza se resta tuo). Finché non c'è, è meglio non distribuirlo fuori dalla
  cerchia di chi lo sta provando. Vedi `LICENSES.md` per i componenti di terze parti.
- [ ] **Firma dell'eseguibile.** Senza un certificato di firma del codice, sugli altri PC
  Windows mostra l'avviso SmartScreen al primo avvio. Il certificato si compra da un'autorità
  di certificazione; serve solo se lo distribuisci a persone che non ti conoscono.
- [ ] **Guardare l'interfaccia a schermo intero.** Contenuti e impaginazione sono controllati
  dal codice della pagina, ma un'occhiata umana a colori, spaziature e testi non c'è stata.
- [ ] **Provare Claude come modello**, se ti interessa: serve una chiave API Anthropic da
  inserire in Impostazioni. Il codice è provato solo contro un endpoint finto.

## Sviluppi possibili

- [ ] Ricerca per significato oltre che per parole (embedding): richiede di scaricare un
  secondo modello; da fare solo se il banco di prova mostra domande che la ricerca per parole
  non trova.
- [ ] Modalità "interrogami": l'app genera domande dagli appunti di una cartella e controlla
  le tue risposte sui testi.
- [ ] OCR per i PDF scansionati (oggi vengono segnalati come non leggibili).
- [ ] Aggiornamento automatico dell'app quando esce una versione nuova.
