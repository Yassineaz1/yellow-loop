# Yellow Loop

Yellow Loop is an automated, end-to-end data extraction and enrichment pipeline designed to aggregate professional contact data and legal information. 

## Project Overview

The primary goal of this tool is to generate high-quality, actionable B2B lead files based on a given geographical department and specific business sectors. The pipeline operates autonomously through a sequence of interconnected scripts that scrape, enrich, and sanitize the data.

### Pipeline Architecture

The execution follows a strict 4-step process:

1. **Initial Scraping (`scraper.py`)**
   - Reads target sectors from `secteur.txt`.
   - Navigates the PagesJaunes directory to extract base information: Company Name, Activity, Phone Number, Address, and Detailed URL.
   - Bypasses basic bot protections and handles dynamic DOM rendering for hidden phone numbers.

2. **Legal Information Enrichment (`enrichement-scrappy/scraper.py`)**
   - Visits each previously extracted Detailed URL.
   - Scrapes the B2B/Legal section to retrieve the SIRET, SIREN, NAF Code, Legal Form, and Creation Date.

3. **Executive Enrichment (`enrichement-scrappy/dirigeant.py`)**
   - Connects to Pappers.fr using the extracted SIREN/SIRET.
   - Parses the legal documentation to identify and extract the names of the company's executives (Dirigeants).

4. **Data Sanitization (`enrichement-scrappy/cleaner.py`)**
   - Filters out incomplete entries (e.g., missing phone numbers or invalid executive names).
   - Standardizes phone number formats.
   - Outputs a clean, final CSV file named automatically after the targeted department (e.g., `67.csv`).

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
Define your target sectors (one per line) in `secteur.txt`.
Run the main script:
```bash
python scraper.py
```
When prompted, enter the target department number. The pipeline will then execute all 4 steps sequentially.

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
python3 scraper.py
```

Detach from the session to leave it running in the background:
Press `Ctrl + B`, then release and press `D`.
You can now safely terminate your SSH connection.

To reattach and monitor the progress later:
```bash
tmux attach -t scraper
```

## Output Format

The final processed dataset is saved in `enrichement-scrappy/<department_number>.csv` and contains the following structured fields:
- Nom de l'entreprise
- Activité
- Téléphone
- Adresse / Code Postal / Ville / Département
- SIRET / SIREN / Code NAF / Forme juridique
- Nom_Dirigeant
