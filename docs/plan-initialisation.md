# ThermOpt — Plan consolidé d'initialisation

**Statut** : validé avec l'utilisateur, prêt à implémenter
**Périmètre de ce jalon** : squelette d'intégration HA + perception + repli
**Document de référence fonctionnelle** : `thermopt-pilotage-optimal-du-chauffage-fil-pilote-document-clé-en-main.md` (à déplacer dans `docs/spec.md` du repo)

> Note : ce fichier est écrit dans `C:\Users\natha\.opencode\plan` car le mode Plan interdit l'écriture ailleurs. À déplacer dans `docs/plan-initialisation.md` du repo une fois en mode build.

---

## 1. Décisions actées

| Sujet | Décision | Justification |
|---|---|---|
| Forme de l'« extension » | Intégration custom `custom_components/thermopt` | Accès direct aux états, services, recorder et météo ; entités natives ; mise à jour depuis l'UI HA. Un add-on imposerait API REST/WS + token + MQTT pour un gain nul (calcul en quelques ms). |
| Dépendances Python | Aucune (`requirements: []`) | Python pur : RLS/MPC en algèbre 2×2, ~10 µs par trajectoire de 96 pas. Évite toute installation pip sur HA OS. |
| Config | UI uniquement (config flow + subentries + options flow) | Zéro YAML pour la configuration ; reload des options sans redémarrage. |
| Boucle | `DataUpdateCoordinator`, 15 min, ancrée sur l'horloge | Évite la dérive ; aligne les cycles sur les frontières HC/HP. |
| Persistance | `homeassistant.helpers.storage.Store` | Paramètres identifiés, dernier plan, buffer d'échantillons. Pas de base externe. |
| Canal de mise à jour | GitHub Releases → HACS → entité `update` → bouton Update + restart | Répond au besoin « mettre à jour depuis l'interface HA ». |
| Repli | Automatisations/scripts **natifs** (blueprints) | Indépendance totale vis-à-vis du composant, exigence § 7.1.5 du spec. |
| Nommage | repo `thermopt`, domain `thermopt`, préfixe entités `thermopt_` | — |

**Contexte HA** : HA OS sur Raspberry Pi, version 2026.10 ou antérieure → HACS classique. À l'upgrade 2026.11, HACS devient le Marketplace intégré : migration automatique, custom repositories et entités `update` conservés. Les procédures ci-dessous restent valables (l'emplacement passe de « HACS » à « Settings > Marketplace »).

---

## 2. Matériel réel (vérifié)

Actionneurs : **2 × NodOn SIN-4-FP-21** (« Pilot wire heating module »), pilotés via **Zigbee2MQTT**. Radiateurs : 2 × Atlantic SOKIO (réf. Q1H-BD1).

Expositions Zigbee2MQTT confirmées :

| Propriété Z2M | Entité HA | Valeurs |
|---|---|---|
| `pilot_wire_mode` | `select.<radiateur>_pilot_wire_mode` | `comfort`, `comfort_-1`, `comfort_-2`, `eco`, `frost_protection`, `off` |
| `state` | `switch.<radiateur>` | `ON` / `OFF` (relais de sortie) |
| `power` | `sensor.<radiateur>_power` | W, instantané |
| `energy` | `sensor.<radiateur>_energy` | kWh cumulés |
| `power_on_behavior` | `select.<radiateur>_power_on_behavior` | `off`, `on`, `toggle`, `previous` |

**Validation utilisateur** : les 6 ordres sont correctement interprétés par les radiateurs. Confort−1 et Confort−2 sont donc exploitables → l'ensemble d'actions du MPC est bien de 5 ordres, et le levier § 6.3.4 du spec (micro-arbitrages Confort ↔ Confort−1) est conservé.

### 2.1 Conséquences matérielles sur le projet

1. **`P_rad(ordre)` devient une mesure** et non plus une grandeur inférée. Le capteur `power` donne directement la puissance restituée par ordre. Le RLS n'identifie plus que la partie thermique (`C_a`, `C_m`, `H_e`, `H_am`, `H_em`), ce qui supprime le paramètre le plus mal conditionné et réduit fortement le risque « modèle non identifiable » (§ 10 du spec).
2. **L'évaluation économique devient mesurée** : `energy` par radiateur donne la consommation réelle, donc baseline et gain au kWh près (§ 8.2). Le DJU reste utile pour normaliser la météo, mais on ne dépend plus d'une estimation.
3. **Vérification d'effet réelle** : `power > 0` quand l'ordre devrait chauffer. Le « retour d'état » du § 7.2 n'existe pas en Zigbee (le `select` reflète la dernière valeur écrite), c'est cette vérification qui le remplace.
4. **Un seul driver nécessaire** : `select`. L'abstraction est conservée (interface + une implémentation) pour ne pas figer le code, mais les drivers `switches` et `climate` sont abandonnés.
5. **`off` est banni** de l'espace d'actions : ce n'est pas un ordre fil pilote mais une coupure. Liste blanche = les 5 ordres utiles.
6. **`switch = ON` est un prérequis de sécurité** : relais à `OFF` = radiateur qui ne chauffe plus quel que soit l'ordre (panne silencieuse). Surveillance + alerte + remise à `ON` si la pièce doit être chauffée. `power_on_behavior` à régler sur `previous`.
7. **Détection d'override manuel gratuite** : si `pilot_wire_mode` change sans écriture de ThermOpt (bouton physique, appli NodOn, automatisation tierce) → override → gel de la pièce 2 h (§ 7.1.7). À implémenter au jalon sécurité.

### 2.2 Échelle de consignes — paramètre `C`

Seuls le Confort de base `C` et le Hors-gel sont réglables sur le radiateur ; les offsets sont imposés par le protocole (−1, −2, −3,5).

Échelle dérivée : `{C, C−1, C−2, C−3,5, frost}`.

**Valeur recommandée : `C = 20,5 °C`, `frost = 7 °C`**

| Ordre | Consigne effective | Usage / cible du profil |
|---|---|---|
| Confort | 20,5 °C | préchauffage (= T_min occupé + 1) |
| Confort −1 | 19,5 °C | matin / soir — exact |
| Confort −2 | 18,5 °C | journée week-end (19) au plus proche |
| Eco | 17,0 °C | nuit / absence — exact |
| Hors-gel | 7,0 °C | garde-fou uniquement |

Pourquoi 20,5 et pas 20 :
- les deux cibles structurantes (17 et 19,5) tombent **exactement** sur deux ordres → pas de dithering Confort/Confort−1, donc pas d'usure inutile ;
- le garde-fou § 7.1.1 (`T_air < T_min − 0,5` = 16,5 °C) redevient sain : Eco régule à 17 °C, il ne se déclenche qu'en vraie anomalie. Avec `C = 20`, Eco = 16,5 et le garde-fou se déclenchait en boucle chaque nuit ;
- la borne haute du profil (`T_min + 1` = 20,5) correspond exactement au seul ordre au-dessus.

Conséquences logicielles :
- `C` et `frost` sont des **paramètres d'entrée** du config flow ; l'échelle est **calculée**, jamais codée en dur.
- **Validation à la saisie** : avertir si une cible du profil n'est pas atteignable à ±0,5 °C.
- **Contrôle de cohérence** : si le comportement observé trahit un `C` différent du déclaré → `binary_sensor.thermopt_degraded`.
- **Règle d'exploitation** : toute modification de la consigne Confort sur le radiateur doit être répercutée dans l'intégration.
- À vérifier en phase 0 : que le SOKIO accepte 20,5 (pas seulement des entiers). Sinon `C = 21` → `{21, 20, 19, 17,5, 7}`, 19,5 inatteignable mais 19 et l'écart de 0,5 restent acceptables.

---

## 3. Arborescence du repo

```
thermopt/
├─ custom_components/thermopt/
│  ├─ manifest.json          # domain, version, codeowners, issue_tracker, requirements: []
│  ├─ __init__.py            # setup/unload, services, migration
│  ├─ config_flow.py         # 1 entry + subentries « pièce »
│  ├─ coordinator.py         # tick 15 min, orchestration couches 1 et 4
│  ├─ perception/            # météo, tarif HC/HP, profils, présence, liveness, sampling
│  ├─ actuators/             # interface FilPiloteDriver + driver « select »
│  ├─ core/                  # ⚠️ zéro import HA — placeholder à ce jalon
│  ├─ sensor.py · binary_sensor.py · switch.py · button.py · select.py
│  ├─ diagnostics.py
│  ├─ brand/icon.png
│  └─ translations/{fr,en}.json
├─ blueprints/thermopt/      # watchdog + script de repli (import par URL depuis l'UI)
├─ ha_config/helpers.md      # helpers à créer en UI, valeurs exactes
├─ tests/                    # pytest-homeassistant-custom-component
├─ docs/{spec.md,plan-initialisation.md,setup.md,phase0.md,deployment.md}
├─ hacs.json                 # name, render_readme, homeassistant: "2026.10.0"
└─ .github/workflows/{ci.yml,release.yml}
```

Contraintes HACS respectées : un seul sous-dossier dans `custom_components/`, tout le code exécutable dedans, `manifest.json` complet, `brand/icon.png` présent, `hacs.json` à la racine.

`core/` est un sous-paquet **vendoré** (pas un dépôt séparé) car on ne peut pas `pip install` une dépendance privée sur HA OS — mais il n'importe rien de HA, donc il reste testable sur poste de dev.

---

## 4. Périmètre du jalon 1

### 4.1 Configuration (config flow)

Une seule config entry (`single_config_entry: true`) + **une subentry par pièce**.

**Pièce** : nom, capteur T°, capteur humidité, `select` fil pilote, `sensor` de puissance, puissance nominale, surface / volume / exposition (priors du modèle), profil de confort (hérité, surchargeable), `enabled`.

**Système** : entité météo, prix HP et HC (€/kWh), plages HC (liste `HH:MM–HH:MM`, passage de minuit géré), entité binaire HC réelle (optionnelle), profil de confort semaine/week-end, tolérance et marge haute, signal « présence continue » (`input_boolean` ou calendrier), `C`, `frost`.

**Options flow** : tout sauf les capteurs → modification sans redémarrage.

Le tarif configuré **fait foi** ; si l'entité binaire réelle diverge, journaliser + compter (pas de bascule).

### 4.2 Driver fil pilote

```text
FilPiloteDriver (interface)
  ├─ read() -> Order | None
  ├─ async_write(order) -> bool
  └─ is_available() -> bool

SelectDriver  (seule implémentation)
  mappe Order interne -> valeur Z2M :
    COMFORT -> comfort | COMFORT_1 -> comfort_-1 | COMFORT_2 -> comfort_-2
    ECO -> eco | FROST -> frost_protection
    OFF -> interdit (liste blanche)
```

- Entité propre `select.thermopt_<pièce>_order` avec libellés FR (`Confort`, `Confort −1`, `Confort −2`, `Eco`, `Hors-gel`), traduite vers les valeurs Z2M : découple le vocabulaire interne du module et évite d'afficher des `comfort_-2` bruts.
- Contraintes appliquées en sortie : dwell time 5 min, 1 changement max / 30 min, jamais `off`.

### 4.3 Perception

- **Météo** : `weather.get_forecasts(type=hourly)`, série 24 h. Si indisponible → dernière prévision persistée + sinusoïde journalière (§ 4.1 du spec), journalisé et remonté dans `degraded`.
- **Tarif** : plages HC configurées, passage de minuit, prix paramétrables.
- **Profil de confort** : créneaux semaine/week-end + signal de présence continue (bascule journée 17 → 19 °C), effet **immédiat** sur la borne basse, sans attendre le cycle suivant.
- **Liveness capteurs** : variation < 0,05 °C pendant 45 min, ou absence > 10 min → pièce `degraded`. (Le forçage Confort associé appartient au jalon sécurité.)
- **Puissance/énergie** : `power` et `energy` par pièce collectés et journalisés dès ce jalon → baseline réelle de la phase 1 du Gantt, même sans modèle.
- **Prérequis sécurité** : `switch` du module à `ON`, sinon alerte + remise à `ON` si la pièce doit être chauffée.
- **Échantillonnage** : buffer interne à 5 min, anneau borné (≈ 3 mois puis sous-échantillonnage à 15 min), amorcé par un backfill `recorder` limité à 7 jours. On ne gonfle pas la base SQLite du Pi et on ne dépend pas de la granularité du recorder.

### 4.4 Entités exposées

| Entité | Rôle |
|---|---|
| `sensor.thermopt_status` | Init / Collecte / Excitation / Shadow / BoucleFermee / Repli / Manuel |
| `sensor.thermopt_last_cycle` | horodatage du dernier cycle — base du watchdog |
| `sensor.thermopt_next_cycle` | prochaine échéance |
| `binary_sensor.thermopt_degraded` | météo indisponible, capteur figé, `switch` OFF, incohérence tarifaire, `C` incohérent |
| `select.thermopt_<pièce>_order` | ordre courant (FR) |
| `sensor.thermopt_<pièce>_target_min` | borne basse courante |
| `sensor.thermopt_<pièce>_temperature` | miroir de la mesure |
| `sensor.thermopt_<pièce>_power` | miroir de la puissance |
| `switch.thermopt_<pièce>_enabled` | activation de la pièce |
| `button.thermopt_run_now` | forcing manuel d'un cycle (debug) |
| `button.thermopt_dump_state` | dump de l'état interne |

**Le composant n'écrit aucun ordre fil pilote dans ce jalon.** Seul le repli natif agit, et uniquement en cas de défaillance. C'est l'esprit des phases 0–1 du Gantt : déployer, observer, journaliser, sans risque.

### 4.5 Repli (couche 5) et sécurité d'exploitation

- `input_boolean.thermopt_auto` (helper UI) = **source de vérité** auto/manuel, survit à un crash du composant. Le composant lit, n'écrit jamais.
- **Blueprint 1 — watchdog** : toutes les 10 min, si `sensor.thermopt_last_cycle` > 20 min ou `unavailable`/`unknown` → active le repli, notifie, applique le planning.
- **Blueprint 2 — planning de repli** (§ 7.3) : HC → Confort puis Confort−1 ; HP occupé → Confort−1 ; HP inoccupé / nuit → Eco. Dwell 5 min et 1 changement / 30 min respectés.
- Aucune dépendance au composant : les blueprints prennent les `select` fil pilote **bruts** en entrée. Import par URL depuis l'UI (*Settings > Automations > Blueprints > Import*), sans accès fichier.
- Helpers créés en UI, noms exacts documentés dans `ha_config/helpers.md`.

---

## 5. Déploiement

### 5.1 Côté GitHub

1. Repo public `thermopt`, branche `main`, tag `v0.1.0`.
2. **CI** (`ci.yml`) : `ruff check`, `ruff format --check`, `mypy`, `pytest`, `hassfest`, `hacs/action (category: integration)`, et vérification `manifest.version == tag`.
3. **Release** (`release.yml`) : sur push de tag → création de la GitHub Release + notes. Le bump de version devient une commande unique.

### 5.2 Côté HA OS (2026.10, HACS classique)

1. *Settings > Add-ons > Add-on Store > ⋮ > Repositories* → ajouter `https://github.com/hacs/addons`.
2. Installer et démarrer **Get HACS**, suivre les instructions dans les logs.
3. Redémarrer HA.
4. *Settings > Devices & Services > Add Integration > HACS* → authentification GitHub par device code.
5. HACS > ⋮ > *Custom repositories* → URL du repo, catégorie **Integration** → Download `v0.1.0`.
6. Redémarrer HA.
7. *Add Integration > ThermOpt* → météo, tarifs, plages HC, `C`/`frost`, pièces.
8. Créer les helpers en UI, importer les 2 blueprints.

### 5.3 Mises à jour courantes

`Settings > Updates` affiche ThermOpt → **Update** → redémarrage HA. Rollback = redownload d'une release antérieure via HACS. Contraintes assumées : bump de version + release GitHub à chaque mise à jour, et redémarrage (le code Python du composant est chargé au démarrage).

### 5.4 Boucle de dev (optionnelle)

- Développement de `core/` **hors HA** (pytest, données synthétiques) : c'est là que se fait 90 % du travail.
- Si besoin d'itérer sur le plumbing dans HA : clone de dev séparé (Samba share monté sur Windows + `git pull`) — **ne jamais** cumuler avec le dossier géré par HACS.

---

## 6. Dev local et qualité

- Python aligné sur la version exigée par la version de HA cible (3.13 pour la série 2026.x — à confirmer dans le conteneur HA).
- Environnement : `uv venv` + `pytest-homeassistant-custom-component`.
- Tests du jalon : config flow (création, options, unload), setup/unload de l'entry, calcul de l'échelle `C → ordres`, mapping driver, résolution du profil de confort (semaine/week-end/présence), parsing des plages HC avec passage de minuit, liveness capteurs.
- Aucun test ne dépend du réseau ni d'un vrai HA.

---

## 7. Définition de « terminé » (jalon 1)

- L'intégration s'installe depuis HACS, crée son entrée, expose ses entités, survit à un redémarrage HA et à un reload d'options.
- `last_cycle` avance toutes les 15 min pendant 24 h sans trou.
- Le diagnostic affiche : prévision météo retenue, plages HC en vigueur, échelle d'ordres dérivée de `C`, borne basse courante par pièce, taille du buffer, dernière puissance/énergie relevées.
- **Test de panne** : composant désactivé → dans les 20 min le watchdog déclenche le repli, les ordres natifs sont appliqués, une notification part. Réactivation → retour à la normale.
- **Test capteur figé** : capteur simulé figé → `degraded` passe à `on` pour la pièce concernée.
- **Test prérequis relais** : `switch` du module forcé à `OFF` → `degraded` + alerte + remise à `ON`.
- `docs/phase0.md` contient la checklist issue du § 11 du spec, complétée.

---

## 8. Corrections à apporter au document de référence

| Section | Correction |
|---|---|
| § 2.1 | « Modules fil pilote (type Shelly + diodes, ou équivalent) » → **2 × NodOn SIN-4-FP-21** via Zigbee2MQTT ; ajouter les entités `select`/`switch`/`power`/`energy` |
| § 2.2 | Consigne interne 20 °C → **paramètre `C`, recommandé 20,5 °C**, dérivé du profil de confort |
| § 2.3 | La table devient une fonction de `C` ; préciser que les offsets −1/−2/−3,5 sont imposés par le protocole ; ajouter que `off` n'est jamais utilisé |
| § 5.2 / § 5.3 | `P_rad(ordre)` mesurée via `sensor.power` → identification réduite à la partie thermique |
| § 7.1.1 | Seuil de forçage cohérent avec la quantification (résolu par `C = 20,5`) ; ajouter le prérequis `switch = ON` + alerte |
| § 7.2 | « Vérification de la lecture retour » → vérification d'**effet** via `power` (pas de retour d'état réel en Zigbee) |
| § 8.2 | Consommation mesurée par radiateur (`energy`), plus d'estimation par le modèle |
| § 9.1 | Profil aligné sur l'échelle quantifiée (17 / 19,5 / 20,5) |
| § 10 | Retirer le risque « module 4 ordres » (levé par test) ; ajouter « `C` modifié sur le radiateur sans mise à jour de l'intégration » |
| § 11.2 | Remplacé par le matériel confirmé ; nouveau § 11.7 : procédure de calibration (`C`, `frost`, `power_on_behavior = previous`, OTA firmware) |

---

## 9. Suite de la feuille de route

| Jalon | Contenu |
|---|---|
| **J1** (ce plan) | Squelette installable + perception + repli |
| J2 | Couche 4/5 complète : garde-fous absolus (plancher de confort, hors-gel, cohérence capteur), override manuel 2 h, fenêtre ouverte, vérification d'effet via `power` |
| J3 | `core/` : RC 2R2C + RLS (λ = 0,995) + Kalman + `P_rad` issue des mesures ; validation hors ligne (RMSE 12 h ≤ 0,5 °C, blanchiment des résidus, refroidissement libre) |
| J4 | MPC (glouton + hill-climbing, budget ≈ 1 000 évaluations/cycle) + shadow mode |
| J5 | Boucle fermée + évaluation DJU-normalisée vs baseline mesurée |

---

## 10. Points ouverts

1. Le SOKIO accepte-t-il une consigne à 20,5 °C ? (30 s de test, conditionne `C`.)
2. Cadence de report de `power` par le SIN-4-FP-21 (à relever ; si trop lente, l'identification de `P_rad` se fait sur une moyenne glissante).
3. Stabilité Zigbee du maillage (2 modules, 1 écriture / 15–30 min : charge négligeable, mais surveiller les `unavailable`).
4. Coût du backfill `recorder` sur le Pi (limité à 7 jours au démarrage).
5. Le repo doit rester **public** et sans secret (prix, plages HC et profils vivent dans les options, pas dans le code).
