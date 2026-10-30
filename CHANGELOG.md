# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
versionnage sémantique. La version de `custom_components/thermopt/manifest.json`
doit toujours correspondre au tag publié.

## [Unreleased]

### Ajouté

- **Phase B de l'app : configuration, perception et sécurité.**
  - interface web complète sous `ingress` (pièces, tarifs, profil de confort,
    consigne Confort), formulaires HTML sans JavaScript, listes d'entités
    proposées par domaine ;
  - validation à l'enregistrement réutilisant les modules partagés, avec les
    mêmes messages chiffrés que l'intégration ;
  - configuration persistée dans `/data/config.json` (sauvegardée avec l'app) ;
  - boucle 15 min alignée sur l'horloge, fuseau lu depuis Home Assistant ;
  - garde-fous portés à l'identique : plancher, hors-gel, fenêtre, override
    manuel, vérification d'effet ;
  - écritures via le proxy Supervisor, mode `actif` / `observation` depuis le
    tableau de bord ;
  - entités MQTT : statut, mode dégradé, prix, dernier cycle, et par pièce
    température, consigne minimale, sécurité, ordre appliqué, puissance ;
  - alertes d'exploitation : repli natif armé, ancienne intégration détectée.
- Les modules purs de l'intégration sont copiés tels quels dans l'image
  (`thermopt_lib`), sans duplication de code.

### Modifié

- Version portée à **0.3.0** (intégration et app).

### Sécurité, entités et tableau de bord

- `sensor.thermopt_pieces` : nombre de pièces, et attribut `rooms` (température,
  consignes, ordre demandé/appliqué, source, sécurité) — permet un tableau de
  bord sans coder en dur les `entity_id`.
- **Couche de sécurité active** : ThermOpt écrit désormais des ordres fil
  pilote, mais uniquement via les garde-fous (plancher de confort, hors-gel
  absolu). `pilotage_actif` passe à `on` avec `portee: securite`, et un mode
  `securite` (« Sécurité seule ») apparaît.
- `sensor.<piece>_securite` : `inactif` / `plancher` / `hors_gel` / `fenetre` /
  `override`, avec la raison en attribut.
- Détection de fenêtre ouverte : chute > 1,5 °C en 10 min → suspension 60 min.
- Détection d'override manuel : modification du `select` hors ThermOpt → pièce
  gelée 2 h (le hors-gel absolu reste prioritaire).
- Vérification d'effet : ordre chauffant sans puissance mesurée au bout de
  15 min → `no_effect` + alerte.
- Bouton **« Exporter l'historique »** : CSV du buffer 5 min dans
  `/config/thermopt_exports/`, base de l'identification du modèle (jalon 3).
- Les garde-fous ne sont jamais bloqués par une situation dégradée : une pièce
  froide est secourue même si le profil de confort est incohérent.

### Corrigé

- Le bouton génère désormais un **tableau de bord complet** (`title` + `views`)
  et non un fragment de vue : coller une liste là où Home Assistant attend un
  objet produisait « Expected an object, but received: [object Object] ».
- `content: >-` remplacé par `content: |` dans les cartes markdown : le
  repliement des sauts de ligne cassait la mise en forme (titres, listes).
- Le YAML généré est validé (`yaml.safe_load` + présence de `views`) avant
  publication ; en cas d'échec, le bouton le signale au lieu de publier.
- Messages de dégradation lisibles avec les valeurs et la correction à
  appliquer (`degraded_detail`), exposés par `sensor.thermopt_statut` et
  `binary_sensor.thermopt_mode_degrade`.
- Attribut `raison` sur `sensor.thermopt_statut`, pour que le dashboard dépende
  d'une seule entité stable.
- `binary_sensor.thermopt_pilotage_actif` : dit explicitement si ThermOpt
  pilote le chauffage, avec la raison en attribut.
- `sensor.thermopt_statut` devient un capteur énuméré lisible
  (`observation`, `pilotage`, `repli`, `manuel`, `degrade`), traduit en FR/EN.
- `sensor.thermopt_derniere_commande` : horodatage de la dernière commande
  écrite par ThermOpt, avec pièce / ordre / résultat / source.
- Par pièce, l'ordre **demandé** et l'ordre **appliqué** sont désormais
  distincts, avec la source (`thermopt`, `manuel`, `repli`, `inconnue`).
- Champ « Pièce Home Assistant » par pièce : l'appareil ThermOpt est rattaché à
  la bonne zone (`suggested_area`), sans déplacer les appareils existants.
- Flux « Remplir depuis une pièce » : pré-remplissage des entités en scannant
  une zone (module fil pilote détecté par son option `frost_protection`,
  relais, puissance, énergie, capteurs).
- Vue Lovelace prête à coller : `dashboards/thermopt.yaml`.
- Bouton « Générer la vue » : YAML adapté aux noms réels de tes pièces.

### Modifié

- `sensor.<piece>_ordre_fil_pilote` devient `sensor.<piece>_ordre_applique`
  (renommage, aucune release publiée à ce stade).
- Le helper de repli est configurable (défaut `input_boolean.thermopt_repli`).

## [0.1.0] — 2026-10-30

Premier jalon : squelette installable, perception et repli. **Aucun ordre fil
pilote n'est appliqué par l'intégration.**

### Ajouté

- Intégration custom `thermopt` : config flow en deux étapes, sous-entrées par
  pièce, options flow, rechargement à chaud.
- Échelle d'ordres dérivée de la consigne Confort du radiateur
  (`C = 20,5 °C` par défaut) et détection des profils de confort incohérents.
- Perception : prévision météo horaire avec repli sur cache puis sinusoïde,
  plages Heures Creuses avec passage de minuit, profil de confort
  semaine/week-end/télétravail, détection de capteur figé ou absent.
- Buffer d'échantillons à 5 minutes par pièce (auto-décimé, persisté via
  `Store`), incluant puissance et énergie mesurées par le module fil pilote.
- Driver fil pilote `select` (Zigbee2MQTT) avec liste blanche sans `off`,
  dwell time et limite de changement.
- Garde-fou relais : détection d'un `switch` coupé, alerte et remise en marche.
- Entités : statut, battement de cœur, prix, température extérieure, mode
  dégradé, heures creuses, et 10 entités par pièce.
- Boutons de diagnostic (forcer un cycle, dumper l'état) et diagnostics
  téléchargeables.
- Blueprints indépendants : watchdog du superviseur et planning de repli.
- CI : ruff, mypy, pytest, hassfest, validation HACS ; workflow de release
  vérifiant la cohérence tag ↔ manifest.
- 74 tests, dont des tests d'intégration Home Assistant (config flow, setup,
  entités, garde-fous).

### Notes

- `off` n'est jamais émis : c'est une coupure, pas un ordre fil pilote.
- HACS devient le Marketplace intégré à partir de Home Assistant 2026.11 ; les
  procédures restent valables.
