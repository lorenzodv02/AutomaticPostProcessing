# FS-MetaPostDiag — Suite Post-Processing CFD & Diagnostica Design Aerodinamica

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey.svg)]()
[![CFD Support](https://img.shields.io/badge/CFD-ANSYS%20Fluent%20(.cas%20%2F%20.dat)-orange.svg)]()
[![Post-Processor](https://img.shields.io/badge/Post--Processor-BETA%20CAE%20META-red.svg)]()
[![Version](https://img.shields.io/badge/version-1.16.0-blue.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

Suite completa in Python progettata per l'automazione ad alte prestazioni del **post-processing CFD** e della **diagnostica fluidodinamica** per monoposto **Formula Student** e vetture da competizione. 

Supporta file binari nativi di **ANSYS Fluent** (`.cas`/`.dat` e `.h5`) e si interfaccia in modalità headless/batch con **BETA CAE META Post v23/v24/v25+**. Include inoltre un **motore grafico di fallback autonomo** a bassissimo consumo di memoria, in grado di estrarre e visualizzare la mesh 3D reale e generare l'intero dossier diagnostico su qualsiasi PC, anche privo di BETA CAE META installato.

---

## 🌟 Caratteristiche Principali

- **Scompattazione Binaria Diretta (.cas/.dat)**:
  Parser multi-sezione ad alte prestazioni con memory-mapping (`mmap`) per la lettura immediata di coordinate nodali 3D, triangoli/quad delle superfici di parete, campi scalari ($C_p$, Pressione Statica, $k$, $\tau_{w,x}$, Velocità $V$).
- **Computo Forze e Resistenza Viscosa Rigorosi**:
  Integrazione algebrica reale delle forze verticali ($F_y$) e longitudinali ($F_x$). Computa e scorpora la componente di **pressione** e la componente **viscosa** (attrito di parete), allineandosi con esattezza decimale ai monitor di ANSYS Fluent.
- **Rilevamento Fisico dello Stallo e Separazione dello Strato Limite**:
  Calcolo dello sforzo di taglio longitudinale a parete $\tau_{w,x} = -F_{v,x} / \text{Area}$. Identifica le reali aree di ricircolo e distacco ($\tau_{w,x} \le 0$) su flap, diffusori e ruote scoperte, evitando falsi allarmi globali.
- **Conformità e Standardizzazione Grafica $C_p \in [-3.0, +1.0]$**:
  Tutti i grafici dei profili alari, le mappe di contorno 2D/3D, le colorbar e i tagli trasversali e longitudinali adottano una scala fissa e coerente $[-3.0, +1.0]$ per consentire confronti visivi immediati tra diverse iterazioni aerodinamiche.
- **10 Sezioni Trasversali (X-Cuts) & 10 Longitudinali (Z-Cuts)**:
  Sezioni progressive a proporzioni reali 1:1 (senza distorsione d'aspetto) per seguire lo sviluppo dei vortici del fondo, l'espansione nel diffusore e le scie delle ruote.
- **Sweep Dinamico GIF Animata**:
  Generazione automatica di una GIF ad alta risoluzione (`10_cp_xcut_progressive_sweep.gif`) che mostra l'evoluzione continua della pressione statica e totale dall'anteriore al posteriore della vettura.
- **Visualizzazione Streamline 3D da 5 Angolazioni**:
  Viste assonometriche 3D, dall'alto, laterale, inferiore e posteriore per esaminare la scia e l'upwash.
- **Dossier Interattivo HTML Standalone "All-in-One"**:
  Report autoportante con visualizzatore a schede delle 32 immagini, grafici vettoriali, tabelle per PID e audit di conformità. Tutti gli asset sono incorporati in **Base64**: il file `.html` può essere condiviso ovunque via email, cloud o Teams senza cartelle allegate.
- **Esportazione Excel Integrata (.xlsx x2)**:
  Tabelle per singolo PID con ordinamento alfabetico, computo simmetrico raddoppiato ($x2$), efficienza $L/D$, drag viscoso/pressione e bounding box.
- **AI Vision Advisor Avanzato**:
  Integrazione euristica e supporto per modelli multimodali (incluso il supporto a `gemini-3.8-flash` e OpenAI) per la diagnosi visiva e suggerimenti di modifica CAD.
- **Architettura Ultra-Leggera con Safe Rendering**:
  Algoritmo di subsampling intelligente che preserva il 100% dei dettagli sui componenti sottili ($\le 800$ triangoli) e campiona le grandi superfici, azzerando i picchi di RAM e prevenendo categoricamente `MemoryError` anche su laptop con poca memoria.

---

## 🚀 Guida Rapida all'Installazione

### Requisiti di Sistema
- **Sistema Operativo**: Windows 10 / 11 (64-bit) o Linux
- **Python**: 3.10 o versioni superiori (testato su Python 3.10, 3.11, 3.12, 3.13)
- *(Opzionale)* **BETA CAE META Post**: se installato nei percorsi predefiniti (`%LOCALAPPDATA%\Apps\BETA_CAE_Systems\...` o `Program Files`), la suite lo rileva automaticamente. Se non presente, la suite opera al 100% tramite il suo motore Python autonomo.

---

### Step 1: Clonare il repository ed entrare nella cartella
```bash
git clone https://github.com/lorenzodv02/AutomaticPostProcessing.git
cd AutomaticPostProcessing
```

---

### Step 2: Installare le dipendenze Python

Su **Windows** (1-Click):
> Fai doppio click su **`install_dependencies.bat`**

Oppure manualmente da terminale:
```bash
pip install -r requirements.txt
python main.py --version      # FS-MetaPostDiag 1.16.0
```

Le librerie richieste sono:
- `numpy`, `scipy`, `matplotlib`, `Pillow`, `PyYAML`, `opencv-python`
- *(Opzionali per AI Vision Advisor)*: `google-genai`, `openai`

---

## 🖥️ Utilizzo

### Modalità 1: Interfaccia Grafica Desktop (GUI)
Ideale per l'utilizzo interattivo quotidiano.

> Fai doppio click su **`run_gui.bat`**  
*(oppure esegui:* `python main.py --gui`*)*

Dall'interfaccia puoi:
1. Sfogliare e selezionare la cartella contenente i file CFD (`.cas` e `.dat`).
2. Selezionare l'assieme aerodinamico desiderato:
   - `auto` *(Rilevamento intelligente dei PID)*
   - `full_car` *(Monoposto completa con ruote e pilota)*
   - `undertray` *(Fondo piatto, canali Venturi e diffusore)*
   - `front_wing` *(Ala anteriore, profili flap ed endplate)*
   - `rear_wing` *(Ala posteriore, beam wing e piloni)*
3. Configurare velocità $V_\infty$, densità dell'aria $\rho$ e visualizzare l'anteprima.
4. Cliccare su **"ESEGUI POST-PROCESSING META & GENERA REPORT DIAGNOSTICO"**.

---

### Modalità 2: Esecuzione Rapida da Riga di Comando (CLI)

Per elaborare una cartella specifica (es. `F:\FW5`) su vettura completa e aprire automaticamente il report al termine:
```bash
python main.py -w "F:\FW5" -a full_car --open-report
```

Opzioni disponibili da linea di comando:
```
python main.py [OPZIONI]

Opzioni:
  -w, --workspace PATH      Cartella contenente i file .cas e .dat (default: cartella corrente)
  -c, --config PATH         Percorso del file config.yaml
  -a, --assembly TIPO       Assieme target: auto, undertray, front_wing, rear_wing, full_car
  --no-meta-batch           Disabilita l'avvio batch di META Post ed usa solo il motore Python
  --ai-model MODELLO        Modello AI Vision Advisor (default: gemini-3.8-flash)
  --open-report             Apre automaticamente il report HTML nel browser al termine
  --gui                     Avvia l'interfaccia grafica Desktop
```

---

## 📁 Struttura del Progetto

```
AutomaticPostProcessing/
├── main.py                          # Entry point CLI ed orchestratore della pipeline
├── gui_app.py                       # Applicazione Desktop GUI completa (Tkinter)
├── config_bridge.py                 # Ponte unico config.yaml <-> codice (keyword, soglie, tagli, cp_range)
├── config.yaml                      # Configurazione parametri fisici, soglie e percorsi
├── requirements.txt                 # Dipendenze Python
├── install_dependencies.bat         # Launcher Windows 1-click installazione librerie
├── run_gui.bat                      # Launcher Windows 1-click interfaccia grafica
├── run_diagnostics.bat              # Launcher Windows 1-click post-processing rapido
├── README.md                        # Documentazione tecnica del progetto
│
├── meta_driver/                     # Motore di Parsing CFD e Driver BETA CAE META
│   ├── fluent_parser.py             # Parser binario avanzato per .cas, .dat e .h5
│   ├── launcher.py                  # Generazione 32 viste, sezioni X/Z, GIF e streamline
│   ├── ses_generator.py             # Generatore script di automazione META (.ses)
│   └── meta_post_worker.py          # Script worker interno per l'ambiente BETA CAE
│
├── analyzer/                        # Diagnostica Aerodinamica e Vision Advisor
│   ├── aero_plots.py                # Generazione grafici quantitativi Cp(x), CL(z), Drag
│   ├── ai_vision_advisor.py         # Motore euristico e interfaccia Vision AI (Gemini/OpenAI)
│   ├── assembly_rules.py            # Regole e soglie ingegneristiche per ogni assieme
│   ├── image_diagnostics.py         # Analisi contour e annotazione anomalie visive
│   └── verifier.py                  # Validazione coerenza sessioni e controlli di conformità
│
└── reporting/                       # Builder Report Interattivo ed Esportatore Dati
    └── report_builder.py            # Generatore HTML Standalone (Base64) ed Excel (.xlsx)
│
└── tests/                           # Test automatizzati (parser, config, soglie)
    ├── fixtures.py                  # Genera un .cas/.dat minimo con attese calcolate a mano
    ├── test_parser_synthetic.py     # End-to-end: aree, forze, Cp, tau, fonte del dato viscoso
    ├── test_config_bridge.py        # Le chiavi di config.yaml devono essere davvero lette
    ├── test_rules_thresholds.py     # Severita' della diagnosi guidata dalle soglie
    └── run_tests.py                 # Runner senza dipendenze (python tests/run_tests.py)
```

---

## 📐 Convenzioni Assi & Segni Fluidodinamici

| Asse | Orientamento | Significato Aerodinamico |
| :---: | :---: | :--- |
| **X** | Verso il retrotreno | Asse longitudinale. Flusso indisturbato diretto lungo $+X$. Resistenza (Drag) $> 0$. |
| **Y** | Verso l'alto | Asse verticale. Quota dal suolo. La **deportanza (Downforce)** spinge verso il basso ($-Y$). Componenti portanti come il casco pilota hanno $+Y$. |
| **Z** | Verso sinistra/destra | Asse trasversale / Spanwise. $Z = 0$ rappresenta il piano di simmetria longitudinale del veicolo. |

- **Computo Half-Car $\times 2$**: Se il modello CFD analizzato è simmetrico ($Z \le 0$ con simmetria a $Z=0$), il software raddoppia automaticamente le forze per rappresentare la vettura intera.
- **Sforzo di Taglio Longitudinale**: $\tau_{w,x} > 0$ indica strato limite attaccato; $\tau_{w,x} \le 0$ indica separazione e stallo.

---

## 📄 Output Generati

Al termine dell'elaborazione, nella cartella di lavoro contenente i file CFD vengono salvati:
1. `Report_CFD_<nome_file>_<assieme>.html`: Dossier interattivo completo navigabile da qualsiasi browser senza dipendenze esterne.
2. `Tabella_PID_Aerodinamica_2x.xlsx`: Foglio di calcolo nativo Excel con scomposizione per PID di Downforce, Drag (Pressione + Viscosa), Stallo e Bounding Box.
3. `output_diagnostics/`: Cartella con tutte le 32 immagini ad alta risoluzione, grafici aerodinamici e file `.ses` interattivo per aprire la sessione in META Post.

---

## ⚙️ Configurazione: cosa è davvero collegato

La configurazione è letta da `config_bridge.py`: **non ci sono più valori duplicati o chiavi finte**.

| Chiave di `config.yaml` | Effetto reale |
| --- | --- |
| `project.workspace_dir` / `output_dir` / `assembly_type` | cartelle e assieme di default |
| `reference_values.*` | integrali di forza e coefficienti (`reference_area` serve a CL e CD) |
| `meta.*` | esecuzione META Post e risoluzione immagini |
| `assemblies.<t>.pid_keywords` / `exclude_keywords` | filtro dei PID (si **sommano** al fallback storico) |
| `assemblies.<t>.x_cuts_normalized` / `z_cuts_normalized` | stazioni delle sezioni disegnate (valori > 1.0 scartati) |
| `assemblies.<t>.thresholds` | severità della diagnosi (stallo, Cp, asimmetria, vortici) |
| `assemblies.<t>.cp_range` | scala colore del Cp |
| `ai_vision.*` | commento AI opzionale |

Restano nel file solo come **documentazione** (nessun codice le legge): `coordinate_system`, `fluent_variables`, `wheelbase`.
Sono state rimosse le chiavi inutilizzate `y_cuts_normalized` e `primary_suction_view`.

> **Nota sulle stazioni.** `x_cuts_normalized` / `z_cuts_normalized` governano le *sezioni renderizzate*. La griglia di campionamento dei KPI lungo X resta canonica a 10 stazioni: i numeri restano così confrontabili anche cambiando i tagli.

## 🧪 Test automatici

```bash
python tests/run_tests.py      # nessuna dipendenza oltre numpy + PyYAML
# oppure, con pytest installato:
pip install -r requirements-dev.txt && pytest -q
```

I test costruiscono un caso Fluent **sintetico** (`.cas`/`.dat` minimi, 4 nodi, 3 triangoli) con valori calcolati a mano. Coprono il punto più fragile del progetto: il parser può sbagliare gli offset in silenzio e falsare ogni numero del report.

| Test | Cosa garantisce |
| --- | --- |
| `test_parser_synthetic.py` | lettura zone/nodi/facce, aree, normali, Cp, `tau_w,x`, scomposizione drag, fonti viscose, convenzione di segno |
| `test_config_bridge.py` | le chiavi di `config.yaml` sono lette davvero; i PID del modello restano selezionati |
| `test_rules_thresholds.py` | le soglie cambiano davvero la severità della diagnosi |

La CI (`.github/workflows/ci.yml`) li esegue su Python 3.10, 3.12 e 3.13 a ogni push e pull request.

## 🧭 Convenzione di segno (dichiarata nel codice)

Le normali delle facce puntano dal vicino `c0` (fluido) al vicino `c1` (parete), quindi la forza del fluido sulla parete è `F = p_rel · A · n`:

- i campi `downforce_*` riportano la **risultante verticale con segno** (negativa = spinta verso il basso);
- `vertical_force_y_N` è l'alias esplicito della stessa grandezza;
- i campi `drag_*` riportano il modulo, sempre ≥ 0.

La definizione completa è in `fluent_parser.SIGN_CONVENTION_NOTE` ed è verificata da `tests/test_parser_synthetic.py::test_forces_follow_the_documented_convention`.

## 🛠️ Licenza

Questo progetto è distribuito sotto licenza **MIT**. Consulta il file `LICENSE` per ulteriori dettagli.

---

## 📝 Changelog

### v1.16.0 — Geometria di ogni assieme, non solo il fondo

Il fondo era solo il primo assieme provato, non l'unico importante:

- **`meta_driver/geometry.py`**: descrittori di **tutte** le zone aero e, per ogni assieme, le misure che contano — fondo (profilo, altezza minima, salita, espansione), **ali** (apertura, corda media, area in pianta, allungamento), superfici per famiglia. Funziona anche su un full car: le ali si leggono dalle zone `front_*`/`rear_*` senza rifare un caso dedicato.
- **`--geometry-only --assembly …`**: undertray, front wing, rear wing o full car.
- **Sintesi per famiglia**: nella scheda Sintesi puoi scegliere "solo ala anteriore", "solo ala posteriore", "solo corpo" o tutte; non solo il fondo.
- La suite passa l'assieme del caso (`assieme` nel dataset) all'exe, quindi ogni caso usa il suo.
- Verificato sul caso reale FW5 full car: ala anteriore apertura 1,66 m, corda media 0,539 m, area 0,894 m², AR 3,08; ala posteriore 1,40 m, 0,657 m, 0,917 m², AR 2,13; 43 zone.

### v1.15.0 — Aero Suite: un processo, un report, brand di squadra

La suite non produce più tre HTML separati: **un solo processo e un solo report brandizzato**.

- **Un comando**: `00_Aero_Suite.bat` → geometria dalla mesh → tabelle → `Aero_Suite.html`. Nessuno stadio da lanciare a mano.
- **Un report**: cinque schede in un file — panoramica (KPI, mappa deportanza/resistenza, tabella), confronto zone, sintesi (donatori, tre pacchetti, piano di prova), geometria (profili, misure, correlazioni), metodo.
- **Brand identity**: palette ufficiale (`#11255C`, `#5B2581`, `#FDEB19`, `#D8EEFC`), Roboto e Roboto Condensed incorporati come `@font-face` in base64, monogramma UC nell'header e wordmark nel footer, barre oblique giallo/viola/azzurro.
- Il dashboard è autonomo (nessuna CDN, nessun server) e funziona anche senza `assets`: in quel caso usa i font di sistema.

### v1.14.0 — Aero Suite e geometria dalla mesh

Tre pezzi nuovi che chiudono il cerchio:

- **`--geometry-only`**: l'app legge i triangoli delle zone del fondo direttamente dal `.cas` e scrive `geometry.json` — profilo altimetrico, altezza minima, tratto in salita (diffusore o cascata, con angolo), espansione, area in pianta e area della superficie. Nessuna misura manuale.
- **`suite/aero_suite.py` + `00_Aero_Suite.bat`**: un comando per *geometria → tabelle → report*. Per ogni caso lancia l'exe, raccoglie `geom/<caso>.json`, costruisce `dataset_geom.csv` con le correlazioni geometria-prestazioni, genera Explorer e Recombination e una pagina indice **Aero_Suite.html** con i profili del fondo in scala comune.
- **Geometria verificata sul caso reale FW5**: fondo 1,65–3,35 m, altezza minima 37,9 mm, tratto in salita 50,6° (gradino/cascata, non diffusore: il codice lo distingue), espansione 6,73, area del fondo 1,105 m², 117.040 triangoli letti.

### v1.13.0 — Aero Recombination Engine

Il passo che mancava: non descrivere le configurazioni, ma **ricomporre la vettura** dai dati. `tools/recombination.py` (solo libreria standard) per ogni zona del fondo, delle ali e del corpo cerca la configurazione che la produce meglio e costruisce una "vettura sintetica".

- **affidabilità per zona** misurata sulle run doppie (stesso modello, stesso file): una zona entra solo se il guadagno supera 3σ del suo rumore (0,45 N sui dati reali);
- **famiglie**: fondo, ala anteriore, ala posteriore, corpo, gomme; le **gomme** sono escluse per default (artefatti della parete rotante, non leve di progetto);
- **tre pacchetti incrementali** da simulare (solo fondo / fondo+ali / tutto l'affidabile) con guadagno, drag, donatori e numero di interfacce da raccordare;
- **piano di prova** per ogni pacchetto: parti da un caso e cambia solo le zone elencate.

Sul dataset reale (gruppo RW1 + diffusore completo, riferimento V9 508,5 N / 219,7 N): sintesi **560,4 N / 229,8 N** = **+51,9 N** con **+10,2 N** di drag (L/D 2,44 contro 2,31). Il pacchetto "solo fondo" vale **+15,4 N / +3,0 N**: quello è il primo da simulare.

### v1.12.0 — Aero Design Explorer

Un report interattivo autonomo che legge il dataset del batch e lo trasforma in decisioni di progetto. `tools/design_explorer.py` (solo libreria standard) produce un singolo HTML con:

- **mappa dei modelli**: deportanza vs resistenza, frontiera di Pareto, punti cliccabili;
- **tabella ordinabile** dei casi con iterazioni, configurazione e modello;
- **confronto per zona** tra due casi qualsiasi: dove si guadagna e dove si perde, con le zone presenti in uno solo dei due;
- **cosa i dati permettono**: modello lineare con validazione leave-one-out (λ scelto sul LOO), effetto stimato dei parametri, copertura dello spazio di progetto;
- **cinque simulazioni da fare adesso**, scelte per riempire i vuoti dello spazio (massima distanza dai casi esistenti, non previsioni).

Sul dataset reale (17 casi): deportanza RMSE leave-one-out **30,6 N** (31× il rumore di 1,05 N) → il report dichiara che i dati non sostengono una previsione di dettaglio; resistenza RMSE 5,7 N (R² 0,95). Frontiera di Pareto con V9 in testa e D8 come miglior compromesso.

### v1.11.4 — esclusione tracciabile dei casi non validi

`escludi.txt` nella cartella dei risultati: un `case_id` per riga (con `#` per i commenti). `make_tables.py` e `check_dataset.py` lo leggono e **saltano quei casi**, senza cancellare i JSON.

```text
# v16: run non validi
v16-70-50
v16-70-50__3
v16-70-50__4
# V14: e' la versione 1, si usa V14__3_ti_prego
V14
```

L'esclusione resta scritta accanto ai dati ed è riproducibile: rilanciando le tabelle i casi restano fuori, e il conteggio viene stampato ("Esclusi: 4").

### v1.11.3 — casi sospetti e iterazioni di convergenza

Dopo la prima estrazione reale (21 casi) sono emersi due problemi che i controlli non vedevano:

- **un caso con numeri impossibili** (deportanza 5397 N, drag −12741 N, Cp_min al limite di clipping): tutti i CHK passavano perché la somma dei PID tornava. Ora `check_dataset.py` verifica la **plausibilità fisica** (deportanza, drag positivo, L/D, Cp_min, percentuale di stallo) e lo segnala come caso sospetto;
- **iterazioni di convergenza diverse** (250…1750): il numero finale nei nomi Fluent è l'iterazione a cui è stato salvato il caso. `make_tables.py` lo estrae in una colonna `iterazioni`, `check_dataset.py` segnala i casi sotto 1000 iterazioni e il range tra i casi.

Verificato sul dataset reale: 1 caso sospetto individuato, 4 casi sotto 1000 iterazioni segnalati, anteprima della classifica che non mostra più il caso impossibile.

### v1.11.2 — tutorial d'uso e filtro dei casi

- `batch/TUTORIAL.md`: guida completa in cinque parti (singolo caso dalla GUI, estrazione in blocco passo per passo, lettura di `dataset.csv` e `_controlli.txt`, problemi comuni con rimedi, riferimento rapido dei comandi).
- `--case-filter "Venturi"`: elabora solo i casi il cui id o percorso contiene la stringa; il dry-run mostra anche quanti casi sono esclusi dal filtro.

### v1.11.1 — estrazione in blocco: si tengono solo le iterazioni

Le cartelle contengono spesso sia i file di partenza sia quelli dell'ultima iterazione. Ora `batch_extract.py` riconosce **solo i file iterati**:

| Nome | Esito |
|---|---|
| `V14_3-1-01250.cas` / `.dat` | usato (nome-iterazione-id) |
| `V14_3.cas` / `.dat` | **scartato** (file di partenza) |
| `nome_1_iterazioni.cas` | usato (contiene "iterazion") |

- le cartelle con i soli file di partenza vengono scartate e listate in `run_summary.txt`;
- se in una cartella ci sono entrambi, la coppia iterata viene **isolata** in `_solo_iterazioni` con hardlink (nessuna copia dei GB): il programma non può più prendere il file sbagliato;
- con più iterazioni (`-1-`, `-2-`) usa la più recente e segnala il caso come `AMBIGUO`;
- `--iter-keyword` per una regola diversa, `--include-all` per forzare tutto;
- `index.csv` e `dataset.csv` riportano `cas_usato`/`dat_usato`.

Verificato sul caso reale: cartella con `V14_3.*` (finto) + `V14_3-1-01250.*` (veri) → usata solo la coppia iterata, 122 s, 483,1 N / 222,7 N, 43 PID, `_solo_iterazioni` rimossa a fine corsa.

### v1.11.0 — estrazione in blocco di molte analisi

La cartella `batch/` contiene tutto per elaborare **decine di casi** su un altro PC, senza installare nulla oltre a Python 3.8+:

| File | Cosa fa |
|---|---|
| `01_Estrai_tutti.bat` | chiede la cartella radice (o la accetti trascinandola) e lancia l'estrazione |
| `02_Tabelle_e_controlli.bat` | costruisce le tabelle e verifica la coerenza |
| `batch_extract.py` | trova le cartelle con `.cas`+`.dat` (anche annidate), esegue l'exe, salva solo il JSON dei dati (~200 KB/caso) e il log |
| `make_tables.py` | produce `dataset.csv` (un caso per riga) e `dataset_pid.csv` (un PID per riga), unendo `metadata.csv` |
| `check_dataset.py` | controlla che i casi siano confrontabili: velocità, convenzione, assieme, numero di PID, simmetria, somma PID = KPI |

- resumibile: i casi già fatti vengono saltati;
- un caso rotto non ferma gli altri e finisce in `run_summary.txt`;
- gli HTML da ~80 MB e `output_diagnostics` vengono cancellati dopo ogni caso;
- `--dry-run` elenca i casi trovati prima di partire.

Verificato su un caso reale (FW5): 1 caso, 135 s, 483,1 N / 222,7 N, 43 PID, tabelle e controlli puliti; caso corrotto gestito con codice di uscita 3.

### v1.10.0 — cursore velocità nel report

Nel report c'è una sezione **Estrapolazione a un'altra velocità**: uno slider che ricalcola deportanza, drag, |L|/D e potenza aero a una velocità qualsiasi.

Fisica: a **Cp congelato** le forze scalano con la pressione dinamica, `F(v) = F(v_ref)·(v/v_ref)²`. È esatto per il campo di moto simulato; non tiene conto del fatto che a velocità molto diverse cambiano Reynolds, transizione e separazione, quindi fuori da ±30% è solo un ordine di grandezza (la nota è scritta nel report stesso). Il CoP non si sposta, perché tutte le forze scalano allo stesso modo.

Verificato eseguendo il JavaScript del report con un DOM finto: a 14 m/s 483 N / 222,7 N, a 28 m/s 1932 N / 890,8 N, a 7 m/s 121 N / 55,7 N, |L|/D costante 2,17.

### v1.9.4 — la velocità delle streamlines arriva dal config

Il titolo diceva `V_inf = 16,7 m/s` anche con 14 impostato. Causa: il codice leggeva un KPI che **non esiste** (`inlet_velocity`) e cadeva nel fallback cablato **16,67 m/s** (= 60 km/h); la chiave vera è `velocity_inf_ms`. Ora:

- `resolve_velocity_inf` in `render_utils` con catena `velocity_inf_ms → velocity_inf → inlet_velocity → 14,0`;
- usato sia dal launcher (streamlines) sia da `image_diagnostics`;
- default della GUI allineato a `14,0` (era `16,67`).

Effetto: velocità locali e scala colori erano il **19% più alte** in tutte le immagini con streamlines. Verificato sul caso FW5: titolo ora `V_inf = 14.0 m/s`, colorbar 7,5–27,5 invece di 10–30.

### v1.9.3 — commento del config allineato alla realtà

La v1.9.2 aveva corretto la nota nel parser ma **non** il commento di `config.yaml` (errore mio: mancava il salvataggio). Ora entrambi dicono la stessa cosa, verificata sul caso reale: con la convenzione di default i numeri sono **positivi per forze dirette verso il basso**, come in un report Fluent con `Direction Vector (0 -1 0)`.

### v1.9.2 — convenzione dei segni: documentazione corretta

Verifica sul caso reale (FW5): con la convenzione di default (`report_force_convention: "lift"`) i numeri sono **positivi quando la forza è diretta verso il basso**, cioè identici a un report Fluent con `Direction Vector (0 -1 0)`. La documentazione di `config.yaml` diceva il contrario ed è stata corretta; nessun cambio di comportamento.

### v1.9.1 — segni delle forze allineati al report Fluent

Confronto componente per componente con il report *Forces* di Fluent (caso FW5, direzione `(0 -1 0)` per la deportanza e `(1 0 0)` per il drag). Il set di zone era già identico (43 vs 43); erano sbagliati **due segni**:

| Grandezza | Prima | Fluent | Correzione |
|---|---|---|---|
| drag di pressione (`chassis`) | `-12,590` | `+12,586` | `-pid_fx_press` |
| drag totale | `\|p\| + \|v\|` (moduli) | `p + v` con segno | somma algebrica |
| viscosa verticale (`chassis`) | `+0,02` | `-0,02` | `pid_fy_visc` senza `-` |

Effetto misurato sul caso FW5 (metà modello → ×2 per il full car):

| | Fluent | Prima | Ora |
|---|---|---|---|
| Deportanza (metà / full) | 241,53 / 483,07 N | 243,38 / 486,76 N (+0,76%) | **241,50 / 483,00 N (−0,01%)** |
| Drag (metà / full) | 110,52 / 221,05 N | 113,71 / 227,42 N (+2,9%) | **111,35 / 222,70 N (+0,75%)** |

Il residuo sul drag è tutto nella componente **viscosa** (la nostra è ~8% più alta per zona): la pressione coincide al centesimo.

### v1.9.0 — viste Cp per lato e selezione manuale dei PID

**Le due mappe Cp erano quasi identiche** (98,27% di pixel uguali): le viste "lato aspirazione" e "superiore" proiettavano **tutti** i triangoli sullo stesso piano e differivano solo per l'ordine di sovrapposizione. Ora il mesh combinato porta le **normali per triangolo** e ogni vista filtra il proprio lato (`n·Y < -0,15` in basso, `> +0,15` in alto): misurata una differenza reale (51,13% di pixel identici, cioè solo sfondo e legenda).

**Selezione manuale delle zone wall** (per allineare il computo delle forze a Fluent): nuova card *PID nel computo* con l'elenco delle zone wall del `.cas`, checkbox, e pulsanti **Tutti / Nessuno / Automatico**. La scelta va in `assemblies.<assieme>.manual_zone_ids` e **sostituisce** il filtro per keyword (vale anche per `full_car`). Sul caso FW5: 43 zone wall, 5 incluse automaticamente per l'undertray.

### v1.8.3 — le immagini arrivano davvero all'AI

Causa trovata sul campo (con il caso reale FW5): una delle immagini inviate era **8612 px** di larghezza, oltre il limite DeepSeek di **8192 px per lato** → `HTTP 400 "You have uploaded an unsupported image"`. Le altre passavano, quindi il messaggio sembrava riguardare il modello mentre era una **nostra immagine**.

Perché era così larga: nella mappa PID le etichette delle zone finivano fuori dall'area del grafico e `bbox_inches="tight"` allargava il file salvato (misurato: 6015 px con etichette non ritagliate, 925 px con `clip_on=True`).

- **Client**: `normalize_image_bytes` converte in RGB e ridimensiona ogni immagine entro **4096 px** per lato prima dell'invio; i file illeggibili vengono **saltati** (con log) invece di far fallire tutta la richiesta;
- **Renderer**: etichette PID con `clip_on=True`, così la mappa non sfora più il canvas;
- test: ridimensionamento, skip dei file rotti, limite di payload.

Verificato con le immagini reali del caso FW5: prima 1 immagine su 4 rifiutata e la richiesta combinata in errore; ora **tutte accettate**, richiesta combinata inclusa.

### v1.8.2 — `--ai-check` usabile da terminale, e un PNG di prova che era corrotto

Due problemi reali che impedivano la diagnosi:

- **La chiave si poteva inserire solo nella GUI** (lì resta in memoria, non viene salvata su disco). Da terminale `--ai-check` vedeva il config incluso, senza chiave. Ora: `--ai-key sk-...` e `--ai-provider deepseek|gemini|openai`, validi per il controllo **e** per l'esecuzione. La chiave passata da riga di comando **non** viene scritta su disco.
- **Il PNG 1×1 della prova vision era corrotto** (una stringa base64 scritta a mano): il server lo rifiutava, quindi la prova avrebbe potuto dire "il modello non accetta immagini" per colpa nostra. Ora il PNG è costruito a runtime (`struct` + `zlib`) e c'è un test che ne verifica firma, IHDR, IDAT e IEND.

```bash
FS-MetaPostDiag.exe --ai-check --ai-key sk-xxxxxxxx
# oppure, senza argomenti:
$env:DEEPSEEK_API_KEY = "sk-xxxxxxxx"; FS-MetaPostDiag.exe --ai-check
```

### v1.8.1 — il budget dei triangoli (la vera causa delle immagini "puntinate")

La v1.8.0 aveva tolto il collo di bottiglia nel renderer, ma i triangoli venivano gia' **scartati prima**, in `_combine_real_zone_meshes(target_budget_triangles=70000)`: sul caso FW5 restavano **103.908** triangoli su 1.529.200 (il numero che compariva nel titolo dell'immagine).

- budget alzato a **1.500.000** e reso configurabile: `meta.render_max_triangles` (30 MB di RAM ogni ~500k triangoli);
- il combiner è passato in `render_utils.py` (solo numpy) con 4 test: budget rispettato, zone piccole mai tagliate, mirror che raddoppia;
- il combinatore non emette più `RuntimeWarning: Mean of empty slice` sullo stderr.

Misura sul caso reale FW5: budget 70.000 → 103.908 triangoli; budget 1.500.000 → **1.529.226**; render delle 24 viste in 47,9 s. La geometria (muso, fondo, sospensioni, ruote, diffusore) diventa riconoscibile.

### v1.8.0 — superfici dense nelle immagini e diagnosi della vision

**Immagini.** Il renderer disegnava al massimo **55.000 triangoli** con un subsampling a passo uniforme: sul caso reale (1.529.200 facce) restava il **3,6%**, quindi si vedevano i singoli triangoli con i buchi e la geometria spariva.

- fino a 150.000 triangoli: `tripcolor` vettoriale (contorno fedele);
- oltre: **rasterizzazione** a livello di pixel (campionamento al baricentro **e** sui tre vertici, poi riempimento dei buchi) → superficie continua, costo lineare, memoria limitata (campione a 4 M triangoli).
- Nuovo modulo `render_utils.py` (solo numpy, testabile in CI): 1,9 M triangoli resi in ~0,1 s.

**Diagnosi vision.** `--ai-check` e il pulsante *Verifica AI* ora leggono `input_modalities` del modello e fanno una **prova vision con un PNG 1×1**: se il 400 arriva lì, il modello della chiave non accetta immagini — che è la ragione del `solo testo (immagini rifiutate)` (il client riprova senza immagini e lo dichiara).

### v1.7.1 — "Verifica AI" anche dalla GUI

La diagnostica era solo da riga di comando (`--ai-check`), che **non** viene eseguita durante un'analisi: chi lavora dalla GUI doveva uscire dall'app.

- Nuovo pulsante **Verifica AI** nella card "Esecuzione META", sotto la API key: usa provider e chiave **attuali della GUI** (anche appena digitati) ed esegue in un thread la stessa diagnostica del comando: elenco modelli, avviso se il modello non c'è, chiamata minima con e senza thinking, messaggio esatto del server.
- I risultati finiscono nella **console dell'app** con prefisso `[AI-VERIFICA]`; l'interfaccia non si blocca (thread + coda di log già thread-safe) e un doppio clic non duplica il controllo.
- Durante l'analisi normale l'AI viene chiamata davvero e, se fallisce, il motivo resta nella console (`[INFO] … Dettaglio: …`) e nella nota del report.

### v1.7.0 — diagnosi dell'AI Vision e richieste più robuste

Un `HTTP 400` di DeepSeek non diceva *cosa* fosse sbagliato: ora si legge tutto.

- **`--ai-check`**: comando che verifica chiave, elenco modelli e una chiamata minima, ed esce. Mostra il messaggio esatto del server.
  ```bash
  FS-MetaPostDiag.exe --ai-check          # o: python main.py --ai-check
  ```
  Esempio reale con chiave non valida:
  ```text
  [AI-CHECK] chiave: presente (sk-c…test)
  [AI-CHECK] errore su GET /models -> HTTP 401: {"error":{"message":"Authentication Fails, Your api key ... is invalid"}}
  ```
  Esempio con modello non disponibile per la chiave:
  ```text
  [AI-CHECK] modelli disponibili per questa chiave: deepseek-chat, deepseek-reasoner
  [AI-CHECK] ATTENZIONE: 'deepseek-flash' NON e' tra i modelli disponibili: usa uno degli id elencati.
  ```
- **La nota del report riporta il messaggio del server**, non solo il codice HTTP (fix di una doppia lettura del corpo che lo perdeva).
- **Retry senza immagini**: se DeepSeek rifiuta la richiesta con immagini (HTTP 400), riprova una volta in solo testo e la fonte diventa `DeepSeek Vision (..., solo testo (immagini rifiutate))`.
- **Limite di dimensione**: le immagini vengono accodate fino a ~24 MiB di base64; le eccedenti si scartano con una riga di log, invece di far fallire la richiesta (limite DeepSeek 48 MiB).

### v1.6.1 — il report dice se (e perché) l'AI Vision non è stata usata

Prima, quando la perizia veniva dal motore locale, il report mostrava solo `Fonte: Motore Diagnostico Verificato ...`: non si capiva se l'AI fosse disattivata, senza chiave o in errore.

- Nuovo campo `ai_status` (`mode: "ai" | "local"`, `provider`, `model`, `reason`) restituito da `generate_ai_vision_commentary`.
- Nel dossier HTML, sotto il titolo della sezione 3, compare una **nota gialla**: *"AI Vision non usata · Nessuna API key configurata per il provider 'gemini': la perizia viene dal motore esperto locale."*
- Stessa informazione nel **Markdown** (`Fonte:` + nota) e nel log.
- Motivi distinti: chiave assente, AI disattivata, provider sconosciuto, errore HTTP (con codice e modello), risposta vuota.

### v1.6.0 — DeepSeek come provider AI Vision (con thinking)

Oltre a Gemini e OpenAI, il commento aerodinamico sulle immagini può usare **DeepSeek**: modello con vision + thinking mode, selezionabile dalla GUI o dal config.

- **Provider** `deepseek` in `ai_vision.provider` (o dal menu a tendina accanto alla API key).
- **Modello** `deepseek-flash` — è il nome API ufficiale di DeepSeek-V4.1-Flash, l'unico che accetta immagini (`config.yaml` → `model_deepseek`).
- **Thinking**: `deepseek_thinking: true` e `deepseek_reasoning_effort: "high"` (`low` | `high` | `max`). Nella richiesta viaggiano `thinking: {"type": "enabled"}` e `reasoning_effort`; in thinking mode temperatura e penalty non sono ammesse e non vengono inviate.
- **Immagini** in data-URL base64 (`image_url`), come da documentazione DeepSeek: fino a 4 viste annotate + 2 grafici, stessa selezione degli altri provider.
- **Chiave**: `api_key` nel config/GUI oppure variabile d'ambiente `DEEPSEEK_API_KEY`.
- **Errori leggibili**: se il nome modello non esiste, il log elenca i modelli disponibili per quella chiave (`GET /models`) e la pipeline ripiega sul motore esperto locale, senza interrompersi.
- Validazione del config estesa: provider sconosciuto o `reasoning_effort` non valido producono un avviso `[CONFIG-WARN]`.

Sorgenti: [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/), [Vision](https://api-docs.deepseek.com/guides/vision), [Lists Models](https://api-docs.deepseek.com/api/list-models).

### v1.5.0 — il config viene validato, e `wheelbase` serve davvero

- **Validazione all'avvio** (`config_bridge.validate_config`): gli errori che prima passavano in silenzio ora producono un avviso `[CONFIG-WARN]` nel log (CLI e console della GUI). Controlli:
  - `coordinate_system.*`: gli assi devono essere **X longitudinale, Y verticale, Z laterale** — se il file dichiara altro, i segni delle forze sarebbero sbagliati;
  - `reference_values.*`: velocità, densità, area e passo devono essere **> 0**;
  - `report_force_convention` deve essere `lift` o `downforce` (prima un valore ignoto veniva ignorato in silenzio);
  - se `front_axle_x`/`rear_axle_x` ci sono, il passo dichiarato deve concordare entro il 5%.
- **`wheelbase` non è più solo documentale**: dichiarando `front_axle_x` e `rear_axle_x` il report mostra il **CoP in percentuale del passo** (es. "0,444 m · 44,4% del passo"), che è il numero con cui si ragiona sul bilanciamento. Senza quei due valori il KPI non compare.
- `fluent_variables` resta **dichiarativo** (il parser legge i campi per `sub_id`, non per nome): il config lo dice esplicitamente e la validazione ne controlla solo la forma.

### v1.4.1 — ricerca di META Post su qualunque PC

- La ricerca dell'eseguibile **non contiene percorsi fissi** della macchina di sviluppo: deriva tutto da `%LOCALAPPDATA%`, `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%PROGRAMDATA%` e dalle lettere dei **dischi fissi** (via `GetLogicalDrives`, solo `DRIVE_FIXED` per non attendere unità di rete).
- Ordine di risoluzione: percorso esplicito in `config.yaml` → variabili `META_POST_EXE`/`BETA_META_PATH` → scansione (versione più alta, launcher `.bat` preferito).
- Se META non c'è, la pipeline continua con le immagini Python e la GUI mostra `N/D`.
- Nuovo test di **guardia** che fallisce se nel codice compare un percorso personale (`C:\Users\...`, `/Users/...`).

### v1.4.0 — convenzione delle forze, META Post riconosciuto, questioni aperte chiuse

- **Convenzione lift/downforce configurabile** (`reference_values.report_force_convention`). In Fluent il report si definisce "lift" (proiezione su +Y: **deportanza negativa**) oppure "downforce" (segno invertito). Il parser ora espone sia `lift_N` (grandezza fisica) sia `downforce_N` secondo la convenzione scelta, con `CL`, `CL*A` ed efficienza coerenti: nel report i numeri coincidono con quelli del setup Fluent.
- **Centro di pressione realmente pesato** (bug): il peso era `max(downforce, 0)` su valori negativi, quindi si ricadeva sempre sul centro geometrico (CoP = 50% L fisso). Ora pesa la sola parte che preme verso il basso.
- **Asimmetria laterale corretta** (bug): il confronto tra le due metà usava i valori con segno e poteva dare 200%; ora somma i moduli e resta nel range 0–100%.
- **META Post davvero riconosciuto e usato**: nuovo modulo `meta_locator.py` (leggero e testabile) che sceglie la **versione più alta** e preferisce il launcher `.bat`; l'invocazione stampa versione e codice di uscita, con timeout configurabile (`meta.batch_timeout_s`). Verificato sul campo: META Post v25.1.0 eseguito, exit 0.
- **`.h5` e `.gz` ignorati**: il parser legge solo `.cas`/`.dat` binari Fluent; i formati HDF5/compressi non vengono più cercati né proposti.
- **Report con le forze finali**: deportanza e resistenza totali in N in primo piano (somma di pressione + viscosa), con i coefficienti come dettaglio; rimossi gli split pressione/viscosa dalle tabelle. Efficienza mostrata come `|L|/D` (positiva) e `lift_N` affiancata per il confronto con Fluent.
- **X-cut rinominati `xcut_cp_*`**: il grafico mostra Cp, non la pressione totale.
- Nota di numerazione: la serie `06_ycut_velocity_*` è prodotta da META Post, quindi compare solo quando la sessione batch viene eseguita.

### v1.3.0 — report HTML in brand identity

Il dossier HTML usava ancora il tema precedente (slate/ciano/verde, `Segoe UI`, gradienti). Ora segue la stessa brand identity dell'interfaccia.

- **Palette di brand**: navy `#11255C` per le card, `#0B1B47` per il fondo, giallo `#FDEB19` per accenti e KPI, azzurro `#d8eefc` per il testo secondario, viola `#5B2581` per le informazioni, rosso `#E42320` per gli errori.
- **Header con il monogramma UC** incorporato in Base64: il report resta un file unico e standalone.
- **Card senza bordi e arrotondate**, titoli di sezione con barretta d'accento, KPI a 1.85 rem.
- **Badge a pillola** con sfondo tinto (PASS/FAIL/CRITICAL/WARNING/INFO) invece dei blocchi pieni saturi.
- Pulsanti: primario giallo a pillola, secondari outline (`Esporta tabella in Excel`).
- Tabelle con intestazioni in maiuscoletto attenuato e separatori sottili, riga totale con tinta gialla.
- Font stack `Roboto` con fallback di sistema (il report non incorpora i font per non gonfiare il file).
- Regole `@media print` aggiornate: su carta resta leggibile in bianco e nero.

### v1.2.0 — restyling moderno dell'interfaccia

Stessa brand identity, linguaggio visivo aggiornato: via gli elementi che invecchiavano l'interfaccia.

- **Card senza bordi e con angoli arrotondati** (`RoundedPanel`, radius 18) al posto dei riquadri con cornice: la gerarchia la fa la superficie, non la linea.
- **Via i dingbat** `◈ ✦ ⚙ ▶ ▤ ↗`: al loro posto una **barretta d'accento** colorata accanto ai titoli.
- **Un solo elemento pieno**: la CTA ora è gialla piena con testo navy e angoli morbidi, senza gradiente; le azioni secondarie diventano **outline** o **ghost**.
- **Gerarchia tipografica**: titoli 15/11, etichette di campo in maiuscoletto attenuato, **KPI a 19 pt**.
- **Header più arioso** con chip `META Post v25.1+` e, al posto della striscia piena, un **filo sottile con tre accenti** di brand.
- Scrollbar sottile e discreta (gialla solo allo hover), barra di avanzamento 4 px che a riposo resta neutra.
- Console incassata senza cornice, interlinea maggiore.

### v1.1.0 — interfaccia in brand identity UniNa Corse

- **Interfaccia riallineata al brand book** (`brand.py`): palette ufficiale `#11255C` · `#5B2581` · `#FDEB19` · `#d8eefc`, sfumature derivate dalle rampe del brand book.
- **Header con il monogramma UC** e le **barre oblique** (il "segno grafico" del team) disegnate su Canvas: nessuna immagine extra da includere.
- **Tipografia Roboto** (SIL OFL, inclusa in `assets/fonts` e registrata come font privato del processo, senza installarla sul sistema); i numeri e il log usano Roboto Condensed.
- **Ethnocentric non viene incluso**: la licenza Typodermic è una *Desktop EULA* e non consente la ridistribuzione del font dentro un'applicazione. Il font display è quindi Roboto.
- Pulsante principale a gradiente giallo con testo navy; azioni secondarie in viola; log e stato con i colori semantici derivati dal brand.
- Wordmark UniNa Corse nel footer; icona della finestra allineata all'eseguibile.
- Il label `.dat` e i PID usano la tinta viola del brand (prima erano colori fuori palette).

### v1.0.4 — nessun traceback Tkinter nella GUI

- **Corretto un difetto introdotto nella v1.0.3**: `discover_cas_dat` sollevava `NoCaseFilesFound` e la GUI la chiama dentro un callback `after`, quindi senza `.cas` comparivano `Exception in Tkinter callback` su stderr.
- Nuova `file_discovery.try_discover()` che **non solleva** e restituisce `(cas, dat, messaggio)`: la GUI mostra il messaggio nella propria console, la CLI continua a uscire con `[ERRORE]` e codice non nullo.
- 2 nuovi test (47 totali) sulla variante senza eccezioni.

### v1.0.3 — avvio senza argomenti e selezione dei file

- **Nessun argomento = GUI**: un doppio clic sull'eseguibile apre l'interfaccia, non la pipeline sulla cartella corrente. Con `-w`, `-a` o `--config` resta la CLI.
- **Selezione dei file robusta** (`file_discovery.py`): il `.cas` è obbligatorio e la sua assenza produce un messaggio che dice cosa fare, invece di un `FileNotFoundError` con traceback; il `.dat` viene accoppiato per nome base; i file che non sono dataset (es. `*_license.dat` di BETA CAE) vengono ignorati.
- Errori d'uso stampati come `[ERRORE] ...` con codice di uscita non nullo, senza traceback.
- 6 nuovi test sul ritrovamento dei file (cartella con solo licenze, accoppiamento per nome, `.cas.h5`).

### v1.0.2 — icona UniNa Corse

- **Icona dell'eseguibile e della finestra**: `assets/FS-MetaPostDiag.ico` (7 misure, da 16 a 256 px), ottenuta dal logo UNINA CORSE su fondo blu notte con angoli arrotondati.
- Lo spec PyInstaller usa `icon=` per l'exe e include l'`.ico` tra i dati, così anche la finestra Tkinter mostra il logo (`gui_app._apply_window_icon`).
- `assets/FS-MetaPostDiag.png` (256 px) per documentazione e README.

### v1.0.1 — pacchetto Windows (eseguibile)

- **Build Windows** con PyInstaller (`FS-MetaPostDiag.spec`, `FS-MetaPostDiag.exe`): nessun Python da installare.
- **La configurazione viene trovata anche nell'exe**: ordine `--config` → accanto all'eseguibile → `config.yaml` incluso nel bundle → default interni. Prima l'exe ignorava il file e usava i default (32 viste invece delle 23 configurate).
- `main.py` stampa la riga `[CONFIG] <percorso>` all'avvio, così si vede subito da dove arrivano le soglie.
- Test: `tests/test_packaging.py` verifica che lo spec includa `config.yaml` e `meta_post_worker.py`; nuovi test sul ritrovamento della configurazione.

### v1.0.0 — configurazione viva, bbox corretto, test e CI

Prima release versionata del progetto (il commit iniziale non aveva un tag). Verifica la versione con `python main.py --version`.

- **Nuovo `config_bridge.py`**: unica sorgente di default e risoluzione della configurazione.
- **`config.yaml` finalmente efficace**: keyword PID, stazioni di taglio, soglie, `cp_range` e `reference_area` sono ora letti dal codice; prima erano ignorati.
- **Keyword additive**: quelle del file si sommano al fallback storico, quindi nessun PID già riconosciuto può sparire (era il rischio principale, es. `diffusore_int` contro `diffuser`).
- **Default allineati**: `load_config()` non usa più 16.67 m/s e area 1.0 contro i 14 m/s e 1.08 del file.
- **CL e CD** calcolati con `reference_area` (`CL*A` e `CD*A` restano invariati).
- **`--no-meta-batch` e `--ai-model`** ora esistono davvero in `argparse` (erano documentati ma assenti).
- **Fonte del dato viscoso**: nuovi campi `viscous_source` per PID e per assieme (`fluent` / `estimated` / `mixed` / `none`), così una stima non viene scambiata per un dato Fluent.
- **Convenzione di segno dichiarata** e coperta da test (`SIGN_CONVENTION_NOTE`, `vertical_force_y_N`).
- **Bounding box corretto**: ora usa tutti i vertici delle facce invece dei baricentri (prima l'ingombro era sottostimato, con rischio di sbagliare il rilevamento mm/metri).
- **Nuovo check CHK-07** nel verifier: i totali del report devono coincidere con la somma dei PID.
- **Nuova problematica WARN-05**: perdita di integrità dei vortici oltre `vortex_core_loss_threshold` (chiave prima inutilizzata).
- **Test + CI**: caso `.cas`/`.dat` sintetico con attese a mano, suite eseguibile senza dipendenze, workflow GitHub Actions.
- **Dipendenze con tetto di major** e `requirements-dev.txt` separato.
