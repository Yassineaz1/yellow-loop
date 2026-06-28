# Yellow Loop

Yellow Loop is an automated, end-to-end data extraction and enrichment pipeline designed to aggregate professional contact data and legal information. 

## Project Overview

The primary goal of this tool is to generate high-quality, actionable B2B lead files based on a given geographical department and specific business sectors. The pipeline operates autonomously through a sequence of interconnected scripts that scrape, enrich, and sanitize the data.

### Architecture (orchestrateur en boucle)

Le pipeline est piloté par **un seul script : `run.py`**. Il traite automatiquement
la liste de départements de `departements.txt`, l'un après l'autre, sans intervention.

```
run.py  (orchestrateur)
  pour chaque département de departements.txt :
    1. purge work/                     (aucun reste du département précédent)
    2. scraper.py        -> work/input.csv           (PagesJaunes, CSV frais)
    3. enrichement-scrappy/scraper.py   -> work/output_enriched.csv   (SIRET/SIREN)
    4. enrichement-scrappy/dirigeant.py -> work/output_final.csv       (dirigeants Pappers)
    5. enrichement-scrappy/cleaner.py   -> work/{dept}.csv             (nettoyage)
    6. déplace le résultat -> db/{dept}.csv
    7. marque le département "done" dans state/progress.json
    8. purge work/ -> département suivant
```

**Garanties de la nouvelle structure :**
- `work/` est **purgé entre chaque département** : plus aucune collision de CSV.
- Le CSV brut est réécrit en mode `"w"` à chaque fois (fini l'accumulation accidentelle).
- Seul `db/{dept}.csv` survit ; tous les intermédiaires sont jetables.
- `state/progress.json` permet la **reprise après crash** : les départements déjà
  faits sont sautés. Les départements en échec sont marqués `failed` et la boucle
  continue (relancer avec `python3 run.py --retry-failed`).

### Fichiers de configuration
| Fichier | Rôle |
|---|---|
| `departements.txt` | liste des départements à traiter (un par ligne, `#` = commentaire) |
| `secteur.txt` | liste des secteurs/métiers à rechercher |
| `config.py` | tous les chemins du projet (source unique de vérité) |

### Consulter / récupérer les résultats
```bash
python3 db_tool.py list        # départements finis + nb de lignes
python3 db_tool.py status      # done / failed / restants
python3 db_tool.py get 34      # chemin local + commande scp de téléchargement
```

---

## Local Installation

### Prerequisites
- Python 3.8+
- Google Chrome installed on the host machine

### Setup
Clone the repository and install the required dependencies:
```bash
git clone https://github.com/Yassineaz1/yellow-loop.git
cd yellow-loop
pip install -r requirements.txt
```

### Usage
1. Définir les secteurs (un par ligne) dans `secteur.txt`.
2. Définir les départements à traiter dans `departements.txt`.
3. Lancer l'orchestrateur :
```bash
python3 run.py
```
La boucle traite tous les départements automatiquement et range chaque résultat
dans `db/{dept}.csv`. Pour relancer uniquement les départements en échec :
```bash
python3 run.py --retry-failed
```

---

## Server Deployment (Debian/Ubuntu VPS)

The tool is configured for headless execution on a remote Linux server, utilizing `webdriver-manager` and strict memory management arguments.

### 1. Server Preparation
Update your server and install the necessary system packages:
```bash
apt update && apt upgrade -y
apt install python3 python3-pip wget curl unzip tmux -y
```

Install the stable version of Google Chrome:
```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt install -y ./google-chrome-stable_current_amd64.deb
rm google-chrome-stable_current_amd64.deb
```

### 2. Repository Setup
Clone the repository in your working directory:
```bash
cd ~
git clone https://github.com/Yassineaz1/yellow-loop.git
cd yellow-loop
pip3 install -r requirements.txt
```

### 3. Background Execution (Tmux)
To ensure the script continues running after closing the SSH connection, use a virtual session.

Start a new session:
```bash
tmux new -s scraper
```

Launch the pipeline:
```bash
python3 run.py
```

Detach from the session to leave it running in the background:
Press `Ctrl + B`, then release and press `D`.
You can now safely terminate your SSH connection.

To reattach and monitor the progress later:
```bash
tmux attach -t scraper
```

## Output Format

The final processed dataset is saved in `db/<department_number>.csv` and contains the following structured fields:
- Nom de l'entreprise
- Activité
- Téléphone
- Adresse / Code Postal / Ville / Département
- SIRET / SIREN / Code NAF / Forme juridique
- Nom_Dirigeant
