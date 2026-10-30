# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
versionnage sémantique. La version de `custom_components/thermopt/manifest.json`
doit toujours correspondre au tag publié.

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
