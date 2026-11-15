# Tutorial — FS-MetaPostDiag

Guida pratica in tre parti:

- **Parte 1** — analizzare **un singolo caso** (GUI o riga di comando)
- **Parte 2** — estrarre **molte analisi** in blocco (quello che serve per il dataset)
- **Parte 3** — leggere i risultati e cosa fare dopo

---

# Parte 1 — Un singolo caso

## Cosa serve

- Windows 10/11 64-bit
- `FS-MetaPostDiag.exe` (dalla release)
- I file `.cas` e `.dat` **nella stessa cartella**
- META Post **non** è obbligatorio (serve solo per la sessione interattiva)

## Dalla GUI

1. Doppio clic su `FS-MetaPostDiag.exe`.
2. **Sorgente CFD** → `Stoglia` → scegli la cartella con `.cas` e `.dat`.
   I due indicatori devono diventare **verdi** ("File .cas trovato", "File .dat trovato").
3. **Assieme da isolare**: `Undertray` per il fondo, `Full car` per tutta la vettura.
4. **Analizza .CAS**: compare il numero di PID e, nella card **PID nel computo**, l'elenco delle zone wall.
   - se vuoi che il calcolo usi esattamente le zone del tuo report Fluent, spunta quelle e premi **Avvia**;
   - **Automatico** ripristina la selezione per keyword.
5. **Esecuzione META**: velocità `14` m/s (quella delle simulazioni), densità `1.225`.
6. **AVVIA POST-PROCESSING**. La console mostra le fasi e i controlli `CHK-01 … CHK-07`.
7. Alla fine: `output_diagnostics\CFD_Aero_Diagnostic_Report.html` (report completo) e `Report_CFD_<cas>_<assieme>.html` accanto al `.cas` (copia apribile senza la cartella).

## Da riga di comando

```powershell
$env:TEMP = "C:\temp\fs"          # dove PyInstaller estrae (serve spazio)
.\FS-MetaPostDiag.exe -w "D:\Analisi\Venturi\analisi 1" -a full_car --no-meta-batch
.\FS-MetaPostDiag.exe --version
```

Opzioni utili:

| Opzione | Significato |
|---|---|
| `-w`, `--workspace` | cartella con `.cas`/`.dat` |
| `-a`, `--assembly` | `auto`, `undertray`, `front_wing`, `rear_wing`, `full_car` |
| `--no-meta-batch` | non avviare META: solo motore Python (consigliato sui PC senza META) |
| `-c`, `--config` | `config.yaml` alternativo |
| `--open-report` | apre il report alla fine |
| `--ai-key`, `--ai-provider` | perizia AI Vision (chiave non salvata su disco) |
| `--ai-check` | verifica la configurazione AI ed esce |

## Come capire se è andata bene

- tutti i controlli `CHK-01…CHK-07` in `[PASS]`;
- **CHK-07**: "somma PID = KPI" (deportanza e drag);
- 24 immagini generate e verificate (CHK-06);
- nel report, i KPI in alto e la tabella per PID.

---

# Parte 2 — Estrazione in blocco

Serve per elaborare decine di analisi senza guardarle una per una.

## 2.1 Cosa mettere sul PC remoto

Una cartella, per esempio `C:\FS-MetaPostDiag\`, con dentro:

```
FS-MetaPostDiag.exe          <- l'applicazione (stessa versione per tutti i casi)
01_Estrai_tutti.bat
02_Tabelle_e_controlli.bat
batch_extract.py
make_tables.py
check_dataset.py
LEGGIMI.txt
TUTORIAL.md                  <- questo file
```

Serve **Python 3.8 o superiore** (da python.org, spuntando *"Add python.exe to PATH"*).
Verifica con:

```powershell
python --version
```

## 2.2 Come disporre le analisi

Non serve rinominare nulla: **una cartella per caso**, con dentro il suo `.cas` e `.dat`. Le sottocartelle possono essere annidate come vuoi.

```
D:\Analisi\
    Venturi\
        analisi 1\
            V14_3.cas                  <- file di partenza: SCARTATO
            V14_3.dat
            V14_3-1-01250.cas          <- file delle iterazioni: USATO
            V14_3-1-01250.dat
        analisi 2\
            V14_5-1-01250.cas
            V14_5-1-01250.dat
```

### Quali file vengono usati

| Nome | Esito |
|---|---|
| `V14_3-1-01250.cas` / `.dat` | **usato** (`<nome>-<iterazione>-<id>`) |
| `V14_3.cas` / `.dat` | **scartato** (file di partenza) |
| `nome_1_iterazioni.cas` | usato (contiene "iterazion") |

Se in una cartella ci sono entrambi, la coppia iterata viene isolata in una sottocartella temporanea `_solo_iterazioni` (hardlink: nessuna copia dei GB) e cancellata a fine corsa. I file di partenza non vengono toccati.

Regola diversa? `--iter-keyword "iterazion|finale"`. Vuoi forzare tutto? `--include-all`.

## 2.3 Prima prova: solo l'elenco

1. Doppio clic su **`01_Estrai_tutti.bat`**.
2. Trascina sulla finestra la **cartella radice** (es. `D:\Analisi`) e premi Invio.
3. Assieme: premi Invio per `full_car` (consigliato: conserva il dettaglio di tutti i PID).
4. "Prima solo l'elenco dei casi trovati?": rispondi **`s`**.

Ottieni qualcosa così:

```
Cartelle trovate: 3
Da elaborare: 2 | scartate (solo file di partenza): 1

  OK        Venturi__analisi_1   V14_3-1-01250.cas + V14_3-1-01250.dat  (isolato)
  OK        Venturi__analisi_2   V14_5-1-01250.cas + V14_5-1-01250.dat  (in_place)
  SCARTATO  Venturi__analisi_3   nessun file di iterazione riconosciuto (cas: V14_7.cas | dat: V14_7.dat)
```

**Controlla questo elenco prima di partire**: nomi dei casi, file scelti, cartelle scartate.

## 2.4 Estrazione vera

Rilancia `01_Estrai_tutti.bat` come sopra ma rispondi **`N`** (o Invio) a "solo elenco". Per ogni caso:

```
[1/2] Venturi__analisi_1   avvio (isolato)...
      -> OK  122 s  dep 483.1 N | drag 222.7 N | 43 PID
```

- circa **2 minuti per caso**;
- puoi interrompere con `Ctrl+C` e rilanciare: i casi già fatti vengono **saltati**;
- un caso rotto non ferma gli altri: finisce in `run_summary.txt` con il motivo;
- gli HTML da ~80 MB e `output_diagnostics` vengono cancellati dopo ogni caso.

Tempo indicativo: 30 casi ≈ 1 ora, 100 casi ≈ 3 ore e mezza.

## 2.5 Compilare `metadata.csv`

Nella cartella dei risultati trovi `metadata.csv`, una riga per caso:

```csv
case_id;nota;velocita_nominale_ms;parametro_1;parametro_2;parametro_3;parametro_4
Venturi__analisi_1;diffusore +2 gradi;14;2;;;; 
```

- `nota`: cosa hai cambiato, a parole tue (utile anche se impreciso);
- `velocita_nominale_ms`: la velocità della simulazione;
- `parametro_1..4`: rinomina le intestazioni con i parametri veri (es. `angolo_diffusore_deg`) e riempi.
- Se un valore non lo sai, **lascia vuoto**: meglio un buco che un numero inventato.

## 2.6 Tabelle e controlli

Doppio clic su **`02_Tabelle_e_controlli.bat`** (usa l'ultima cartella, oppure trascinaci sopra `_dati_batch`).
Produce:

| File | Contenuto |
|---|---|
| `dataset.csv` | una riga per caso: deportanza, drag, CL, CD, CL·A, CD·A, L/D, CoP, stallo, Cp_min, file usati, più le tue colonne di `metadata.csv` |
| `dataset_pid.csv` | una riga per PID: forze 1x/2x, pressione/viscosa, area, Cp, stallo |
| `_controlli.txt` | esito dei controlli di coerenza |
| `index.csv` | elenco dei casi, stato, secondi, file usati |

---

# Parte 3 — Leggere i risultati

## I controlli (`_controlli.txt`)

| Messaggio | Significato |
|---|---|
| "Tutto coerente" | i casi sono confrontabili, si può procedere |
| velocità diverse | le **forze** non sono confrontabili: usa `CL_A` e `CD_A` |
| PID per caso diverso | mesh o selezione zone diverse: controlla quel caso |
| somma PID ≠ KPI | il caso ha un problema di calcolo: guarda il log |
| simmetria half-car incoerente | un caso è full-car e un altro half-car: non mescolarli |
| selezione manuale dei PID | la GUI aveva dei PID spuntati: deve essere uguale per tutti |

## Come ordinare i casi

In `dataset.csv`:

- **deportanza** (`deportanza_N`) per il carico verticale;
- **L/D** (`L_D`) per l'efficienza;
- `CL_A`, `CD_A` se le velocità sono diverse (coefficienti, indipendenti da v);
- `cop_x_pct` / `cop_passo_pct` per il bilanciamento.

Il "migliore" dipende da cosa vuoi: massimizzare la deportanza, o l'efficienza, con il CoP in una finestra. Il `dataset.csv` ti dà i numeri, la scelta è tua.

## Verifica di sanità (consigliata su 2-3 casi)

Accanto ai conteggi Fluent, i nostri numeri devono coincidere entro ~1%:

- Fluent: report *Forces*, direzione `(0 -1 0)` per la deportanza e `(1 0 0)` per il drag, somma delle zone;
- nostro: `deportanza_N` e `drag_N` in `dataset.csv`;
- attenzione: il report Fluent ha una riga `Net` che è già il totale; sommare tutte le righe raddoppia.

---

# Parte 4 — Problemi comuni

| Sintomo | Cosa fare |
|---|---|
| `Python 3 non trovato` | installa Python 3.8+ da python.org con "Add python.exe to PATH", oppure copia una installazione portatile accanto agli script |
| `eseguibile non trovato` | metti `FS-MetaPostDiag.exe` accanto agli script o indica il percorso; se Windows l'ha bloccato: `Unblock-File .\FS-MetaPostDiag.exe` |
| `Could not create temporary directory` | il temporaneo non è scrivibile/pieno: `set TEMP=D:\temp` e rilancia, o sposta l'exe fuori da cartelle di rete/protette |
| Tutte le cartelle `SCARTATO` | i nomi non rientrano nella regola: controlla con l'elenco (`s`), poi usa `--iter-keyword` o `--include-all` |
| Un caso `ERRORE` | apri `<caso>.log`: c'è la riga `[FAIL]` o l'eccezione; sistemato il caso, rilancia (verrà rieseguito, gli altri vengono saltati) |
| `AMBIGUO` | nella cartella c'erano più iterazioni: è stata usata la più recente; se non è quella giusta, metti solo la coppia corretta in una cartella |
| Disco pieno | durante il caso servono ~300 MB liberi; i risultati occupano ~200 KB per caso |
| Estrazione lentissima | chiudi altri programmi pesanti; ogni caso usa diversi GB di RAM, **non lanciare due estrazioni insieme** |
| Antivirus che rallenta | escludi la cartella dei risultati e quella degli script dalla scansione in tempo reale |

---

# Parte 5 — Riferimento rapido

```powershell
# un caso
.\FS-MetaPostDiag.exe -w "D:\Analisi\Venturi\analisi 1" -a full_car --no-meta-batch

# elenco delle cartelle e dei file che verrebbero usati, senza eseguire
python batch_extract.py --root "D:\Analisi" --exe .\FS-MetaPostDiag.exe --dry-run

# estrazione completa
python batch_extract.py --root "D:\Analisi" --exe .\FS-MetaPostDiag.exe --assembly full_car

# solo alcune cartelle (filtro sul nome del caso)
python batch_extract.py --root "D:\Analisi" --case-filter Venturi

# tabelle e controlli
python make_tables.py   --data "D:\Analisi\_dati_batch"
python check_dataset.py --data "D:\Analisi\_dati_batch"

# rieseguire anche i casi già fatti
python batch_extract.py --root "D:\Analisi" --force

# tenere anche le immagini/HTML (occupa molto spazio)
python batch_extract.py --root "D:\Analisi" --keep-output --keep-reports
```

## Ordine di lavorazione consigliato

1. `--dry-run` → controlla elenco e file scelti;
2. 2-3 casi → verifica i numeri contro Fluent;
3. tutti i casi (anche di notte);
4. `metadata.csv` con i parametri;
5. `02_Tabelle_e_controlli.bat` → `_controlli.txt`;
6. se i controlli sono puliti, il dataset è pronto per l'analisi.

## Cosa conservare e cosa dare via

Conserva **`_dati_batch`** (JSON + log + CSV + `_controlli.txt`): per 100 casi sono ~20 MB.
I `.cas`/`.dat` non servono per l'analisi del dataset: servono solo se vuoi rigenerare un caso.
