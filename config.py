"""
Configuration centrale du pipeline de scraping.
Tous les chemins du projet sont définis ici, une seule source de vérité.
"""
import os

# Racine du projet (dossier contenant ce fichier)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Sous-dossiers
ENRICH_DIR = os.path.join(BASE_DIR, "enrichement-scrappy")  # contient scraper/dirigeant/cleaner
WORK_DIR = os.path.join(BASE_DIR, "work")                   # intermédiaires éphémères (purgés)
DB_DIR = os.path.join(BASE_DIR, "db")                       # sorties finales : {dept}.csv
STATE_DIR = os.path.join(BASE_DIR, "state")                 # suivi de progression

# Fichiers d'entrée
SECTEUR_FILE = os.path.join(BASE_DIR, "secteur.txt")
DEPARTEMENTS_FILE = os.path.join(BASE_DIR, "departements.txt")

# Fichier d'état (reprise après crash)
PROGRESS_FILE = os.path.join(STATE_DIR, "progress.json")

# Noms FIXES attendus par les sous-scripts d'enrichissement (relatifs au cwd = WORK_DIR).
# Ne pas renommer : scraper.py / dirigeant.py / cleaner.py les lisent en dur.
RAW_CSV = "input.csv"                  # entrée enrichissement (produit par le scraper PagesJaunes)
ENRICHED_CSV = "output_enriched.csv"   # sortie enrichissement SIRET/SIREN
FINAL_CSV = "output_final.csv"         # sortie dirigeants (Pappers)

# En-têtes du CSV brut produit par le scraper PagesJaunes
CSV_HEADERS = [
    "Nom de l'entreprise", "Activité", "Téléphone", "Adresse",
    "Code Postal", "Ville", "Département", "Lien détaillé",
]


def ensure_dirs():
    """Crée les dossiers de travail s'ils n'existent pas."""
    for d in (WORK_DIR, DB_DIR, STATE_DIR):
        os.makedirs(d, exist_ok=True)
