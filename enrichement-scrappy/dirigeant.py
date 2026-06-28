import csv
import time
import os
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService

from bs4 import BeautifulSoup
import re

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dirigeant_scraper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PappersDirigeantScraper:
    def __init__(self, input_csv='output_enriched.csv', output_csv='output_final.csv', headless=True):
        self.input_csv = input_csv
        self.output_csv = output_csv
        self.headless = headless
        self.driver = None
        self.base_url = "https://www.pappers.fr"
    
    def setup_driver(self):
        """Configure le navigateur Chrome avec Selenium"""
        logger.info(">> Initialisation du navigateur Chrome...")
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument('--headless')
        
        # Options pour eviter la detection
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        
        # User-Agent moderne
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        try:
            import platform
            import glob
            raw_path = ChromeDriverManager().install()
            driver_path = raw_path
            driver_dir = os.path.dirname(raw_path)
            is_windows = platform.system() == "Windows"
            exe_name = "chromedriver.exe" if is_windows else "chromedriver"

            # ChromeDriverManager peut renvoyer un fichier de licence/notices (Windows ET Linux)
            # au lieu du vrai binaire. On cherche manuellement le bon exécutable.
            basename = os.path.basename(raw_path)
            if basename != exe_name or "NOTICES" in basename or "LICENSE" in basename:
                for c in glob.glob(os.path.join(driver_dir, "chromedriver*")):
                    cb = os.path.basename(c)
                    if not os.path.isfile(c) or "NOTICES" in cb or "LICENSE" in cb:
                        continue
                    if is_windows and not c.lower().endswith(".exe"):
                        continue
                    driver_path = c
                    break

            # Sur Linux, garantir que le binaire est exécutable
            if not is_windows:
                try:
                    os.chmod(driver_path, 0o755)
                except Exception:
                    pass

            logger.info(f"📍 Utilisation du driver: {driver_path}")
            service = ChromeService(driver_path)
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Script pour masquer l'automation
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            logger.info("[OK] Navigateur Chrome initialise avec succes")
            return True
        except Exception as e:
            logger.error(f"[ERREUR] Erreur lors de l'initialisation du navigateur: {e}")
            return False
    
    def search_company(self, siret_or_siren):
        """Recherche une entreprise sur Pappers par SIRET ou SIREN"""
        try:
            # Nettoyer le numero
            numero = str(siret_or_siren).strip().replace(' ', '')
            
            if not numero or not numero.isdigit():
                logger.warning(f"[ATTENTION] Numero invalide: {siret_or_siren}")
                return None
            
            # Construire l'URL de recherche
            search_url = f"{self.base_url}/recherche?q={numero}"
            logger.info(f"[RECHERCHE] Recherche: {search_url}")
            
            self.driver.get(search_url)
            
            # Attendre le chargement
            time.sleep(2)
            
            # Verifier si on est directement sur une page entreprise
            current_url = self.driver.current_url
            
            if '/entreprise/' in current_url:
                logger.info("[OK] Page entreprise trouvee directement")
                return current_url
            
            # Sinon, chercher le premier resultat
            try:
                # Attendre les resultats de recherche
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/entreprise/']"))
                )
                
                # Trouver le premier lien entreprise
                first_link = self.driver.find_element(By.CSS_SELECTOR, "a[href*='/entreprise/']")
                company_url = first_link.get_attribute('href')
                
                logger.info(f"[OK] Entreprise trouvee: {company_url}")
                return company_url
                
            except TimeoutException:
                logger.warning("[ATTENTION] Aucun resultat trouve")
                return None
                
        except Exception as e:
            logger.error(f"[ERREUR] Erreur lors de la recherche: {e}")
            return None
    
    def extract_dirigeants(self, company_url):
        """Extrait les noms des dirigeants depuis la page entreprise Pappers"""
        try:
            logger.info(f"[FICHIER] Extraction des dirigeants depuis: {company_url}")
            
            self.driver.get(company_url)
            
            # Attendre le chargement de la page
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            time.sleep(2)
            
            # Recuperer le HTML
            page_html = self.driver.page_source
            soup = BeautifulSoup(page_html, 'html.parser')
            
            dirigeants = []
            
            # METHODE 1: Chercher dans les sections "Dirigeants" ou "Beneficiaires"
            # Chercher les titres de section
            sections = soup.find_all(['h2', 'h3', 'h4'], string=re.compile(r'Dirigeant|Beneficiaire|Representant', re.IGNORECASE))
            
            for section in sections:
                logger.info(f"✓ Section trouvee: {section.get_text()}")
                
                # Chercher les noms dans le parent ou les siblings
                parent = section.find_parent(['div', 'section'])
                if parent:
                    # Chercher les liens ou spans contenant des noms
                    name_elements = parent.find_all(['a', 'span', 'div'], class_=re.compile(r'nom|name|dirigeant|personne', re.IGNORECASE))
                    
                    for elem in name_elements:
                        name = elem.get_text(strip=True)
                        # Filtrer les noms valides (au moins 2 mots, pas trop long)
                        if name and len(name.split()) >= 2 and len(name) < 100:
                            # Verifier qu'il y a au moins une majuscule (nom propre)
                            if any(c.isupper() for c in name):
                                if name not in dirigeants:
                                    dirigeants.append(name)
                                    logger.info(f"  [OK] Dirigeant trouve: {name}")
            
            # METHODE 2: Chercher les liens vers des personnes physiques
            person_links = soup.find_all('a', href=re.compile(r'/dirigeant/|/personne/', re.IGNORECASE))
            
            for link in person_links:
                name = link.get_text(strip=True)
                if name and len(name.split()) >= 2 and len(name) < 100:
                    if name not in dirigeants:
                        dirigeants.append(name)
                        logger.info(f"  [OK] Dirigeant trouve (lien): {name}")
            
            # METHODE 3: Recherche par regex dans tout le texte (fallback)
            if not dirigeants:
                logger.info("[RECHERCHE] Recherche par regex (fallback)...")
                # Chercher des patterns de noms (NOM Prenom ou Prenom NOM)
                text_content = soup.get_text()
                # Pattern pour nom + prenom (tout en majuscules ou mixte)
                name_patterns = re.findall(r'\b([A-ZÀÂÄÉÈÊËÏÎÔÖÙÛÜÇ]{2,}\s+[A-ZÀÂÄÉÈÊËÏÎÔÖÙÛÜÇa-zàâäéèêëïîôöùûüç]{2,})\b', text_content)
                
                for name in name_patterns[:5]:  # Limiter a 5 pour eviter le bruit
                    if name not in dirigeants and len(name) < 50:
                        dirigeants.append(name)
                        logger.info(f"  [OK] Dirigeant trouve (regex): {name}")
            
            # Nettoyer et formater
            dirigeants = [self.clean_name(d) for d in dirigeants]
            dirigeants = list(dict.fromkeys(dirigeants))  # Supprimer les doublons en gardant l'ordre
            
            if dirigeants:
                logger.info(f"-> {len(dirigeants)} dirigeant(s) trouve(s)")
                return dirigeants
            else:
                logger.warning("[ATTENTION] Aucun dirigeant trouve")
                return []
                
        except Exception as e:
            logger.error(f"[ERREUR] Erreur lors de l'extraction des dirigeants: {e}")
            return []
    
    def clean_name(self, name):
        """Nettoie un nom de dirigeant"""
        # Supprimer les espaces multiples
        name = re.sub(r'\s+', ' ', name)
        # Supprimer les caracteres speciaux indesirables
        name = re.sub(r'[^\w\s\-àâäéèêëïîôöùûüçÀÂÄÉÈÊËÏÎÔÖÙÛÜÇ]', '', name)
        return name.strip()
    
    def get_dirigeants_from_siret(self, siret_or_siren):
        """Fonction principale: recupere les dirigeants a partir d'un SIRET/SIREN"""
        try:
            # Rechercher l'entreprise
            company_url = self.search_company(siret_or_siren)
            
            if not company_url:
                return []
            
            # Extraire les dirigeants
            dirigeants = self.extract_dirigeants(company_url)
            
            return dirigeants
            
        except Exception as e:
            logger.error(f"[ERREUR] Erreur: {e}")
            return []
    
    def process_csv(self):
        """Traite le CSV enrichi et ajoute les dirigeants"""
        if not os.path.exists(self.input_csv):
            logger.error(f"[ERREUR] Fichier {self.input_csv} introuvable!")
            return False
        
        # Initialiser le navigateur
        if not self.setup_driver():
            logger.error("[ERREUR] Impossible d'initialiser le navigateur. Arret du script.")
            return False
        
        try:
            # Lire le CSV avec détection automatique du délimiteur
            with open(self.input_csv, 'r', encoding='utf-8') as f:
                sample = f.read(1024)
                f.seek(0)
                
                if '\t' in sample:
                    delimiter = '\t'
                    logger.info("📄 Format CSV détecté: tabulations")
                elif ';' in sample:
                    delimiter = ';'
                    logger.info("📄 Format CSV détecté: points-virgules")
                else:
                    delimiter = ','
                    logger.info("📄 Format CSV détecté: virgules")
                    
                reader = csv.DictReader(f, delimiter=delimiter)
                fieldnames = reader.fieldnames
                businesses = list(reader)
            
            logger.info(f"[STATS] {len(businesses)} entreprises a traiter")
            
            # Ajouter la colonne "Nom_Dirigeant"
            new_fieldnames = list(fieldnames) + ['Nom_Dirigeant']
            
            # Traiter chaque entreprise
            total = len(businesses)
            success_count = 0
            fail_count = 0
            
            for idx, business in enumerate(businesses, 1):
                nom = business.get('Nom de l\'entreprise', f'Entreprise #{idx}')
                siret = business.get('SIRET', '').strip()
                siren = business.get('SIREN', '').strip()
                
                logger.info(f"\n{'='*60}")
                logger.info(f"[{idx}/{total}] {nom}")
                logger.info(f"{'='*60}")
                
                # Prioriser SIREN (plus fiable sur Pappers)
                numero = siren if siren else siret
                
                if not numero:
                    logger.warning("[ATTENTION] Aucun SIRET/SIREN disponible")
                    business['Nom_Dirigeant'] = ''
                    fail_count += 1
                    continue
                
                logger.info(f"🔢 Recherche avec: {numero}")
                
                # Recuperer les dirigeants
                dirigeants = self.get_dirigeants_from_siret(numero)
                
                if dirigeants:
                    # Joindre les dirigeants avec " ; "
                    business['Nom_Dirigeant'] = ' ; '.join(dirigeants)
                    success_count += 1
                    logger.info(f"[OK] Succes #{success_count}: {business['Nom_Dirigeant']}")
                else:
                    business['Nom_Dirigeant'] = ''
                    fail_count += 1
                    logger.warning(f"[ERREUR] Echec #{fail_count}")
                
                # Sauvegarde intermediaire
                if idx % 5 == 0:
                    self.save_progress(businesses, new_fieldnames)
                    logger.info(f"[SAUVEGARDE] Sauvegarde intermediaire ({idx}/{total})")
                
                # Pause entre les requetes
                if idx < total:
                    pause_time = 3.0  # Pappers peut etre plus strict
                    logger.info(f"[TEMPS] Pause de {pause_time}s...")
                    time.sleep(pause_time)
            
            # Sauvegarde finale
            self.save_progress(businesses, new_fieldnames)
            
            # Statistiques finales
            logger.info(f"\n{'='*60}")
            logger.info(f"[OK] TRAITEMENT TERMINE!")
            logger.info(f"{'='*60}")
            
            with_dirigeants = sum(1 for b in businesses if b.get('Nom_Dirigeant'))
            
            logger.info(f"[STATS] RESULTATS:")
            logger.info(f"   Total traite: {total}")
            logger.info(f"   Avec dirigeants: {with_dirigeants} ({with_dirigeants/total*100:.1f}%)")
            logger.info(f"   Sans dirigeants: {fail_count} ({fail_count/total*100:.1f}%)")
            logger.info(f"[FICHIER] Fichier de sortie: {self.output_csv}")
            
            # Apercu
            logger.info(f"\n[LISTE] APERCU DES 3 PREMIERES ENTREPRISES:")
            for i, b in enumerate(businesses[:3], 1):
                nom = b.get('Nom de l\'entreprise', 'N/A')[:40]
                dirigeant = b.get('Nom_Dirigeant', 'N/A')[:40]
                logger.info(f"   {i}. {nom:42} | Dirigeant: {dirigeant}")
            
            logger.info(f"{'='*60}")
            return True
        except Exception as e:
            logger.error(f"[ERREUR] Erreur critique lors du traitement: {e}")
            return False
            
        finally:
            # Fermer le navigateur
            if self.driver:
                logger.info("[FERMETURE] Fermeture du navigateur...")
                self.driver.quit()
    
    def save_progress(self, businesses, fieldnames):
        """Sauvegarde le progres dans le CSV"""
        with open(self.output_csv, 'w', encoding='utf-8', newline='') as f:
            # On utilise extrasaction='ignore' pour éviter les crashs si des colonnes imprévues apparaissent
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(businesses)


def test_specific_siret():
    """Teste avec un SIRET specifique"""
    print("\n" + "="*60)
    print("🧪 TEST D'EXTRACTION DIRIGEANTS SUR PAPPERS")
    print("="*60)
    
    # SIRET de test (TotalEnergies du CSV)
    test_siret = "53168044500116"
    
    print(f"SIRET de test: {test_siret}")
    
    scraper = PappersDirigeantScraper(headless=False)
    
    if scraper.setup_driver():
        print("\n[RECHERCHE] Recherche en cours...")
        dirigeants = scraper.get_dirigeants_from_siret(test_siret)
        
        print("\n[STATS] RESULTATS DU TEST:")
        print("-" * 40)
        
        if dirigeants:
            print(f"[OK] {len(dirigeants)} dirigeant(s) trouve(s):")
            for i, dirigeant in enumerate(dirigeants, 1):
                print(f"   {i}. {dirigeant}")
        else:
            print("[ERREUR] Aucun dirigeant trouve")
        
        scraper.driver.quit()
    else:
        print("[ERREUR] Impossible d'initialiser Chrome")


def main():
    print("=" * 60)
    print("ENRICHISSEMENT DIRIGEANTS - PAPPERS.FR")
    print("Ajoute les noms des dirigeants au CSV enrichi")
    print("=" * 60)
    print()
    print("[LISTE] Fichier d'entree: output_enriched.csv")
    print("[LISTE] Fichier de sortie: output_final.csv")
    print()
    print("Options:")
    print("  1. Lancer l'enrichissement complet")
    print("  2. Tester avec un SIRET specifique")
    print()
    
    choix = input("Votre choix (1 ou 2): ").strip()
    
    if choix == "1":
        headless = input("Mode invisible ? (o/N): ").strip().lower() == 'o'
        
        scraper = PappersDirigeantScraper(
            input_csv='output_enriched.csv',
            output_csv='output_final.csv',
            headless=headless
        )
        return 0 if scraper.process_csv() else 1
        
    elif choix == "2":
        test_specific_siret()
        return 0
    else:
        print("[ERREUR] Choix invalide. Lancement du mode complet...")
        scraper = PappersDirigeantScraper(
            input_csv='output_enriched.csv',
            output_csv='output_final.csv',
            headless=False
        )
        return 0 if scraper.process_csv() else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())