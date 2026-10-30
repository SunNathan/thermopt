# ThermOpt

Supervision du chauffage fil pilote. Application Home Assistant, installée
depuis ce dépôt.

> **Projet personnel — POC.** Développé avec OpenCode pour un usage domestique.
> Ce n'est ni testé, ni supporté. Ne l'utilise pas sur une installation dont
> dépend le chauffage de quelqu'un d'autre.

## Ce que fait l'application

| Phase | État |
|---|---|
| A — squelette | installable, page d'administration, capteur de santé |
| B — perception | lecture capteurs, météo, tarifs |
| C — sécurité | garde-fous : plancher de confort, hors-gel |
| D — configuration | interface complète (pièces, profils, tarifs) |
| E — optimisation | modèle thermique et MPC |

L'application publie ses entités dans Home Assistant via **MQTT discovery** :
elles se comportent comme des entités natives, utilisables dans n'importe quelle
carte ou automatisation.

## Prérequis

- Home Assistant OS ou Supervised.
- Un broker MQTT (Mosquitto). Il est déjà présent si tu utilises
  Zigbee2MQTT — les identifiants sont fournis automatiquement par le
  Supervisor, rien à saisir.
- Les modules fil pilote (NodOn SIN-4-FP-21) exposés par Zigbee2MQTT.

## Installation

1. **Paramètres → Apps → Installer une app**, puis ⋮ → **Dépôts**.
2. Ajouter `https://github.com/SunNathan/thermopt`.
3. Installer **ThermOpt**, démarrer, puis **Ouvrir l'interface web**.

## Configuration

Les options de l'app (engrenage sur sa page) ne contiennent que le niveau de
journalisation. La configuration des pièces se fait dans l'interface web, qui
arrive à la phase D.

## Entités publiées

Au démarrage : `sensor.thermopt_app` (`ok` / `degraded`), avec la version, la
version de Home Assistant et l'état MQTT en attributs.

Les capteurs métier arrivent aux phases suivantes.

## Journaux

Onglet **Journal** de l'app. Pour plus de détail, passer `log_level` à `debug`
dans les options et redémarrer.
