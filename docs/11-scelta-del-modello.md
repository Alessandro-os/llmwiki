# 11. Quale modello locale usare su un dato PC

[← Indice](README.md)

Questa pagina mostra il ragionamento per scegliere il modello locale da collegare a LLMWiki,
applicato a un PC reale il 13 novembre 2026. È scritta perché il ragionamento si possa rifare
quando cambia l'hardware: i numeri cambiano, i passi no.

## Il PC di partenza

| Componente | Valore |
|---|---|
| Scheda video | RTX 3080 Ti, 12 GB |
| RAM | 48 GB DDR4 (2×8 + 2×16), in arrivo 64 GB |
| Processore | Ryzen 9 5950X, 16 core |
| Motore | Strata 0.1.59, usato anche da opencode e pi |
| Modello caricato | Qwen3.8-Flash-Next IQ3_S, contesto 128K |
| Già scaricati | IQ3_S, IQ3_XXS, IQ2_XS, Coder IQ1_M |

## Passo 1: che cosa serve a LLMWiki

| Requisito | Perché |
|---|---|
| Chiamate a strumenti affidabili | L'agente naviga con gli strumenti; senza, si ripiega su modalità meno complete ([pagina 5](05-modelli.md)) |
| Buon italiano, in lettura e scrittura | Schede e risposte sono nella lingua dei documenti |
| Almeno 16-32K di contesto | Una scheda usa circa 8.000 token; la conversazione dell'agente cresce a ogni passo |
| Uscita strutturata | Ricontrollo delle citazioni e ricerca diretta |
| Logprob (facoltativi) | Giudice più fine; senza, c'è il decision model |
| Velocità | Una risposta costa migliaia di token tra ragionamento e passi |

Qwen3.8-Flash-Next su Strata li soddisfa tutti, ed è già misurato: 9 su 9 e 23 su 24 sul banco
di prova. La domanda quindi non è "quale modello sa farlo" ma "quale versione sta bene in
questo PC".

## Passo 2: il vincolo è la memoria, non il contesto

Strata tiene il modello su tre livelli: scheda video (gli esperti più usati), RAM (gli altri),
SSD (quelli che in RAM non stanno). La sua documentazione dà una regola:

> la RAM deve essere almeno gli esperti più circa 10 GB

e avverte che su Windows il margine di sicurezza è di 8 GiB.

| Versione | Esperti | RAM che serve (esperti + 10) | Con 48 GB | Con 64 GB | Velocità di riferimento¹ | Stesso token del modello pieno² |
|---|---|---|---|---|---|---|
| Q2_0 | 34 GB | 44 GB | entra | entra | 87 / 74 token/s | 80,6% |
| IQ2_XS | 35,5 GB | 45,5 GB | entra | entra | 80 / 63 | non pubblicato ("better") |
| IQ3_XXS | 43 GB | 53 GB | **non entra** | entra | 62 / 49 | 84,5% |
| IQ3_S | 50 GB | 60 GB | **non entra** | entra a filo | 52 / 46 | 87,7% |
| Coder IQ1_M | 23 GB | 33 GB | entra | entra | 59 / 43 | più debole fuori dal codice e dall'inglese |

¹ Misure del progetto Strata su RTX 5070 12 GB, Ryzen 5 7600, 64 GB DDR5: conversazione breve /
contesto pieno a 128K. Su questo PC i valori assoluti sono diversi; contano i rapporti.
² Quante volte la versione sceglie lo stesso token della versione a 8 bit.

La documentazione lo dice anche a parole: "With 48 GB only Q2_0 and IQ2_XS may fit"; con 64 GB
entrano tutte, "IQ3_S with little else open", e per IQ3_XXS "close the browser" e contesto
fino a 128K.

**Il contesto pesa poco.** Costa circa 13,7 KB di RAM per token: 1,7 GB a 128K, 0,4 GB a 32K.
Scendere da 128K a 32K libera circa 1,3 GB, contro i 14,5 GB di differenza tra IQ3_S e
IQ2_XS. Il contesto da 128K, che serve a opencode e pi, si può tenere.

## Passo 3: che cosa succede oggi

IQ3_S su 48 GB è fuori regola di circa 12 GB. Le misure sul PC lo confermano:

| Misura | Valore | Significato |
|---|---|---|
| RAM libera con Strata acceso | 2,8 GB su 48 | sotto il margine di 8 GiB indicato per Windows |
| Memoria di Strata | 37-39 GB in RAM, di cui 13,5 GB privati | circa 25 GB di esperti in RAM su 50: gli altri stanno tra scheda video e SSD |
| Log di Strata | `conversation cache: skip parking (… 271 MiB available …)` | la cache delle conversazioni non riesce a salvare: opencode e pi rileggono il prompt più spesso |
| Log di Strata | `route tail skip: … missed experts skipped` | gli esperti secondari non presenti sulla scheda video vengono saltati; la documentazione dice "Answers differ slightly" |
| Velocità su un testo breve ripetuto | 46-51 token/s | in linea con il riferimento: a caldo il modello è veloce |
| Una richiesta vera da 4.400 token | 732 token in 28,6 s | più lenta: entrano in gioco esperti non caricati |

Strata è avviato in modalità `--mmap-experts`: gli esperti sono mappati dai file e Windows può
riprendersi quella memoria quando un altro programma la chiede. Per questo il PC non si blocca
e il decision model di LLMWiki (1,35 GB) convive. Il prezzo è che ogni programma aperto toglie
esperti dalla RAM, e la pagina dei problemi di Strata descrive proprio questo caso: "the chosen
model exceeds the available RAM/VRAM and is using the file tier … pick a smaller model or size
(Q2_0 or IQ2_XS)".

## Passo 4: la scelta

### Oggi, con 48 GB: Qwen3.8-Flash-Next IQ2_XS

1. **Entra.** 45,5 GB richiesti su 48: restano liberi circa 12 GB invece di 2,8, per browser,
   editor, LLMWiki e la cache delle conversazioni di Strata.
2. **È già sul disco.** Nessuno scaricamento del modello.
3. **Stesso motore, stesso modello.** Strumenti, uscita strutturata e logprob restano quelli
   già provati con LLMWiki. Un solo modello serve LLMWiki, opencode e pi.
4. **È più veloce.** Sul PC di riferimento circa 1,5 volte IQ3_S (80 contro 52 token/s).
5. **Tra le due versioni che entrano è la migliore.** Strata classifica Q2_0 "good" e IQ2_XS
   "better".

Che cosa non si sa: quanto IQ2_XS perda rispetto a IQ3_S sul lavoro vero. Non c'è un numero
pubblicato per IQ2_XS, e il confronto non è alla pari, perché oggi IQ3_S gira con una parte
degli esperti saltata. Si misura (passo 5).

### Con 64 GB: IQ3_XXS per l'uso di tutti i giorni, IQ3_S a PC libero

| Versione | RAM che serve | Margine su 64 GB | Quando |
|---|---|---|---|
| IQ3_XXS | 53 GB | 11 GB | Con browser, editor e LLMWiki aperti |
| IQ3_S | 60 GB | 4 GB | Solo con poco altro aperto |

Con 64 GB conviene anche far tenere a Strata gli esperti in RAM invece di mapparli dai file
(`--resident-experts`: "Nothing is read from the SSD while it answers"). La documentazione
riporta un caso vicino a questo: scheda da 12 GB, PC da 63 GB, IQ3_S a 128K passato da 9,4 a
25-28 token/s con la copia in RAM. Nel profilo attuale questa opzione è spenta.

### Scartati

| Opzione | Perché no |
|---|---|
| Restare su IQ3_S con 48 GB | Fuori regola di 12 GB: RAM sempre piena, cache delle conversazioni ferma |
| IQ3_XXS con 48 GB | 53 GB richiesti: stesso problema, più piccolo |
| Q2_0 | Entra, ma è la versione di qualità più bassa e libera solo 1,5 GB in più di IQ2_XS |
| Coder IQ1_M | Più debole fuori dal codice e sui testi non inglesi: i documenti sono in italiano |
| Qwen3.6-35B-A3B in Strata | Su 12 GB gira in modalità ibrida a circa 59 token/s (misura su RTX 3060): più lento di IQ2_XS e più piccolo. Va scaricato |
| Un modello piccolo tutto nella scheda video (vedi sotto) | La scheda video è occupata da Strata (11,4 GB su 12) e Strata non serve altre famiglie di modelli: servirebbe un secondo programma e spegnere Strata ogni volta. L'ultimo avvio di Strata registrato è durato 1.008 secondi. Il guadagno sarebbe circa 90 token/s contro gli 80 di riferimento di IQ2_XS, con un modello da 9-12 miliardi di parametri al posto di uno molto più grande |

## Passo 5: verificare prima di decidere

La scelta è un'ipotesi finché non è misurata. Due prove, prima e dopo il cambio:

1. **LLMWiki.** Le 24 domande della raccolta difficile. Oggi con IQ3_S: 23 su 24, 102
   citazioni di cui 1 non confermata, 110 secondi di media, indice in 47 minuti.

   ```bash
   uv run python evals/run.py answers --config percorso/wiki.toml --suite difficile --fresh
   ```

2. **Uso con opencode e pi.** Qualche sessione di lavoro vero: lì il giudizio è di chi li usa.

Se IQ2_XS resta intorno a 22-23 su 24 con pochi ⚠ e tempi più bassi, è la scelta giusta per
48 GB. Se perde chiaramente, si torna a IQ3_S accettando la RAM piena fino all'arrivo dei 64 GB.

Per vedere che cosa farebbe Strata senza cambiare nulla:

```bash
strata launch --plan --model iq2_xs --context 128k
```

Il cambio vero si fa dalle schermate di `strata launch`, che nella scelta del modello dicono
per ogni versione "fits / tight / does not fit this computer" e permettono di rimettere le
impostazioni personali (cache delle conversazioni, riserva di memoria video). Il profilo
attuale ha la taratura saltata e una nuova taratura in sospeso dopo l'aggiornamento del motore:
la taratura rapida dura circa 20 minuti.

Dopo il cambio, in LLMWiki: Impostazioni → Modello → "Mostra i modelli disponibili", scegliere
il nuovo nome e "Salva e prova".

## Come rifare il conto

1. **Quanta RAM c'è**, e quanta ne usano gli altri programmi che restano aperti.
2. **Regola di Strata:** esperti + 10 GB ≤ RAM. Su Windows tenere 8 GB di margine.
3. **Tra le versioni che entrano, la più alta in qualità.**
4. **Contesto:** aggiungere 13,7 KB per token (1,7 GB a 128K).
5. **LLMWiki aggiunge** 1,35 GB per il decision model e poco altro.
6. **Misurare** con il banco di prova prima e dopo.

Applicato: 48 GB → IQ2_XS (45,5). 64 GB → IQ3_XXS (53) con margine, IQ3_S (60) a filo.
Per IQ3_S con il browser aperto servirebbero circa 72 GB.

## Per un PC senza Strata

Strata con Qwen3.8-Flash-Next richiede decine di GB di RAM. Per chi ha una scheda da 12 GB e
un PC normale, o per chi riceve LLMWiki e vuole un modello leggero, i candidati sono modelli
piccoli che stanno interi nella scheda video. Misure pubblicate su una RTX 3080 Ti:

| Modello | File | Memoria video a 32K | Velocità | Note |
|---|---|---|---|---|
| Gemma 4 12B, QAT Q4_0 | 6,5 GiB | 8,1 GB | 90 token/s | Prima scelta di tre guide su tre; chiamate a strumenti native; Apache 2.0 |
| Qwen3.5-9B, Q6_K | 7,0 GiB | 7,8 GB | 94 token/s | 201 lingue dichiarate; ragiona prima di rispondere; Apache 2.0 |
| Granite 4.2 8B, Q6_K | 6,7 GiB | non entra a 32K | 91 token/s | Solo fino a 16K con questa versione |

Ordine consigliato: Gemma 4 12B per primo, per l'affidabilità del formato delle chiamate;
Qwen3.5-9B come alternativa, per la copertura delle lingue. Servono con Ollama, LM Studio o
llama.cpp, che LLMWiki trova da solo.

**Non provati con LLMWiki e non provati in italiano.** Le misure vengono da una guida di un
produttore di software e non sono state riprodotte in modo indipendente. Prima di consigliarli
a qualcuno vanno passati dal banco di prova.

## Fonti

- Documentazione di Strata: [MODELS.md](https://github.com/Niko1221/Strata/blob/main/docs/MODELS.md),
  [DETAILS.md](https://github.com/Niko1221/Strata/blob/main/docs/DETAILS.md),
  [QUANTS.md](https://github.com/Niko1221/Strata/blob/main/docs/QUANTS.md),
  [QWEN36.md](https://github.com/Niko1221/Strata/blob/main/docs/QWEN36.md),
  [TROUBLESHOOTING.md](https://github.com/Niko1221/Strata/blob/main/docs/TROUBLESHOOTING.md)
- Misure sui modelli piccoli: [Atomic Chat, Best Local LLMs for 12GB VRAM](https://atomic.chat/blog/guides/best-local-llm-12gb)
  (30 settembre 2026)
- Licenze e dimensioni: [VDF AI, Best Local LLM by VRAM](https://vdf.ai/blog/best-local-llm-by-vram/)
  (6 ottobre 2026)
- Chiamate a strumenti di Gemma 4 12B: [Kilo, The Best Local Coding Models for Any Setup](https://blog.kilo.ai/p/the-best-local-coding-models-for)
  (29 luglio 2026)
- Misure su questo PC: `nvidia-smi`, memoria del processo, `strata status`, log di Strata, tre
  richieste a `/v1/chat/completions`.
