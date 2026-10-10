# Spécifications : Nœud de maintenance prédictive connecté

> Version mise à jour à partir des datasheets de l'**ADXL345** (Rev PrA, préliminaire) et du **STM32G474** (DS12288 Rev 6), et du calculateur de résolution FFT de rftools.io. Les valeurs de la colonne « Décision » sont à confirmer pendant les tests.

## 1. Objectif

Détecter des anomalies de fonctionnement d'une machine tournante (ventilateur ou petit moteur) à partir de ses vibrations, en temps réel sur STM32, avec remontée des données et des alertes vers un dashboard.

**Architecture :** ADXL345 → (SPI) STM32G474 [FreeRTOS, FFT, TinyML] → (UART) ESP32 [pont WiFi] → MQTT → InfluxDB → Grafana

## 2. Défauts à détecter

| Défaut | Comment le simuler | Signature attendue | Décision |
|--------|--------------------|--------------------|----------|
| Fonctionnement normal | Ventilateur seul | Pic stable à la fréquence de rotation | Retenu |
| Balourd | Masse (ruban, pâte adhésive) sur une pale | Pic plus fort à la fréquence de rotation | Retenu |
| Fixation desserrée | Vis de fixation desserrée | Harmoniques et bruit large bande | Retenu |
| Frottement / obstruction | Léger frottement sur une pale | Énergie accrue en hautes fréquences | Retenu |

## 3. Plateforme matérielle

| Élément | Choix | Source / justification |
|---------|-------|------------------------|
| Carte STM32 | NUCLEO-G474RE (STM32G474RE) | Cortex-M4 avec FPU et instructions DSP, 170 MHz, 512 Ko de Flash, 128 Ko de RAM |
| Capteur | ADXL345 (breakout), accéléromètre 3 axes | SPI ou I2C, FIFO de 32 niveaux, 3,3 V |
| WiFi | ESP32-C3 DevKit, pont WiFi uniquement | UART vers le STM32 |
| Alimentation | USB 5 V (Nucleo), capteur en 3,3 V | VS de l'ADXL345 : 2,0 à 3,6 V |
| Montage du capteur | Fixation rigide (vis ou colle) sur la machine | La datasheet déconseille un montage sur un support flexible |
| Horloge système | 170 MHz par défaut (mode Range 1 boost) | ≈ 29,5 mA à 170 MHz, ≈ 13 mA à 80 MHz (Table 21) : à réduire si l'autonomie compte |

## 4. Acquisition (ADXL345)

| Paramètre | Décision | Source |
|-----------|----------|--------|
| Interface | SPI 4 fils, **mode 3** (CPOL = 1, CPHA = 1) | Datasheet ADXL345 |
| Horloge SPI | ≈ 1,3 MHz (prescaler 128 depuis 170 MHz) | Max 5 MHz ; sous 1,5 MHz, l'adressage suffit à garantir le délai de 5 µs entre lectures de la FIFO |
| Fréquence de sortie (ODR) | **1600 Hz** (code `1110` dans `BW_RATE`) | Table 5 : bande passante = ODR / 2 = 800 Hz, ≈ 80 µA |
| Plage et résolution | ±4 g, `FULL_RES` activé (4 mg/LSB, 11 bits) | Table 1 de la datasheet |
| Axes | 3 (X, Y, Z) | |
| FIFO | Mode **Stream**, watermark à 16 échantillons | À 1600 Hz, la FIFO (32 niveaux) se remplit en 20 ms ; interruption toutes les 10 ms |
| Lecture | 16 rafales de 6 octets (registres 0x32 à 0x37), CS relevé entre chaque | Chaque entrée de FIFO doit être lue en rafale |
| Débit utile | ≈ 9,6 ko/s (1600 × 6 octets) | Très inférieur à la capacité du SPI |
| Test de communication | Lecture de `DEVID` (0x00) = **0xE5** | Datasheet ADXL345 |

## 5. Analyse fréquentielle (FFT)

Formule : résolution Δf = fs / N, durée de la fenêtre T = N / fs.

| Paramètre | Valeur | Calcul |
|-----------|--------|--------|
| Fréquence d'échantillonnage fs | 1600 Hz | ODR de l'ADXL345 |
| Fréquence de Nyquist | 800 Hz | fs / 2 |
| Taille de fenêtre N | **1024 points** | |
| Résolution Δf | **1,5625 Hz** | 1600 / 1024 |
| Durée d'une fenêtre | **0,64 s** | 1024 / 1600 |
| Fenêtrage | **Hann** | Lobes secondaires ≈ −31 dB (contre −13 dB en rectangulaire) |
| Résolution effective avec Hann | ≈ 2,3 Hz | Bande équivalente de bruit ≈ 1,5 bin, soit 1,5 × 1,5625 |
| Recouvrement | **50 %** | Nouveau spectre toutes les 0,32 s (512 nouveaux échantillons) |
| Zero-padding | Non utilisé | Il lisse l'affichage mais n'améliore pas la résolution réelle |

**Comparaison des tailles de fenêtre (fs = 1600 Hz)**

| N | Résolution Δf | Durée de fenêtre | Remarque |
|---|---------------|------------------|----------|
| 512 | 3,125 Hz | 0,32 s | Plus réactif, moins précis |
| **1024** | **1,5625 Hz** | **0,64 s** | **Retenu : bon compromis** |
| 2048 | 0,78125 Hz | 1,28 s | Plus précis, plus lent, calcul plus lourd |

**Mémoire (RAM de 128 Ko)** : une fenêtre de 1024 échantillons sur 3 axes occupe ≈ 6 Ko en entiers 16 bits, ≈ 12 Ko en flottants 32 bits, ce qui laisse une large marge. La FFT utilise **CMSIS-DSP** (le CORDIC et le FMAC du STM32G474 ne remplacent pas la FFT, mais le FMAC peut servir à du filtrage FIR/IIR).

## 6. Caractéristiques extraites (par fenêtre et par axe)

| Caractéristique | Rôle |
|-----------------|------|
| RMS | Niveau global de vibration |
| Valeur crête et facteur de crête | Détection de chocs |
| Kurtosis | Détection d'impulsions (desserrage, frottement) |
| Fréquence dominante | Vitesse de rotation, déséquilibre |
| Énergie par bandes de fréquence | Entrée principale du modèle |

## 7. Modèle TinyML

| Paramètre | Décision |
|-----------|----------|
| Classes | normal, balourd, desserrage, frottement |
| Entrées | Caractéristiques de la section 6 |
| Outil d'entraînement | Edge Impulse ou Python (TensorFlow) |
| Déploiement | X-CUBE-AI ou TFLite Micro |
| Précision cible | ≥ 90 % sur un jeu de test séparé |
| Latence d'inférence | < 100 ms |
| Mémoire du modèle | < 50 Ko de RAM |

## 8. Communication

| Élément | Décision | Source |
|---------|----------|--------|
| Liaison STM32 ↔ ESP32 | UART 115200 bauds, 8N1, en DMA | 3 USART + 2 UART avec FIFO et DMA |
| Trame | En-tête, longueur, type, données, **CRC16** | Unité CRC matérielle (polynôme configurable) |
| Fréquence d'envoi | 1 trame par seconde (caractéristiques + classe) | |
| MQTT, télémétrie | `nodes/<id>/telemetry` (QoS 0) | |
| MQTT, alertes | `nodes/<id>/alert` (QoS 1) | |
| Reconnexion WiFi | Automatique, avec tampon local | |

## 9. Mise à jour OTA

| Élément | Décision | Source |
|---------|----------|--------|
| Source du firmware | Téléchargé par l'ESP32, transmis à l'STM32 par UART | |
| Organisation de la Flash | **Mode double banque** (2 × 256 Ko) : écriture dans la banque inactive, puis bascule | Lecture pendant écriture et boot double banque pris en charge |
| Taille maximale de l'application | < 256 Ko | |
| Contrôle d'intégrité | **CRC32** (unité matérielle) | |
| Authenticité | Signature **ECDSA P-256** vérifiée par le bootloader, **en logiciel** | Pas d'accélérateur cryptographique listé (seuls RNG et CRC) |
| Protection du code | Niveau de protection en lecture (RDP) à étudier, zone mémoire sécurisable pour la clé publique | Datasheet STM32G474 |
| Retour arrière | Conserver l'ancienne version si la validation échoue | |
| Endurance Flash | 10 000 cycles d'écriture : suffisant pour des mises à jour occasionnelles | Table 48 |

## 10. Exigences générales

| Exigence | Valeur |
|----------|--------|
| Alimentation | USB 5 V |
| Robustesse | Watchdog indépendant (IWDG), reprise automatique après coupure |
| Journalisation | Logs sur UART de debug |
| Configuration | Paramètres modifiables par commande série |

## 11. Critères de validation

| Test | Critère de réussite |
|------|---------------------|
| Communication capteur | `DEVID` = 0xE5 lu correctement |
| Cadence d'acquisition | 1600 échantillons/s sans perte (pas de dépassement de FIFO, drapeau OVERRUN absent) |
| Résolution spectrale | Pic d'un signal de test détecté à ± 1,6 Hz |
| Précision de la classification | ≥ 90 % sur le jeu de test |
| Perte de trames UART | < 1 % |
| Latence acquisition → dashboard | < 3 s |
| OTA | Mise à jour réussie, et rejet d'un firmware non signé |
| Coupure WiFi de 5 min | Aucune donnée perdue après reconnexion |

## 12. Points à vérifier

| Point | Action |
|-------|--------|
| La datasheet de l'ADXL345 utilisée est une **version préliminaire (Rev PrA, 2008)** | Comparer avec la dernière version sur le site d'Analog Devices |
| Bruit de l'ADXL345 à 1600 Hz | Mesurer le bruit réel sur la machine à l'arrêt |
| Horloge système | Tester 80 MHz et 170 MHz selon la charge CPU mesurée |
| Choix de la bibliothèque ECDSA | Comparer micro-ecc et mbedTLS (taille, vitesse) |

## 13. Sources

| Source | Usage |
|--------|-------|
| Datasheet ADXL345 (alldatasheet.com) | Registres, ODR, SPI, FIFO |
| Datasheet STM32G474xB/xC/xE, DS12288 Rev 6 (st.com) | Cœur, mémoires, périphériques, consommation |
| rftools.io, calculateur de résolution FFT | Δf = fs / N, fenêtrage, zero-padding |
