import csv
import re
import os
import logging
from pathlib import Path

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cleaner.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class CSVCleaner:
    def __init__(self, input_csv='output_final.csv'):
        self.input_csv = input_csv
        self.output_csv = None  # Sera défini par l'utilisateur
        
        # Mots-clés et phrases à exclure des noms de dirigeants
        self.exclusion_phrases = [
            'il sagit du nom de naissance',
            'nom de naissance du dirigeant',
            'nom de naissance',
            'dirigeant',
            'voir plus',
            'tous les',
            'autres personnes',
        ]
        
        self.exclusion_keywords = [
            'président', 'directeur', 'gérant', 'administrateur', 'commissaire',
            'société', 'entreprise', 'sarl', 'sas', 'sa', 'eurl', 'sci',
            'représentant', 'monsieur', 'madame', 'mademoiselle',
        ]
        
    def print_banner(self):
        """Affiche une bannière stylisée"""
        banner = """
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║              🧹 NETTOYAGE ET FILTRAGE DE CSV 🧹                ║
║                                                                ║
║    Supprime les entreprises sans téléphone ou dirigeant       ║
║    Nettoie et formate les numéros de téléphone                ║
║    Extrait UN SEUL nom de dirigeant valide                    ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
"""
        print(banner)
        logger.info("Démarrage du nettoyage CSV")
    
    def clean_phone_number(self, phone):
        """Nettoie un numéro de téléphone"""
        if not phone:
            return ''
        
        # Supprimer tout ce qui n'est pas un chiffre ou un + (pour international)
        # Garder uniquement les chiffres
        cleaned = re.sub(r'[^\d+]', '', phone)
        
        # Si le numéro commence par +33, le convertir en 0
        if cleaned.startswith('+33'):
            cleaned = '0' + cleaned[3:]
        elif cleaned.startswith('0033'):
            cleaned = '0' + cleaned[4:]
        
        # Garder uniquement les chiffres (pas de +)
        cleaned = re.sub(r'[^\d]', '', cleaned)
        
        # Vérifier que c'est un numéro français valide (10 chiffres commençant par 0)
        if len(cleaned) == 10 and cleaned.startswith('0'):
            return cleaned
        
        # Si c'est un numéro court (service client, etc.), on peut le garder
        if len(cleaned) >= 8:
            return cleaned
        
        return ''
    
    def is_valid_person_name(self, name):
        """
        Valide qu'une chaîne est bien un nom et prénom de personne
        Critères stricts:
        - Contient exactement 2 mots ou plus (nom + prénom minimum)
        - Chaque mot commence par une majuscule
        - Pas de mots réservés (fonctions, titres)
        - Longueur raisonnable
        """
        if not name or not isinstance(name, str):
            return False
        
        # Nettoyer le nom
        name = name.strip()
        
        # Vérifier la longueur
        if len(name) < 5 or len(name) > 60:
            return False
        
        # Séparer en mots
        words = name.split()
        
        # Il faut au moins 2 mots (prénom + nom)
        if len(words) < 2:
            return False
        
        # Vérifier chaque mot
        for word in words:
            # Chaque mot doit avoir au moins 2 caractères
            if len(word) < 2:
                return False
            
            # Chaque mot doit commencer par une majuscule
            if not word[0].isupper():
                return False
            
            # Le reste doit être en minuscules (sauf particules comme "De", "Le")
            # On accepte aussi les noms composés avec tirets
            if not word[1:].replace('-', '').replace("'", '').isalpha():
                return False
            
            # Vérifier qu'il ne contient pas de mots-clés exclus
            word_lower = word.lower()
            if word_lower in self.exclusion_keywords:
                return False
        
        # Vérifier qu'il n'y a pas de chiffres
        if any(char.isdigit() for char in name):
            return False
        
        # Vérifier qu'il n'y a pas de caractères spéciaux (sauf - et ')
        allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ -\'éèêëàâäùûüïîôöçÉÈÊËÀÂÄÙÛÜÏÎÔÖÇ')
        if not all(c in allowed_chars for c in name):
            return False
        
        return True
    
    def extract_single_valid_name(self, dirigeant_field):
        """
        Extrait UN SEUL nom valide depuis le champ dirigeant
        Gère les cas avec plusieurs noms séparés par ; ou des phrases parasites
        """
        if not dirigeant_field:
            return ''
        
        # Nettoyer les espaces
        dirigeant_field = dirigeant_field.strip()
        
        # Supprimer les phrases d'exclusion
        for phrase in self.exclusion_phrases:
            dirigeant_field = re.sub(phrase, '', dirigeant_field, flags=re.IGNORECASE)
        
        # Séparer par ; ou par des retours à la ligne
        potential_names = re.split(r'[;\n]', dirigeant_field)
        
        # Parcourir chaque nom potentiel
        for name in potential_names:
            name = name.strip()
            
            # Vérifier si c'est un nom valide
            if self.is_valid_person_name(name):
                # Nettoyer le nom final
                name = re.sub(r'\s+', ' ', name)  # Espaces multiples
                logger.info(f"      ✓ Nom valide extrait: {name}")
                return name
        
        # Si aucun nom valide n'a été trouvé
        logger.warning(f"      ✗ Aucun nom valide dans: {dirigeant_field[:50]}...")
        return ''
    
    def clean_dirigeant_name(self, dirigeant_field):
        """Nettoie et extrait un seul nom de dirigeant valide"""
        if not dirigeant_field:
            return ''
        
        # Extraire le premier nom valide
        valid_name = self.extract_single_valid_name(dirigeant_field)
        
        return valid_name
    
    def has_valid_phone(self, row):
        """Vérifie si la ligne a un téléphone valide"""
        phone = row.get('Téléphone', '').strip()
        
        if not phone:
            return False
        
        # Extraire le numéro si présent (format "Tél : 04 78...")
        phone_match = re.search(r'(\+?\d[\d\s\-\.\(\)]+)', phone)
        if phone_match:
            phone = phone_match.group(1)
        
        cleaned = self.clean_phone_number(phone)
        
        return len(cleaned) >= 8  # Au minimum 8 chiffres
    
    def has_valid_dirigeant(self, row):
        """Vérifie si la ligne a un nom de dirigeant valide"""
        dirigeant = row.get('Nom_Dirigeant', '').strip()
        
        if not dirigeant:
            return False
        
        # Nettoyer et extraire un nom valide
        cleaned_name = self.clean_dirigeant_name(dirigeant)
        
        # Vérifier que le nom nettoyé est valide
        return bool(cleaned_name) and self.is_valid_person_name(cleaned_name)
    
    def clean_row(self, row):
        """Nettoie une ligne du CSV"""
        cleaned_row = row.copy()
        
        # Nettoyer le téléphone
        phone = row.get('Téléphone', '').strip()
        if phone:
            # Extraire le numéro si présent
            phone_match = re.search(r'(\+?\d[\d\s\-\.\(\)]+)', phone)
            if phone_match:
                phone = phone_match.group(1)
            
            cleaned_phone = self.clean_phone_number(phone)
            cleaned_row['Téléphone'] = cleaned_phone
        
        # Nettoyer le nom du dirigeant
        dirigeant = row.get('Nom_Dirigeant', '').strip()
        if dirigeant:
            cleaned_dirigeant = self.clean_dirigeant_name(dirigeant)
            cleaned_row['Nom_Dirigeant'] = cleaned_dirigeant
        
        # Nettoyer les autres champs (supprimer espaces inutiles)
        for key in cleaned_row:
            if isinstance(cleaned_row[key], str):
                cleaned_row[key] = cleaned_row[key].strip()
        
        return cleaned_row
    
    def process_csv(self):
        """Traite le CSV : filtre et nettoie"""
        if not os.path.exists(self.input_csv):
            logger.error(f"❌ Fichier {self.input_csv} introuvable!")
            return False
        
        logger.info(f"📂 Lecture du fichier: {self.input_csv}")
        
        try:
            # Lire le CSV d'entrée
            with open(self.input_csv, 'r', encoding='utf-8') as f:
                # Détecter le délimiteur
                sample = f.read(1024)
                f.seek(0)
                delimiter = '\t' if '\t' in sample else ','
                
                reader = csv.DictReader(f, delimiter=delimiter)
                fieldnames = reader.fieldnames
                rows = list(reader)
            
            logger.info(f"📊 {len(rows)} entreprises trouvées")
            
            # Compteurs
            total = len(rows)
            removed_no_phone = 0
            removed_no_dirigeant = 0
            cleaned_dirigeant_count = 0
            kept = 0
            
            # Filtrer et nettoyer
            cleaned_rows = []
            
            logger.info("\n" + "="*60)
            logger.info("🔍 FILTRAGE ET NETTOYAGE EN COURS...")
            logger.info("="*60)
            
            for idx, row in enumerate(rows, 1):
                nom = row.get('Nom de l\'entreprise', f'Entreprise #{idx}')[:50]
                
                # Vérifier téléphone
                has_phone = self.has_valid_phone(row)
                
                # Décider si on garde la ligne (téléphone d'abord)
                if not has_phone:
                    logger.warning(f"[{idx}/{total}] ❌ {nom} - Pas de téléphone")
                    removed_no_phone += 1
                    continue
                
                # Afficher le dirigeant avant nettoyage
                dirigeant_avant = row.get('Nom_Dirigeant', '')[:60]
                if dirigeant_avant:
                    logger.info(f"[{idx}/{total}] 🔍 {nom}")
                    logger.info(f"      Avant: {dirigeant_avant}")
                
                # Nettoyer la ligne (y compris le dirigeant)
                cleaned_row = self.clean_row(row)
                
                # Vérifier si le dirigeant nettoyé est valide
                dirigeant_apres = cleaned_row.get('Nom_Dirigeant', '')
                
                if not dirigeant_apres:
                    logger.warning(f"      ❌ Pas de dirigeant valide après nettoyage")
                    removed_no_dirigeant += 1
                    continue
                
                # Afficher le résultat du nettoyage
                if dirigeant_avant != dirigeant_apres:
                    logger.info(f"      Après: {dirigeant_apres}")
                    cleaned_dirigeant_count += 1
                
                cleaned_rows.append(cleaned_row)
                kept += 1
                
                if idx % 20 == 0:
                    logger.info(f"\n  📊 Progression: {idx}/{total} traités, {kept} gardés\n")
            
            logger.info("="*60)
            logger.info(f"✅ Filtrage terminé!")
            logger.info("="*60)
            
            # Statistiques
            logger.info(f"\n📊 STATISTIQUES:")
            logger.info(f"   Total initial: {total}")
            logger.info(f"   ❌ Sans téléphone: {removed_no_phone} ({removed_no_phone/total*100:.1f}%)")
            logger.info(f"   ❌ Sans dirigeant valide: {removed_no_dirigeant} ({removed_no_dirigeant/total*100:.1f}%)")
            logger.info(f"   🧹 Noms dirigeants nettoyés: {cleaned_dirigeant_count}")
            logger.info(f"   ✅ Gardées: {kept} ({kept/total*100:.1f}%)")
            
            # Demander le nom du fichier de sortie
            logger.info("\n" + "="*60)
            logger.info("💾 SAUVEGARDE")
            logger.info("="*60)
            
            default_name = "output_cleaned.csv"
            print(f"\n📝 Nom du fichier de sortie (par défaut: {default_name})")
            output_name = input("   Votre choix (Entrée pour défaut): ").strip()
            
            if not output_name:
                output_name = default_name
            
            # Ajouter .csv si absent
            if not output_name.endswith('.csv'):
                output_name += '.csv'
            
            self.output_csv = output_name
            
            # Sauvegarder
            with open(self.output_csv, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(cleaned_rows)
            
            logger.info(f"\n✅ Fichier sauvegardé: {self.output_csv}")
            
            # Aperçu des résultats
            if cleaned_rows:
                logger.info(f"\n📋 APERÇU DES 5 PREMIÈRES ENTREPRISES:")
                for i, row in enumerate(cleaned_rows[:5], 1):
                    nom = row.get('Nom de l\'entreprise', 'N/A')[:35]
                    phone = row.get('Téléphone', 'N/A')[:12]
                    dirigeant = row.get('Nom_Dirigeant', 'N/A')[:25]
                    logger.info(f"   {i}. {nom:37} | Tél: {phone:12} | Dir: {dirigeant}")
            
            logger.info("\n" + "="*60)
            logger.info("🎉 NETTOYAGE TERMINÉ AVEC SUCCÈS!")
            logger.info("="*60)
            logger.info(f"📂 Fichier d'entrée: {self.input_csv}")
            logger.info(f"📤 Fichier de sortie: {self.output_csv}")
            logger.info(f"📊 {kept} entreprises valides exportées")
            logger.info("="*60)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur lors du traitement: {e}", exc_info=True)
            return False


def test_phone_cleaning():
    """Teste le nettoyage des numéros de téléphone"""
    print("\n" + "="*60)
    print("🧪 TEST DE NETTOYAGE DES NUMÉROS")
    print("="*60)
    
    cleaner = CSVCleaner()
    
    test_cases = [
        "Tél : 04 78 78 84 10",
        "04 72 37 12 31",
        "+33 4 78 25 18 62",
        "0033478251862",
        "04.78.25.96.18",
        "04-78-25-96-18",
        "Tél : 0 820 25 02 77 Service...",
        "04 37 65 34 85",
        "",
        "N/A"
    ]
    
    for phone in test_cases:
        cleaned = cleaner.clean_phone_number(phone)
        print(f"Avant: {phone:40} → Après: {cleaned}")
    
    print("="*60)


def test_dirigeant_cleaning():
    """Teste le nettoyage des noms de dirigeants"""
    print("\n" + "="*60)
    print("🧪 TEST DE NETTOYAGE DES DIRIGEANTS")
    print("="*60)
    
    cleaner = CSVCleaner()
    
    test_cases = [
        "Martins Francisco ; Martins Louis",
        "DEWAELE Bernadette ; DEWAELE BernadetteRinneckerIl sagit du nom de naissance du dirigeant ; Dewaele Philippe",
        "Deleens Valentin",
        "SANNIER Stephanie ; Sannier Pascal ; SANNIER StephanieAlloryIl sagit du nom de naissance du dirigeant",
        "Lecrique Olivier",
        "TRIBAUDEAUT Emmanuel ; TRIBAUDEAUT EmmanuelTribaudeautIl sagit du nom de naissance du dirigeant ; BERTRAND Arnault",
        "Jean Dupont",
        "Président Directeur Général",
        "SARL DUPONT",
        "Marie-Claire Dubois",
        "",
    ]
    
    print("\nRésultats du nettoyage:\n")
    for dirigeant in test_cases:
        cleaned = cleaner.clean_dirigeant_name(dirigeant)
        print(f"Avant: {dirigeant[:60]:62}")
        print(f"Après: {cleaned if cleaned else '[REJETÉ]':62}")
        print(f"Valide: {'✅ OUI' if cleaned else '❌ NON'}")
        print("-" * 70)
    
    print("="*60)


def main():
    """Point d'entrée principal"""
    cleaner = CSVCleaner(input_csv='output_final.csv')
    
    cleaner.print_banner()
    
    print("Options:")
    print("  1. Nettoyer le CSV (mode normal)")
    print("  2. Tester le nettoyage des téléphones")
    print("  3. Tester le nettoyage des dirigeants")
    print()
    
    choix = input("Votre choix (1, 2 ou 3, Entrée pour 1): ").strip()
    
    if choix == "2":
        test_phone_cleaning()
    elif choix == "3":
        test_dirigeant_cleaning()
    else:
        success = cleaner.process_csv()
        
        if success:
            print("\n✅ Nettoyage terminé avec succès!")
            return 0
        else:
            print("\n❌ Erreur lors du nettoyage")
            return 1


if __name__ == "__main__":
    exit(main())