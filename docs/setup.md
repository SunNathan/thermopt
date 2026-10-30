# Installation

## 1. Prérequis

- Home Assistant OS (ou Supervised) sur Raspberry Pi.
- **Home Assistant 2025.2 ou plus récent** (sous-entrées de configuration).
  À partir de **2026.11**, HACS devient le *Marketplace* intégré : les étapes
  ci-dessous restent valables, l'entrée se trouve juste dans
  *Paramètres → Marketplace*.
- Les 2 modules NodOn SIN-4-FP-21 appairés dans Zigbee2MQTT, avec leurs entités
  visibles dans Home Assistant :
  - `select.<radiateur>_pilot_wire_mode`
  - `switch.<radiateur>`
  - `sensor.<radiateur>_power`, `sensor.<radiateur>_energy`
- Une intégration météo fournissant des prévisions horaires (`met.no` convient).

## 2. Installer HACS (Home Assistant 2026.10 ou antérieur)

1. *Paramètres → Modules complémentaires → Boutique* → ⋮ →
   *Dépôts* → ajouter `https://github.com/hacs/addons`.
2. Installer et démarrer **Get HACS**, puis lire les journaux du module.
3. Redémarrer Home Assistant.
4. *Paramètres → Appareils et services → Ajouter une intégration → HACS*,
   puis valider l'authentification GitHub (code d'appareil).

## 3. Installer ThermOpt

1. HACS → ⋮ → *Dépôts personnalisés* → coller l'URL du dépôt → catégorie
   **Integration** → *Ajouter*.
2. Chercher **ThermOpt** → *Télécharger*.
3. Redémarrer Home Assistant (obligatoire : le code Python est chargé au démarrage).

## 4. Configurer

*Paramètres → Appareils et services → Ajouter une intégration → ThermOpt.*

**Étape 1 — Système**

| Champ | Valeur |
|---|---|
| Entité météo | votre intégration météo |
| Interrupteur auto/manuel | `input_boolean.thermopt_auto` (à créer, voir `ha_config/helpers.md`) |
| Présence continue | calendrier ou booléen de télétravail (optionnel) |
| Signal HC réel | `binary_sensor` Linky (optionnel, sert au diagnostic) |
| Prix HP / HC | tarif en vigueur (€/kWh) |
| Plages Heures Creuses | format `22:00-06:00, 12:00-14:00` — **à relever sur le Linky** |
| Consigne Confort | **20,5** (voir README) |
| Consigne Hors-gel | 7,0 |

**Étape 2 — Profil de confort**

Les valeurs par défaut reprennent le document de cadrage : 17 °C la nuit,
19,5 °C matin et soir, 17 °C en journée de semaine (19 °C le week-end et en
télétravail).

L'intégration journalise un avertissement si une cible n'est pas atteignable
avec l'échelle d'ordres choisie.

**Étape 3 — Pièces** (une sous-entrée par pièce, ajoutables ensuite à tout moment)

| Champ | Exemple |
|---|---|
| Nom | Salon |
| Capteur de température | `sensor.salon_temperature` |
| Capteur d'humidité | `sensor.salon_humidity` |
| Entité fil pilote (select) | `select.salon_pilot_wire_mode` |
| Relais du module (switch) | `switch.salon` |
| Puissance mesurée | `sensor.salon_power` |
| Énergie cumulée | `sensor.salon_energy` |
| Puissance nominale | 1500 W |
| Surface / volume | 20 m² / 50 m³ (prior du futur modèle) |

## 5. Sécurité indépendante (obligatoire)

1. Créer les deux helpers décrits dans `ha_config/helpers.md`.
2. Importer les blueprints :
   *Paramètres → Automatisations → Blueprints → Importer un blueprint*, coller
   l'URL brute de :
   - `blueprints/thermopt/watchdog.yaml`
   - `blueprints/thermopt/repli_planning.yaml`
3. Créer une automatisation à partir de chaque blueprint :
   - le watchdog une seule fois ;
   - le planning de repli **une fois par pièce**.

## 6. Vérifier

- `sensor.thermopt_statut` vaut `collecte` et `sensor.thermopt_dernier_cycle`
  avance toutes les 15 minutes.
- `binary_sensor.thermopt_mode_degrade` est à `off`.
- Test de panne : désactiver l'intégration (*Paramètres → Appareils et services
  → ThermOpt → Désactiver*). En moins de 20 minutes, `input_boolean.thermopt_repli`
  passe à `on`, une notification apparaît et le planning de repli applique ses
  ordres. Réactiver ensuite l'intégration : le repli se désarme seul.
- Test relais : mettre `switch.<radiateur>` à `off` → `mode_degrade` passe à
  `on` avec la raison `relay_off`, et le relais est remis en marche.

## 7. Diagnostic

*Paramètres → Appareils et services → ThermOpt → Télécharger les diagnostics*
donne la configuration résolue, l'échelle d'ordres, les plages HC, le profil,
la source de prévision météo et l'état de chaque pièce. Les prix sont masqués.
