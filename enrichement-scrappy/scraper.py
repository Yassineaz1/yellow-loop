import csv
import time
import os
import logging
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup
import re
import random

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BusinessScraper:
    def __init__(self, input_csv='input.csv', output_csv='output_enriched.csv', headless=True):
        self.input_csv = input_csv
        self.output_csv = output_csv
        self.headless = headless
        self.driver = None
        self.page_count = 0
        self.chrome_options = None
        
    def setup_driver(self):
        """Configure le navigateur Chrome avec Undetected Chromedriver"""
        logger.info("Initialisation du navigateur Chrome (Undetected)...")
        
        chrome_options = uc.ChromeOptions()
        
        # Le mode headless est géré par uc.Chrome() au moment de l'instanciation
        # Mais on peut quand même ajouter l'argument ici
        if self.headless:
            chrome_options.add_argument('--headless')
        
        # undetected_chromedriver gère déjà la plupart de ces options
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.set_capability('pageLoadStrategy', 'eager')
        self.chrome_options = chrome_options
        
        # User-Agent moderne
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # Désactiver les images pour accélérer
        prefs = {
            'profile.managed_default_content_settings.images': 2,
            'profile.default_content_setting_values.notifications': 2,
            'profile.managed_default_content_settings.stylesheets': 2,
            'profile.managed_default_content_settings.javascript': 1,  # IMPORTANT: Garder JS activé
        }
        chrome_options.add_experimental_option('prefs', prefs)

        # Options de stabilité et anti-détection avancées
        chrome_options.add_argument('--disable-background-networking')
        chrome_options.add_argument('--disable-default-apps')
        chrome_options.add_argument('--disable-sync')
        chrome_options.add_argument('--disable-translate')
        chrome_options.add_argument('--metrics-recording-only')
        chrome_options.add_argument('--safebrowsing-disable-auto-update')

        # Désactiver WebRTC en profondeur pour éviter les erreurs STUN et améliorer l'anonymat
        chrome_options.add_argument('--disable-webrtc')
        chrome_options.add_argument('--disable-features=WebRtcHideLocalIpsWithMdns')
        chrome_options.add_argument('--disable-p2p-sockets')
        chrome_options.add_argument('--disable-webrtc-hw-encoding')
        chrome_options.add_argument('--disable-webrtc-hw-decoding')
        chrome_options.add_argument('--log-level=3') # Réduire la verbosité des logs Chrome
        
        try:
            logger.info("Telechargement du driver via webdriver-manager...")
            from webdriver_manager.chrome import ChromeDriverManager
            driver_path = ChromeDriverManager().install()
            
            logger.info(f"Lancement de Undetected Chromedriver avec le binaire : {driver_path}")
            self.driver = uc.Chrome(
                driver_executable_path=driver_path,
                options=chrome_options,
                headless=self.headless,
                use_subprocess=True,
                version_main=148
            )
            self.driver.set_page_load_timeout(30)
            
            logger.info("Navigateur Chrome initialise avec succes (Mode Undetected)")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation du navigateur: {e}")
            return False 
    
    def extract_legal_info(self, url):
        """Extrait les informations legales d'une page detaillee - VERSION ULTRA-STABLE"""
        # 0. Gestion de la rotation de session (toutes les 25 pages)
        self.page_count += 1
        if self.page_count > 1 and self.page_count % 25 == 0:
            logger.info(f"Rotation de session (Page #{self.page_count}). Redemarrage du navigateur...")
            try:
                self.driver.quit()
                time.sleep(2)
                self.setup_driver()
            except Exception as e:
                logger.error(f"Erreur lors du redemarrage du navigateur: {e}")

        # Pause aleatoire pour simuler un humain (5 a 12 secondes)
        wait_time = random.uniform(5, 12)
        logger.info(f"Pause pre-chargement: {wait_time:.1f}s")
        time.sleep(wait_time)

        try:
            logger.info(f"Chargement de la page: {url}")
            
            # Naviguer avec Referer Google
            try:
                self.driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {
                    'headers': {'Referer': 'https://www.google.com/'}
                })
            except: pass
            
            self.driver.get(url)
            
            # 1. Gestion avancee des challenges Cloudflare
            start_wait = time.time()
            while time.time() - start_wait < 20: # Attendre max 20s
                if "Just a moment" not in self.driver.title and "challenge-running" not in self.driver.page_source:
                    break
                logger.info("Attente de la resolution du challenge Cloudflare...")
                time.sleep(3)
                if time.time() - start_wait > 15:
                    self.driver.refresh() # Tenter un refresh si ca bloque trop longtemps
            
            # 1. Gérer les cookies (si présent)
            try:
                cookie_button = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button"))
                )
                cookie_button.click()
                logger.info("Cookies acceptes")
                time.sleep(1)
            except:
                pass

            # 3. Scroller pour charger tout le contenu (important pour les zones B2B/INSEE lazy-loadées)
            try:
                # Scroll erratique vers le bas (plus humain)
                total_height = self.driver.execute_script("return document.body.scrollHeight")
                curr = 0
                while curr < total_height:
                    step = random.randint(500, 1500)
                    curr += step
                    self.driver.execute_script(f"window.scrollTo(0, {curr});")
                    time.sleep(random.uniform(0.2, 0.5))
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
            except:
                pass

            # 3. Attendre que la page soit prête
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
            except TimeoutException:
                logger.warning("Page lente a charger, continuation...")
            
            # 3. Rechercher et étendre la zone B2B / Legal Info
            zone_b2b = None
            try:
                logger.info("⏳ Recherche de la zone B2B...")
                # Essayer différents sélecteurs pour la zone légale (B2B ou INSEE)
                selectors = [
                    (By.ID, "zoneB2B"),
                    (By.ID, "end-zoneB2B"),
                    (By.ID, "info-juridique"),
                    (By.CSS_SELECTOR, ".header-b2b"),
                    (By.CSS_SELECTOR, ".item-insee"),
                    (By.XPATH, "//button[contains(., 'Informations financières et juridiques')]"),
                    (By.XPATH, "//div[contains(., 'Informations financières et juridiques')]"),
                    (By.XPATH, "//a[contains(., 'Informations financières et juridiques')]"),
                    (By.XPATH, "//button[contains(., 'INSEE')]"),
                    (By.XPATH, "//a[contains(., 'INSEE')]"),
                    (By.CSS_SELECTOR, "a.ancre-btn-8.pj-link")
                ]
                
                for by, selector in selectors:
                    try:
                        zone_b2b = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((by, selector))
                        )
                        if zone_b2b:
                            logger.info(f"Zone B2B trouvee avec {selector}")
                            break
                    except:
                        continue
                
                if zone_b2b:
                    # Scroller vers la zone
                    self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", zone_b2b)
                    time.sleep(1)
                    
                    # Tenter de cliquer pour étendre
                    try:
                        # Chercher l'élément cliquable (bouton d'expansion ou onglet INSEE)
                        click_targets = [
                            "button", "a.item-insee", "li.item-insee", 
                            "a.ancre-btn-8.pj-link", "a[href='#end-zoneB2B']",
                            ".arrow", ".icon-arrow", "[role='button']"
                        ]
                        clicked = False
                        for target in click_targets:
                            try:
                                btn = zone_b2b.find_element(By.CSS_SELECTOR, target)
                                if btn.is_displayed():
                                    self.driver.execute_script("arguments[0].click();", btn)
                                    logger.info(f"Section etendue via {target}")
                                    clicked = True
                                    break
                            except: continue
                        
                        if not clicked:
                            self.driver.execute_script("arguments[0].click();", zone_b2b)
                            logger.info("Clic direct sur la zone B2B")
                            
                        # Attendre que le SIRET apparaisse dans le DOM (important pour les onglets)
                        logger.info("Attente du chargement des donnees...")
                        wait_start = time.time()
                        while time.time() - wait_start < 5:
                            if "SIRET" in self.driver.page_source or "SIREN" in self.driver.page_source:
                                logger.info("Donnees SIRET/SIREN detectees")
                                break
                            time.sleep(0.5)
                        time.sleep(1) 
                    except Exception as e:
                        logger.debug(f"Info: Pas pu cliquer sur l'extension: {e}")
                else:
                    logger.warning("Zone B2B non trouvee par les selecteurs directs")

            except Exception as e:
                logger.warning(f"⚠️ Erreur lors de la recherche B2B: {e}")
            
            # Récupérer TOUT le HTML de la page
            page_html = self.driver.page_source
            soup = BeautifulSoup(page_html, 'html.parser')
            
            # Initialiser les données
            data = {
                'SIRET': '',
                'Code_NAF': '',
                'Typologie': '',
                'SIREN': '',
                'Forme_juridique': '',
                'Creation_entreprise': '',
                'Autres_denominations': ''
            }
            
            # ========== EXTRACTION AMÉLIORÉE ==========
            
            # 1. Chercher DANS TOUTE LA PAGE avec regex AVANCÉES
            logger.info("🔍 Recherche approfondie des données...")
            
            # Chercher TOUS les nombres de 14 chiffres (SIRET possibles)
            siret_matches = re.findall(r'\b\d{14}\b', page_html)
            if siret_matches:
                logger.info(f"{len(siret_matches)} nombres de 14 chiffres trouves")
                for siret in siret_matches:
                    # Vérifier que c'est un SIRET valide (commence souvent par le SIREN)
                    if siret[:9].isdigit():
                        data['SIRET'] = siret
                        logger.info(f"SIRET potentiel trouve: {siret}")
                        break
            
            # Chercher TOUS les nombres de 9 chiffres (SIREN possibles)
            siren_matches = re.findall(r'\b\d{9}\b', page_html)
            if siren_matches:
                logger.info(f"{len(siren_matches)} nombres de 9 chiffres trouves")
                for siren in siren_matches:
                    # Vérifier que c'est un SIREN plausible
                    if siren.isdigit():
                        data['SIREN'] = siren
                        logger.info(f"SIREN potentiel trouve: {siren}")
                        break
            
            # 2. Extraction STRUCTURÉE (méthode originale)
            info_etablissement = soup.find('dl', class_='info-etablissement')
            if info_etablissement:
                logger.info("Section info-etablissement trouvee")
                
                # Chercher SIRET spécifiquement
                siret_elem = info_etablissement.find('dt', string=lambda text: 'SIRET' in str(text))
                if siret_elem:
                    dd_siret = siret_elem.find_next_sibling('dd')
                    if dd_siret:
                        strong_siret = dd_siret.find('strong')
                        if strong_siret:
                            data['SIRET'] = strong_siret.get_text(strip=True)
                            logger.info(f"SIRET structure: {data['SIRET']}")
                
                # Chercher Code NAF
                naf_elem = info_etablissement.find('dt', string=lambda text: 'NAF' in str(text))
                if naf_elem:
                    dd_naf = naf_elem.find_next_sibling('dd')
                    if dd_naf:
                        strong_naf = dd_naf.find('strong')
                        if strong_naf:
                            data['Code_NAF'] = strong_naf.get_text(strip=True)
                
                # Chercher Typologie
                typo_elem = info_etablissement.find('dt', string=lambda text: 'Typologie' in str(text))
                if typo_elem:
                    dd_typo = typo_elem.find_next_sibling('dd')
                    if dd_typo:
                        strong_typo = dd_typo.find('strong')
                        if strong_typo:
                            data['Typologie'] = strong_typo.get_text(strip=True)
            
            info_entreprise = soup.find('dl', class_='info-entreprise')
            if info_entreprise:
                logger.info("Section info-entreprise trouvee")
                
                # Chercher SIREN spécifiquement
                siren_elem = info_entreprise.find('dt', string=lambda text: 'SIREN' in str(text))
                if siren_elem:
                    dd_siren = siren_elem.find_next_sibling('dd')
                    if dd_siren:
                        strong_siren = dd_siren.find('strong')
                        if strong_siren:
                            data['SIREN'] = strong_siren.get_text(strip=True)
                            logger.info(f"SIREN structure: {data['SIREN']}")
                
                # Chercher Forme juridique
                forme_elem = info_entreprise.find('dt', string=lambda text: 'Forme juridique' in str(text))
                if forme_elem:
                    dd_forme = forme_elem.find_next_sibling('dd')
                    if dd_forme:
                        strong_forme = dd_forme.find('strong')
                        if strong_forme:
                            data['Forme_juridique'] = strong_forme.get_text(strip=True)
                
                # Chercher Date création
                date_elem = info_entreprise.find('dt', string=lambda text: 'Création' in str(text))
                if date_elem:
                    dd_date = date_elem.find_next_sibling('dd')
                    if dd_date:
                        strong_date = dd_date.find('strong')
                        if strong_date:
                            data['Creation_entreprise'] = strong_date.get_text(strip=True)
                
                # Chercher Autres dénominations
                autres_elem = info_entreprise.find('dt', string=lambda text: 'Autres dénominations' in str(text))
                if autres_elem:
                    dd_autres = autres_elem.find_next_sibling('dd')
                    if dd_autres:
                        # Chercher spécifiquement la classe 'value'
                        value_elem = dd_autres.find('strong', class_='value')
                        if value_elem:
                            data['Autres_denominations'] = value_elem.get_text(strip=True)
                        else:
                            # Fallback: prendre tout le texte
                            strong_autres = dd_autres.find('strong')
                            if strong_autres:
                                data['Autres_denominations'] = strong_autres.get_text(strip=True)
            
            # 3. VÉRIFICATION ET CORRECTION DES DONNÉES
            logger.info("Verification des donnees extraites...")
            
            # Si on a SIREN mais pas SIRET, on peut essayer de le reconstruire
            if data['SIREN'] and not data['SIRET'] and siret_matches:
                logger.info("Tentative de reconstruction du SIRET...")
                for siret in siret_matches:
                    if siret.startswith(data['SIREN']):
                        data['SIRET'] = siret
                        logger.info(f"✅ SIRET reconstruit: {siret}")
                        break
            
            # Nettoyage des données
            for key in data:
                if data[key]:
                    data[key] = data[key].strip()
            
            # 4. LOG DES RÉSULTATS
            if data['SIRET'] or data['SIREN']:
                logger.info(f"DONNEES EXTRAITES:")
                if data['SIRET']:
                    logger.info(f"   SIRET: {data['SIRET']}")
                if data['SIREN']:
                    logger.info(f"   SIREN: {data['SIREN']}")
                if data['Code_NAF']:
                    logger.info(f"   Code NAF: {data['Code_NAF']}")
                if data['Forme_juridique']:
                    logger.info(f"   Forme juridique: {data['Forme_juridique']}")
                if data['Creation_entreprise']:
                    logger.info(f"   Date création: {data['Creation_entreprise']}")
            else:
                logger.warning("⚠️ Aucun SIRET/SIREN trouvé")
                # Afficher un extrait du HTML pour debug
                html_preview = page_html[:500].replace('\n', ' ').replace('\r', ' ')
                logger.debug(f"HTML preview: {html_preview}...")
            
            return data
            
        except TimeoutException:
            logger.error("⏱ Timeout lors du chargement de la page")
            return None
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'extraction: {e}")
            return None
    
    def process_csv(self):
        """Traite le CSV d'entrée et crée le CSV enrichi"""
        if not os.path.exists(self.input_csv):
            logger.error(f"❌ Fichier {self.input_csv} introuvable!")
            return
        
        # Initialiser le navigateur
        if not self.setup_driver():
            logger.error("❌ Impossible d'initialiser le navigateur. Arrêt du script.")
            return
        
        try:
            # Lire le CSV d'entrée
            businesses = []
            with open(self.input_csv, 'r', encoding='utf-8') as f:
                # Détecter automatiquement le délimiteur
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
            
            logger.info(f"📊 {len(businesses)} entreprises à traiter")
            
            # Ajouter les nouvelles colonnes
            new_fieldnames = list(fieldnames) + [
                'SIRET', 'Code_NAF', 'Typologie', 'SIREN', 
                'Forme_juridique', 'Creation_entreprise', 'Autres_denominations'
            ]
            
            # Traiter chaque entreprise
            total = len(businesses)
            success_count = 0
            fail_count = 0
            
            for idx, business in enumerate(businesses, 1):
                nom = business.get('Nom de l\'entreprise', f'Entreprise #{idx}')
                
                logger.info(f"\n{'='*60}")
                logger.info(f"[{idx}/{total}] {nom}")
                logger.info(f"{'='*60}")
                
                url = business.get('Lien détaillé', '').strip()
                if not url:
                    logger.warning("⚠ Pas de lien détaillé")
                    fail_count += 1
                    continue
                
                # Extraire les informations
                legal_info = self.extract_legal_info(url)
                
                if legal_info:
                    business.update(legal_info)
                    
                    # Compter comme succès si on a au moins SIRET ou SIREN
                    if legal_info.get('SIRET') or legal_info.get('SIREN'):
                        success_count += 1
                        logger.info(f"✅ Succès #{success_count}")
                    else:
                        fail_count += 1
                        logger.warning(f"❌ Aucune donnée trouvée")
                else:
                    # Ajouter des valeurs vides si échec
                    business.update({
                        'SIRET': '', 'Code_NAF': '', 'Typologie': '',
                        'SIREN': '', 'Forme_juridique': '', 
                        'Creation_entreprise': '', 'Autres_denominations': ''
                    })
                    fail_count += 1
                    logger.warning(f"❌ Échec #{fail_count}")
                
                # Sauvegarder progressivement
                if idx % 5 == 0:
                    self.save_progress(businesses, new_fieldnames)
                    logger.info(f"💾 Sauvegarde intermédiaire ({idx}/{total})")
                
                # Pause entre les requêtes (éviter le blocage)
                if idx < total:
                    pause_time = 2.5
                    logger.info(f"⏱ Pause de {pause_time}s...")
                    time.sleep(pause_time)
            
            # Sauvegarde finale
            self.save_progress(businesses, new_fieldnames)
            
            # STATISTIQUES FINALES
            logger.info(f"\n{'='*60}")
            logger.info(f"✅ TRAITEMENT TERMINÉ!")
            logger.info(f"{'='*60}")
            
            with_siret = sum(1 for b in businesses if b.get('SIRET'))
            with_siren = sum(1 for b in businesses if b.get('SIREN'))
            with_any = sum(1 for b in businesses if b.get('SIRET') or b.get('SIREN'))
            
            logger.info(f"RESULTATS:")
            logger.info(f"   Total traite: {total}")
            logger.info(f"   Avec SIRET: {with_siret} ({with_siret/total*100:.1f}%)")
            logger.info(f"   Avec SIREN: {with_siren} ({with_siren/total*100:.1f}%)")
            logger.info(f"   Avec donnees: {with_any} ({with_any/total*100:.1f}%)")
            logger.info(f"Fichier de sortie: {self.output_csv}")
            
            # Aperçu des résultats
            logger.info(f"\nAPERÇU DES 3 PREMIERES ENTREPRISES:")
            for i, b in enumerate(businesses[:3], 1):
                nom = b.get('Nom de l\'entreprise', 'N/A')[:40]
                siret = b.get('SIRET', 'N/A')
                siren = b.get('SIREN', 'N/A')
                logger.info(f"  {i}. {nom:42} | SIRET: {siret:14} | SIREN: {siren:9}")
            
            logger.info(f"{'='*60}")
            
        finally:
            # Fermer le navigateur
            if self.driver:
                logger.info("Fermeture du navigateur...")
                self.driver.quit()
    
    def save_progress(self, businesses, fieldnames):
        """Sauvegarde le progrès dans le CSV"""
        with open(self.output_csv, 'w', encoding='utf-8', newline='') as f:
            # On utilise extrasaction='ignore' pour éviter les crashs si des colonnes imprévues apparaissent
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(businesses)

# ========== FONCTION DE TEST RAPIDE ==========
def test_specific_url():
    """Teste une URL spécifique pour debug"""
    print("\n" + "="*60)
    print("TEST D'EXTRACTION SUR UNE URL SPECIFIQUE")
    print("="*60)
    
    # URL de test
    test_url = "https://www.pagesjaunes.fr/pros/51395148"
    print(f"URL de test: {test_url}")
    
    scraper = BusinessScraper(headless=True)  # Mode headless pour le test
    if scraper.setup_driver():
        print("\nExtraction en cours...")
        result = scraper.extract_legal_info(test_url)
        
        print("\nRESULTATS DU TEST:")
        print("-" * 40)
        if result:
            print(f"SIRET trouve: {result.get('SIRET', 'NON TROUVE')}")
            print(f"SIREN trouve: {result.get('SIREN', 'NON TROUVE')}")
            print(f"Date creation: {result.get('Creation_entreprise', 'N/A')}")
            print(f"Forme juridique: {result.get('Forme_juridique', 'N/A')}")
            print(f"Code NAF: {result.get('Code_NAF', 'N/A')}")
        else:
            print("Aucune donnee extraite")
        
        scraper.driver.quit()
    else:
        print("Impossible d'initialiser Chrome")

# ========== MAIN ==========
def main():
    print("=" * 60)
    print("SCRAPER D'INFORMATIONS ENTREPRISES - PAGES JAUNES")
    print("Version AMÉLIORÉE - Extraction SIRET/SIREN complète")
    print("=" * 60)
    print()
    print("Ameliorations principales:")
    print("   * Recherche regex AVANCEE dans tout le HTML")
    print("   * Reconstruction SIRET a partir du SIREN")
    print("   * Detection automatique des formats CSV")
    print("   * Sauvegarde tous les 5 resultats")
    print("   * Statistiques detaillees en fin de traitement")
    print()
    print("Options:")
    print("   1. Lancer le scraping complet")
    print("   2. Tester une URL spécifique")
    print()
    
    choix = input("Votre choix (1 ou 2): ").strip()
    
    if choix == "1":
        # Mode headless (True = invisible, plus rapide)
        headless = True
        
        scraper = BusinessScraper(
            input_csv='input.csv',
            output_csv='output_enriched.csv',
            headless=headless
        )
        
        scraper.process_csv()
    
    elif choix == "2":
        test_specific_url()
    
    else:
        print("Choix invalide. Lancement du mode complet...")
        scraper = BusinessScraper(
            input_csv='input.csv',
            output_csv='output_enriched.csv',
            headless=False  # Visible pour debug
        )
        scraper.process_csv()

if __name__ == "__main__":
    main()