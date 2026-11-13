"""Raccolta di prova "difficile": documenti inventati ma realistici, molti dei quali quasi
identici tra loro (sedici contratti con la stessa struttura e numeri diversi). È il caso in cui
una wiki sbaglia più facilmente: trova il documento giusto solo se legge davvero, e una
citazione presa dal contratto sbagliato deve farsi notare.

I fatti sono generati con un seme fisso, quindi le risposte attese sono note: `build()` scrive i
documenti e restituisce le domande con ciò che la risposta deve contenere e citare.
"""

from __future__ import annotations

import random
from pathlib import Path

MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
          "settembre", "ottobre", "novembre", "dicembre"]
SUPPLIERS = [
    ("Acme Componenti S.p.A.", "valvole idrauliche serie VX-200"),
    ("Ferroli Meccanica S.r.l.", "alberi di trasmissione"),
    ("Tecnoplast Emilia S.r.l.", "carter in polimero rinforzato"),
    ("Idrosistemi Veneti S.p.A.", "pompe a ingranaggi"),
    ("Bulloneria Lombarda S.r.l.", "viteria ad alta resistenza"),
    ("Elettroforniture Adriatiche S.r.l.", "quadri elettrici di comando"),
    ("Gommaflex Italia S.p.A.", "tubi flessibili oleodinamici"),
    ("Officina Rinaldi S.n.c.", "lavorazioni di tornitura conto terzi"),
    ("Metalli Brenta S.p.A.", "barre in acciaio inox"),
    ("Pneumatica Estense S.r.l.", "cilindri pneumatici"),
    ("Cartotecnica Reno S.r.l.", "imballaggi in cartone ondulato"),
    ("Vernici Felsinee S.r.l.", "vernici epossidiche"),
    ("Trafilerie Apuane S.p.A.", "filo trafilato"),
    ("Molle Lariane S.r.l.", "molle a compressione"),
    ("Guarnizioni Ticino S.r.l.", "guarnizioni in PTFE"),
    ("Cuscinetti Dora S.p.A.", "cuscinetti a sfere"),
]
CITIES = ["Bologna", "Milano", "Torino", "Padova", "Verona", "Modena", "Parma", "Brescia"]
PEOPLE = ["ing. Carla Moretti", "dott. Paolo Ferri", "ing. Sara Lodi", "geom. Marco Tesi",
          "dott.ssa Elena Riva", "ing. Luca Berti", "p.i. Anna Gatti", "ing. Davide Sala"]
HR = [
    ("policy_ferie.md", "Policy ferie e permessi", ["Ogni dipendente matura 26 giorni di ferie all'anno.",
     "Le ferie vanno richieste sul portale HR con almeno 15 giorni di anticipo.",
     "Sono previste 32 ore annue di permesso retribuito."]),
    ("policy_smart_working.md", "Policy smart working", ["Sono consentiti fino a 2 giorni di lavoro da remoto a settimana.",
     "È previsto un rimborso forfettario di 30 euro al mese per la connessione.",
     "La fascia di reperibilità obbligatoria va dalle 10:00 alle 12:30."]),
    ("policy_trasferte.md", "Regolamento trasferte", ["Il rimborso chilometrico è di 0,45 euro al chilometro.",
     "Il limite di spesa per l'hotel è di 140 euro a notte.",
     "La nota spese va consegnata entro 10 giorni dal rientro."]),
    ("policy_straordinari.md", "Regolamento straordinari", ["Lo straordinario non può superare le 8 ore a settimana.",
     "Le ore di straordinario sono pagate con una maggiorazione del 25%.",
     "Lo straordinario va autorizzato per iscritto dal responsabile."]),
    ("policy_buoni_pasto.md", "Buoni pasto", ["Il buono pasto ha un valore di 8 euro.",
     "Spetta un buono per ogni giornata lavorata di almeno 6 ore.",
     "I buoni vengono caricati sulla tessera il giorno 5 di ogni mese."]),
    ("policy_formazione.md", "Piano di formazione", ["Ogni dipendente ha diritto a 40 ore annue di formazione.",
     "Il budget individuale per corsi esterni è di 1.200 euro all'anno.",
     "I corsi sulla sicurezza sono obbligatori e si tengono a marzo."]),
    ("policy_auto_aziendale.md", "Auto aziendale", ["In caso di sinistro con colpa è prevista una franchigia di 500 euro a carico del dipendente.",
     "Il chilometraggio annuo massimo è di 30.000 km.",
     "L'auto va restituita entro 5 giorni dalla cessazione del rapporto."]),
    ("policy_reperibilita.md", "Reperibilità tecnica", ["L'indennità di reperibilità è di 35 euro al giorno.",
     "L'intervento deve avvenire entro 60 minuti dalla chiamata.",
     "I turni di reperibilità durano una settimana, dal lunedì."]),
]
NOTES = [
    ("fisica/moto_uniformemente_accelerato.md", "Moto uniformemente accelerato",
     ["La legge oraria è s = s0 + v0·t + 1/2·a·t².", "La velocità cresce linearmente: v = v0 + a·t.",
      "In caduta libera l'accelerazione vale 9,81 m/s²."]),
    ("fisica/legge_di_ohm.md", "Legge di Ohm",
     ["La tensione ai capi di un resistore è V = R·I.", "La potenza dissipata è P = V·I = R·I².",
      "Due resistori in parallelo da 6 ohm equivalgono a 3 ohm."]),
    ("fisica/gas_perfetti.md", "Gas perfetti",
     ["L'equazione di stato è p·V = n·R·T.", "La costante dei gas vale R = 8,314 J/(mol·K).",
      "A temperatura costante vale la legge di Boyle: p·V = costante."]),
    ("fisica/onde.md", "Onde",
     ["La velocità di un'onda è v = λ·f.", "Il suono nell'aria a 20 °C viaggia a circa 343 m/s.",
      "Il periodo è l'inverso della frequenza: T = 1/f."]),
    ("diritto/contratto_requisiti.md", "Requisiti del contratto",
     ["I requisiti essenziali del contratto sono accordo, causa, oggetto e forma (art. 1325 c.c.).",
      "Il contratto è nullo se manca uno dei requisiti essenziali (art. 1418 c.c.).",
      "L'azione di nullità è imprescrittibile."]),
    ("diritto/prescrizione.md", "Prescrizione",
     ["La prescrizione ordinaria è di dieci anni (art. 2946 c.c.).",
      "Il diritto al risarcimento da fatto illecito si prescrive in cinque anni (art. 2947 c.c.).",
      "La prescrizione è interrotta dalla notifica dell'atto con cui si inizia un giudizio."]),
    ("diritto/clausola_penale.md", "Clausola penale",
     ["La clausola penale limita il risarcimento alla prestazione promessa (art. 1382 c.c.).",
      "La penale è dovuta indipendentemente dalla prova del danno.",
      "Il giudice può ridurre la penale manifestamente eccessiva (art. 1384 c.c.)."]),
    ("diritto/recesso_e_risoluzione.md", "Recesso e risoluzione",
     ["La risoluzione per inadempimento richiede un inadempimento di non scarsa importanza (art. 1455 c.c.).",
      "La diffida ad adempiere deve concedere un termine non inferiore a quindici giorni (art. 1454 c.c.).",
      "Il recesso unilaterale è ammesso solo se previsto dal contratto o dalla legge."]),
    ("economia/elasticita.md", "Elasticità della domanda",
     ["L'elasticità della domanda al prezzo è la variazione percentuale della quantità divisa per quella del prezzo.",
      "La domanda è elastica quando l'elasticità in valore assoluto è maggiore di 1.",
      "Con domanda anelastica un aumento di prezzo fa aumentare il ricavo totale."]),
    ("economia/punto_di_pareggio.md", "Punto di pareggio",
     ["Il punto di pareggio è la quantità Q = costi fissi / (prezzo − costo variabile unitario).",
      "Il margine di contribuzione unitario è prezzo meno costo variabile unitario.",
      "Esempio in aula: costi fissi 60.000 euro, prezzo 50, costo variabile 30: pareggio a 3.000 unità."]),
    ("economia/inflazione.md", "Inflazione",
     ["L'inflazione è l'aumento generalizzato e prolungato del livello dei prezzi.",
      "Il tasso reale è circa il tasso nominale meno l'inflazione attesa (equazione di Fisher).",
      "L'obiettivo della BCE è un'inflazione del 2% nel medio termine."]),
    ("economia/ammortamento.md", "Ammortamento",
     ["L'ammortamento a quote costanti divide il costo per la vita utile.",
      "Esempio: un macchinario da 80.000 euro con vita utile di 8 anni ha una quota annua di 10.000 euro.",
      "Il valore contabile netto è il costo storico meno il fondo ammortamento."]),
]


def _num(value: float) -> str:
    return str(value).replace(".", ",").removesuffix(",0")


def _alternatives(value: float, suffix: str = "%") -> str:
    text = _num(value)
    return f"{text}{suffix}|{text} {suffix}|{text.replace(',', '.')}{suffix}"


def _facts() -> dict:
    rng = random.Random(20261114)
    contracts = []
    for i, (supplier, product) in enumerate(SUPPLIERS):
        slug = supplier.split(" S.")[0].lower().replace(" ", "_")
        contracts.append({
            "supplier": supplier, "product": product, "slug": slug, "number": f"2026/{101 + i}",
            "day": rng.randint(2, 27), "month": rng.choice(MONTHS[:6]),
            "delivery": rng.choice([15, 20, 30, 45, 60]), "payment": rng.choice([30, 60, 90, 120]),
            "penalty": rng.choice([1, 1.5, 2, 2.5, 3, 4]), "cap": rng.choice([5, 8, 10, 12, 15]),
            "weeks": rng.choice([4, 5, 6, 8]), "duration": rng.choice([12, 24, 36]),
            "city": rng.choice(CITIES), "warehouse": rng.choice(["Imola", "Faenza", "Lugo", "Budrio"]),
            "sla": None,
        })
    for contract in rng.sample(contracts, 8):
        contract["sla"] = {
            "urgent": rng.choice([3, 5, 7, 10]), "surcharge": rng.choice([8, 10, 12, 15, 20]),
            "defects": rng.choice([0.2, 0.3, 0.5, 0.8, 1]), "response": rng.choice([4, 8, 12, 24]),
            "contact": rng.choice(PEOPLE),
        }
    minutes = []
    for i in range(12):
        target = contracts[(i * 5) % len(contracts)]
        minutes.append({
            "month": MONTHS[i], "day": rng.randint(3, 26), "supplier": target["supplier"],
            "cut": rng.choice([10, 15, 20, 25, 30]), "budget": rng.choice([18, 24, 35, 42, 60, 75]) * 1000,
            "project": rng.choice(["revisione della linea 2", "nuovo magazzino automatico", "certificazione ISO 14001",
                                   "sostituzione dei compressori", "gestionale di produzione", "impianto fotovoltaico"]),
            "chair": rng.choice(PEOPLE),
        })
    sales = []
    for i in range(8):
        year, quarter = 2025 + i // 4, i % 4 + 1
        sales.append({
            "year": year, "quarter": quarter, "revenue": round(rng.uniform(3.1, 5.4), 1),
            "growth": rng.choice([3, 4, 6, 7, 8, 9, 11]), "orders": rng.randint(900, 1900),
            "client": rng.choice(["Idrotecnica Rossi", "Meccanica Sarti", "Impianti Colli", "Gruppo Vanni"]),
        })
    return {"contracts": contracts, "minutes": minutes, "sales": sales}


def _contract_text(c: dict) -> str:
    annex = ("\nGli ordini urgenti seguono i tempi indicati nell'Allegato B (SLA)." if c["sla"] else "")
    return f"""# Contratto di fornitura n. {c['number']}

Tra Officine Bianchi S.r.l. ("Cliente") e {c['supplier']} ("Fornitore").
Firmato a {c['city']} il {c['day']} {c['month']} 2026. Durata: {c['duration']} mesi dalla firma.

## Art. 1 · Oggetto
Il Fornitore si impegna a fornire al Cliente {c['product']} secondo le specifiche
dell'Allegato A.

## Art. 7 · Consegne
La consegna avviene entro {c['delivery']} giorni dalla data dell'ordine, franco magazzino del
Cliente a {c['warehouse']}.{annex}

## Art. 8 · Pagamenti
Pagamento tramite bonifico bancario a {c['payment']} giorni dalla data della fattura.

## Art. 9 · Penali
In caso di ritardo nella consegna è prevista una penale del {_num(c['penalty'])}% del valore
dell'ordine per ogni settimana completa di ritardo, fino a un massimo del {c['cap']}%.
Oltre le {c['weeks']} settimane di ritardo il Cliente può risolvere il contratto.

## Art. 14 · Foro competente
Per ogni controversia è competente il Tribunale di {c['city']}.
"""


def _sla_text(c: dict) -> str:
    s = c["sla"]
    return f"""# Allegato B · Livelli di servizio (SLA) · {c['supplier']}

Allegato al contratto di fornitura n. {c['number']} con {c['supplier']}.

## 1. Ordini urgenti
Gli ordini marcati come urgenti vengono consegnati entro {s['urgent']} giorni lavorativi,
con un sovrapprezzo del {s['surcharge']}% sul prezzo di listino.

## 2. Qualità
Il tasso di difettosità accettato è dello {_num(s['defects'])}% per lotto.

## 3. Assistenza
Il Fornitore risponde alle segnalazioni tecniche entro {s['response']} ore lavorative.
Referente tecnico: {s['contact']}.
"""


def build(target: Path | None = None) -> list[dict]:
    """Scrive i documenti in `target` (se indicato) e restituisce le domande con le risposte attese."""
    facts = _facts()
    files: dict[str, str] = {}
    for c in facts["contracts"]:
        files[f"contratti/contratto_{c['slug']}.md"] = _contract_text(c)
        if c["sla"]:
            files[f"contratti/allegati/sla_{c['slug']}.md"] = _sla_text(c)
    for name, title, lines in HR:
        files[f"hr/{name}"] = f"# {title}\n\nValida per tutto il personale di Officine Bianchi S.r.l.\n\n" + "\n".join(lines) + "\n"
    for m in facts["minutes"]:
        number = MONTHS.index(m["month"]) + 1
        files[f"verbali/2026-{number:02d}_comitato_acquisti.md"] = f"""# Verbale del comitato acquisti · {m['day']} {m['month']} 2026

Presiede {m['chair']}.

## Decisioni
1. Gli ordini a {m['supplier']} vengono ridotti del {m['cut']}% nel trimestre successivo.
2. È approvato un budget di {m['budget']:,} euro per il progetto "{m['project']}".
3. Il responsabile acquisti riferirà sull'andamento alla prossima riunione.
""".replace(",000", ".000")
    for s in facts["sales"]:
        files[f"vendite/report_{s['year']}_q{s['quarter']}.md"] = f"""# Report vendite · trimestre {s['quarter']} del {s['year']}

Il fatturato del trimestre è stato di {_num(s['revenue'])} milioni di euro, in crescita del {s['growth']}%
rispetto allo stesso trimestre dell'anno precedente. Gli ordini evasi sono stati {s['orders']}.
Il primo cliente per fatturato è stato {s['client']}.
"""
    for path, title, lines in NOTES:
        files[f"appunti/{path}"] = f"# {title}\n\nAppunti di lezione.\n\n" + "\n".join(f"- {line}" for line in lines) + "\n"
    if target is not None:
        for relative, text in files.items():
            file = target / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text, encoding="utf-8")

    contracts, minutes, sales = facts["contracts"], facts["minutes"], facts["sales"]
    with_sla = [c for c in contracts if c["sla"]]

    def doc(c: dict) -> str:
        return f"contratti/contratto_{c['slug']}.md"

    def name(c: dict) -> str:
        return c["supplier"].split(" S.")[0]

    questions = []
    for c in (contracts[1], contracts[6], contracts[11]):
        questions.append({"question": f"Qual è la penale per ritardo nel contratto con {name(c)} e qual è il tetto massimo?",
                          "must_contain": [_alternatives(c["penalty"]), _alternatives(c["cap"])], "must_cite": [doc(c)]})
    for c in (contracts[3], contracts[13]):
        questions.append({"question": f"A quanti giorni dalla fattura si paga {name(c)}?",
                          "must_contain": [f"{c['payment']} giorni"], "must_cite": [doc(c)]})
    for c in (contracts[8], contracts[15]):
        questions.append({"question": f"Entro quanti giorni deve consegnare {name(c)} e in quale magazzino?",
                          "must_contain": [f"{c['delivery']} giorni", c["warehouse"]], "must_cite": [doc(c)]})
    c = contracts[5]
    questions.append({"question": f"Quale tribunale è competente per le controversie con {name(c)} e quanto dura il contratto?",
                      "must_contain": [c["city"], f"{c['duration']} mesi"], "must_cite": [doc(c)]})
    for c in with_sla[:3]:
        questions.append({"question": f"Con {name(c)}, in quanti giorni arrivano gli ordini urgenti e con quale sovrapprezzo?",
                          "must_contain": [f"{c['sla']['urgent']} giorni", _alternatives(c["sla"]["surcharge"])],
                          "must_cite": [f"contratti/allegati/sla_{c['slug']}.md"]})
    c = with_sla[4]
    questions.append({"question": f"Chi è il referente tecnico di {name(c)} e entro quante ore risponde alle segnalazioni?",
                      "must_contain": [c["sla"]["contact"].split()[-1], f"{c['sla']['response']} ore"],
                      "must_cite": [f"contratti/allegati/sla_{c['slug']}.md"]})
    questions += [
        {"question": "Quanto vale il rimborso chilometrico in trasferta e qual è il limite per l'hotel?",
         "must_contain": ["0,45", "140"], "must_cite": ["hr/policy_trasferte.md"]},
        {"question": "Con quale maggiorazione sono pagati gli straordinari e qual è il limite settimanale?",
         "must_contain": ["25%|25 %", "8 ore"], "must_cite": ["hr/policy_straordinari.md"]},
        {"question": "Di quanto è l'indennità di reperibilità e in quanto tempo bisogna intervenire?",
         "must_contain": ["35 euro", "60 minuti"], "must_cite": ["hr/policy_reperibilita.md"]},
    ]
    for m in (minutes[2], minutes[7], minutes[10]):
        number = MONTHS.index(m["month"]) + 1
        questions.append({"question": f"Cosa ha deciso il comitato acquisti di {m['month']} 2026 sugli ordini e sul budget?",
                          "must_contain": [_alternatives(m["cut"]), f"{m['budget'] // 1000}.000|{m['budget']}"],
                          "must_cite": [f"verbali/2026-{number:02d}_comitato_acquisti.md"]})
    for s in (sales[1], sales[6]):
        questions.append({"question": f"Qual è stato il fatturato del trimestre {s['quarter']} del {s['year']} e chi è stato il primo cliente?",
                          "must_contain": [_num(s["revenue"]) + "|" + str(s["revenue"]), s["client"]],
                          "must_cite": [f"vendite/report_{s['year']}_q{s['quarter']}.md"]})
    questions += [
        {"question": "Nei miei appunti, in quanti anni si prescrive il diritto al risarcimento da fatto illecito?",
         "must_contain": ["cinque anni|5 anni"], "must_cite": ["appunti/diritto/prescrizione.md"]},
        {"question": "Negli appunti di economia, come si calcola il punto di pareggio e quanto vale nell'esempio fatto in aula?",
         "must_contain": ["3.000|3000"], "must_cite": ["appunti/economia/punto_di_pareggio.md"]},
        {"question": "Quanto vale la costante dei gas negli appunti di fisica?",
         "must_contain": ["8,314|8.314"], "must_cite": ["appunti/fisica/gas_perfetti.md"]},
        {"question": "Cosa prevedono i documenti sul premio di produzione annuale?",
         "must_contain": ["non"], "must_cite": [], "unanswerable": True},
    ]
    return questions
