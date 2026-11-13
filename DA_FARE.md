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
- [ ] **Dare un'occhiata all'interfaccia nuova.** L'ho ridisegnata e controllata a schermo
  (tema scuro e chiaro, primo avvio, impostazioni, documenti, risposta, fonte), ma il giudizio
  che conta è il tuo e quello di chi non l'ha mai vista: testi, colori, cosa non si capisce.
- [ ] **Provare un servizio online** (Claude, OpenAI, Gemini, OpenRouter, Mistral, Groq): serve
  la chiave del servizio, da incollare in Impostazioni. Il codice è provato contro server
  finti che ne imitano i comportamenti, non contro i servizi veri. Il più economico per una
  prova è OpenRouter, che con una chiave dà accesso a molti modelli.

## Consigli per lo sviluppo

In ordine di importanza, secondo me.

1. **Fallo usare a tre persone vere prima di aggiungere altro.** Una che studia, una che
   lavora con contratti, una che non sa cosa sia un modello. Guardale mentre lo usano senza
   aiutarle: dove si fermano è il prossimo lavoro da fare, più di qualunque idea nostra.
2. **Tieni il banco di prova come cancello.** Ogni modifica a prompt, verifica o ricerca si
   misura con `evals/run.py` prima e dopo. Senza numeri, con i modelli ci si convince
   facilmente di aver migliorato qualcosa che è peggiorato.
3. **Allarga il banco di prova con domande tue.** Le mie sono inventate. Venti domande vere
   sui tuoi documenti, con la risposta giusta scritta da te, valgono più di tutte le mie.
4. **La velocità è il limite più sentito.** Due minuti a risposta con il modello locale sono
   tanti. Le leve, dalla più semplice: ragionamento ridotto (già nelle Impostazioni), un
   modello più piccolo per i riassunti, un servizio online per chi può mandare fuori i dati.
5. **Decidi presto a chi è rivolto.** Studente singolo e azienda hanno bisogni diversi:
   l'azienda chiederà permessi per cartella, HTTPS, copie di sicurezza, un registro di chi ha
   chiesto cosa. Meglio farne bene uno che a metà tutti e due.
6. **Prima di esporlo in rete fuori casa: HTTPS.** Oggi i token viaggiano in chiaro; va bene
   su una rete fidata, non altrove.
7. **Non aggiungere la ricerca per significato finché una misura non la chiede.** Sulla
   raccolta difficile la ricerca per parole ha trovato il documento giusto 24 volte su 24.
8. **Scegli licenza e nome definitivo prima di pubblicare**, e firma l'eseguibile se andrà a
   persone che non ti conoscono.

## Sviluppi possibili

- [ ] Ricerca per significato oltre che per parole (embedding): richiede di scaricare un
  secondo modello. Per ora non serve: nella raccolta difficile (64 documenti molto simili) la
  ricerca per parole più la navigazione ha trovato il documento giusto 24 volte su 24. Da
  riconsiderare con raccolte di migliaia di documenti.
- [ ] Velocità con i modelli locali: oggi un documento richiede 25-45 secondi e una risposta
  circa due minuti, perché Strata elabora una richiesta alla volta. Si può provare un modello
  più piccolo per le schede, tenendo quello attuale per le risposte.
- [ ] Modalità "interrogami": l'app genera domande dagli appunti di una cartella e controlla
  le tue risposte sui testi.
- [ ] OCR per i PDF scansionati (oggi vengono segnalati come non leggibili).
- [ ] Aggiornamento automatico dell'app quando esce una versione nuova.
