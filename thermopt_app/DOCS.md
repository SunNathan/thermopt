# ThermOpt

Supervision du chauffage fil pilote. Application Home Assistant, installée
depuis ce dépôt.

> **Projet personnel — POC.** Développé avec OpenCode pour un usage domestique.
> Ce n'est ni testé, ni supporté. Ne l'utilise pas sur une installation dont
> dépend le chauffage de quelqu'un d'autre.

## Ce que fait l'application

- lit la température de chaque pièce, la puissance du radiateur et l'ordre
  fil pilote en cours ;
- applique les **garde-fous** : plancher de confort, hors-gel absolu, détection
  de fenêtre ouverte, respect d'un réglage manuel, vérification d'effet ;
- publie ses entités dans Home Assistant via **MQTT discovery** ;
- se configure entièrement depuis l'interface web (bouton **Ouvrir l'interface
  web**), sans fichier YAML.

L'optimisation tarifaire (MPC) n'est pas encore là : l'application protège, elle
n'optimise pas.

## Prérequis

- Home Assistant OS ou Supervised.
- Un broker MQTT (Mosquitto) avec la découverte activée. Il est déjà présent si
  tu utilises Zigbee2MQTT ; les identifiants sont fournis par le Supervisor.
- Les modules fil pilote (NodOn SIN-4-FP-21) exposés par Zigbee2MQTT.

## Installation

1. **Paramètres → Apps → Installer une app**, puis ⋮ → **Dépôts**.
2. Ajouter `https://github.com/SunNathan/thermopt`.
3. Installer **ThermOpt**, démarrer.

## Configuration

Ouvre l'application (bouton **Ouvrir l'interface web**), onglet
**Configuration**.

1. **Ajoute une pièce** par radiateur, renseigne le nom, le capteur de
   température et l'entité fil pilote (`select.xxx_pilot_wire_mode`).
2. Renseigne l'entité météo, les prix HP/HC et les plages Heures Creuses —
   **relève-les sur ton Linky**, ils varient par point de livraison.
3. Règle la **consigne Confort** sur la valeur réellement programmée sur le
   radiateur, et la **consigne Eco** si ton radiateur a une valeur d'écart
   personnalisée (laisse vide pour Eco = Confort − 3,5). Toute l'échelle d'ordres en découle : avec 20,5 °C, Eco vaut
   17,0 °C et Confort−1 vaut 19,5 °C. Avec 20 °C, Eco vaut 16,5 °C et le
   garde-fou se déclenchera chaque nuit.
4. Ajuste le profil de confort si besoin, puis **Enregistre**.

La page refuse une configuration incohérente et explique pourquoi, avec les
chiffres.

## Mode observation et mode actif

L'application démarre **en actif**. Deux garde-fous d'exploitation s'affichent
sur le tableau de bord :

- **Écriture suspendue : repli natif actif** — le helper
  `input_boolean.thermopt_repli` est à `on` ; l'application calcule mais
  n'écrit rien. Désactive l'automatisation de repli et remets le helper à
  `off`.
- **Deux superviseurs détectés** — des entités `sensor.thermopt_*` existent
  encore : l'ancienne intégration est installée. Désinstalle-la, sinon deux
  boucles pilotent le même radiateur.

Le bouton du tableau de bord bascule entre `actif` et `observation`. En
observation, les décisions sont journalisées mais aucun ordre n'est envoyé.

## Entités publiées

| Entité | Rôle |
|---|---|
| `sensor.thermopt_statut` | `observation` / `actif` / `repli` |
| `binary_sensor.thermopt_mode_degrade` | problème détecté, raisons en attribut |
| `sensor.thermopt_prix_actuel` | prix en cours (€/kWh) |
| `sensor.thermopt_dernier_cycle` | horodatage du dernier cycle |
| `sensor.thermopt_app` | santé de l'application |

Par pièce : `sensor.thermopt_<piece>_temperature`, `_consigne_minimale`,
`_securite`, `_ordre_applique`, `_puissance`.

Le nom de la pièce est celui que tu as saisi, mis en minuscules sans accents.

## Garde-fous

| Priorité | Condition | Action |
|---|---|---|
| 1 | `T < 7 °C` | Confort forcé, passe au-dessus du reste |
| 2 | réglage manuel < 2 h | aucune écriture |
| 3 | chute > 1,5 °C en 10 min | suspension 60 min |
| 4 | `T < consigne min − 0,5` | Confort forcé |

Le garde-fou contourne la limite « un changement par 30 min » mais jamais le
temps de stabilisation de 5 minutes, nécessaire au module pour décoder l'ordre.

## Historique et modèle

Onglet **Historique** :

- chaque cycle écrit un échantillon dans `/data/history/`, un fichier JSONL par
  mois (température, extérieure, ordre, puissance, énergie, consigne du
  moment) ;
- la page montre les jours couverts, les trous, le **temps passé par ordre** et
  le nombre de périodes de refroidissement ;
- **Télécharger le CSV** exporte tout, pour analyse hors ligne.

**Identifier le modèle** applique les seuils du cadrage : au moins 14 jours,
au moins 2 ordres utilisés 20 h chacun, au moins 10 périodes de refroidissement
de 3 h, série continue. Si un seuil manque, l'application refuse et dit lequel.

Le modèle est un ARX d'ordre 2 identifié par moindres carrés :
`T[k] = a1·T[k−1] + a2·T[k−2] + be·Te[k−1] + bp·P[k−1] + c`. Sa seconde variable
d'état porte la dynamique de la masse thermique. Il est accepté seulement si
l'erreur de simulation libre sur 12 h reste sous **0,5 °C**. Les paramètres
sont enregistrés dans `/data/model.json` et les déperditions équivalentes, les
constantes de temps et le gain extérieur sont affichés.

Quand un modèle existe, `sensor.thermopt_<piece>_temperature_prevue_12h` publie
la température attendue en maintenant l'ordre et la météo actuels.

## Optimisation (MPC)

Quand un modèle validé existe, l'onglet **Plan** montre pour chaque pièce le
plan des 24 h prochaines : ordre retenu, température prévue, prix, puissance et
coût, plus le coût total.

L'optimiseur minimise `prix × puissance + λ × écart de confort²` sous
contraintes (un changement d'ordre par 30 min, jamais sous 7 °C), par un plan
glouton puis du hill-climbing sur blocs de 1 à 2 h.

**En observation par défaut** : le plan est calculé et publié, mais aucun ordre
n'est appliqué. Pour l'activer, coche *Optimisation active* dans
Configuration — après avoir comparé prévu et réel pendant quelques jours.

Les garde-fous restent prioritaires : s'ils forcent un ordre, l'optimiseur
attend le cycle suivant.

## Journaux

Onglet **Journal** de l'application. Pour plus de détail, passe `log_level` à
`debug` dans les options de l'app et redémarre.
