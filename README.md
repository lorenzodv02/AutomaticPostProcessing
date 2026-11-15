# FS-MetaPostDiag — Suite Post-Processing CFD & Diagnostica Design Aerodinamica

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey.svg)]()
[![CFD Support](https://img.shields.io/badge/CFD-ANSYS%20Fluent%20(.cas%20%2F%20.dat)-orange.svg)]()
[![Post-Processor](https://img.shields.io/badge/Post--Processor-BETA%20CAE%20META-red.svg)]()
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

## 🛠️ Licenza

Questo progetto è distribuito sotto licenza **MIT**. Consulta il file `LICENSE` per ulteriori dettagli.
