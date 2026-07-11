# Yellow Loop

Yellow Loop is an automated, end-to-end data extraction and enrichment pipeline designed to aggregate professional contact data and legal information. 

## Project Overview

The primary goal of this tool is to generate high-quality, actionable B2B lead files based on a given geographical department and specific business sectors. The pipeline operates autonomously through a sequence of interconnected scripts that scrape, enrich, and sanitize the data.

### Architecture — pipeline par (département, secteur)

Le pipeline est piloté par **un seul script : `run.py`**. L'unité de travail
n'est plus le département entier mais **chaque couple (département, secteur)** —
un run de 3 jours qui plante ne fait plus perdre les données déjà scrapées.

```
run.py  (orchestrateur)
  pour chaque département de departements.txt :
    pour chaque secteur de secteur.txt :
      si (dept, secteur) déjà "done" -> skip
      1. purge work/
      2. scraper.scrape_sector()          -> work/input.csv           (PagesJaunes, CSV frais)
      3. enrichement-scrappy/scraper.py   -> work/output_enriched.csv (SIRET/SIREN)
      4. enrichement-scrappy/dirigeant.py -> work/output_final.csv    (dirigeants Pappers)
      5. enrichement-scrappy/cleaner.py   -> work/{secteur}.csv       (nettoyage)
      6. move atomique                    -> db/{dept}/{secteur}.csv
      7. marque (dept, secteur) "done" dans state/progress.json
      8. purge work/ -> secteur suivant
```

**Structure de sortie** : un dossier par département, un CSV par secteur.
```
db/
├── 30/
│   ├── hotel.csv
│   ├── restaurant.csv
│   ├── boulangerie.csv
│   └── ...
├── 31/
│   ├── hotel.csv
│   └── ...
└── ...
```

**Garanties de la nouvelle structure :**
- **Sauvegarde granulaire** : chaque `db/{dept}/{secteur}.csv` est écrit
  atomiquement (`.tmp` puis `os.replace`) dès qu'un secteur est terminé.
  Si le run crashe au secteur suivant, tout ce qui précède est safe.
- **Le cleaner refuse d'écrire un CSV vide** : si `kept == 0` (100% sans
  téléphone ou dirigeant), le fichier n'est pas créé et le secteur est marqué
  `failed` — plus de faux succès qui laissent croire que la donnée existe.
- **Détection anti-bot** : le scraper lève `ScraperBlocked` après 3 pages
  consécutives à 0 téléphone (sélecteur cassé ou VPS blacklisté) au lieu de
  tourner 3 jours dans le vide.
- **Reprise fine** via `state/progress.json` : structure
  `{ dept: { secteur: {status, rows, updated_at} } }`. Les (dept, secteur)
  déjà `done` sont sautés. Les `failed` sont ignorés sauf avec `--retry-failed`.
- `work/` est purgé entre chaque secteur ; seuls les CSV de `db/` survivent.

### Fichiers de configuration
| Fichier | Rôle |
|---|---|
| `departements.txt` | liste des départements à traiter (un par ligne, `#` = commentaire) |
| `secteur.txt` | liste des secteurs/métiers à rechercher |
| `config.py` | tous les chemins du projet (source unique de vérité) |

### Consulter / récupérer les résultats
```bash
# Lister tous les CSV produits (avec taille)
find db -name "*.csv" -not -empty -exec ls -lah {} \;

# État par (dept, secteur) — done / failed / in_progress
cat state/progress.json | python3 -m json.tool

# Résumé rapide done vs failed
python3 -c "
import json
p = json.load(open('state/progress.json'))
done = sum(1 for d in p.values() for s in d.values() if s.get('status')=='done')
failed = sum(1 for d in p.values() for s in d.values() if s.get('status')=='failed')
print(f'✅ {done} secteurs done | ⚠️ {failed} failed')
"
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
2. Définir les départements à traiter dans `departements.txt` (`#` = commentaire).
3. Lancer l'orchestrateur (mode non-bufferisé recommandé pour voir la sortie live) :
```bash
python3 -u run.py 2>&1 | tee -a full_logs.txt
```
La boucle traite tous les (département × secteur) automatiquement et écrit
chaque résultat dans `db/{dept}/{secteur}.csv` **dès qu'il est prêt**.

Pour retenter uniquement les (dept, secteur) en échec :
```bash
python3 -u run.py --retry-failed
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

Launch the pipeline (unbuffered output for live monitoring) :
```bash
python3 -u run.py 2>&1 | tee -a full_logs.txt
```

Detach from the session to leave it running in the background:
Press `Ctrl + B`, then release and press `D`.
You can now safely terminate your SSH connection.

To reattach and monitor the progress later:
```bash
tmux attach -t scraper
```

## Output Format

Un CSV par **(département, secteur)** dans `db/{dept}/{secteur}.csv`.

Exemple d'arborescence après un run complet :
```
db/
├── 30/hotel.csv, restaurant.csv, boulangerie.csv, ...
├── 31/hotel.csv, restaurant.csv, ...
└── ...
```

Chaque CSV contient les champs suivants :
- Nom de l'entreprise
- Activité
- Téléphone (nettoyé, format `0XXXXXXXXX`)
- Adresse / Code Postal / Ville / Département
- SIRET / SIREN / Code NAF / Forme juridique
- Nom_Dirigeant (un seul nom valide extrait et nettoyé)

## Troubleshooting

**`🛑 ScraperBlocked` sur tous les secteurs**
Le sélecteur téléphone de PagesJaunes a probablement changé, ou le VPS est
détecté comme bot. Vérifier la structure HTML actuelle de PagesJaunes et mettre
à jour les sélecteurs dans `scraper.py` (bloc « ── TÉLÉPHONE ── »).

**Le pipeline saute un département alors qu'il n'est pas encore fait**
Supprimer l'entrée correspondante dans `state/progress.json`, ou passer
`--retry-failed` si le statut est `failed`.

**Sortie invisible dans tmux**
Lancer avec `python3 -u run.py` pour désactiver le buffering stdout.
