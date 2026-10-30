# ThermOpt

> [!WARNING]
> **Projet personnel — POC, pas un produit.** ThermOpt est une preuve de
> concept développée avec **OpenCode** pour mon usage domestique : deux
> radiateurs, une installation, un foyer. Ce n'est ni testé, ni supporté,
> ni maintenu au-delà de ce que décrivent `CHANGELOG.md` et `docs/phase0.md`.
> **Ne l'utilise pas en production**, et surtout pas sur une installation dont
> dépend le chauffage de quelqu'un d'autre : une erreur de configuration peut
> laisser une pièce froide.

Supervision du chauffage fil pilote pour Home Assistant : modèle thermique
RC 2R2C, filtre de Kalman et optimiseur MPC, avec garde-fous de confort et
repli natif.

Cible matérielle : 2 radiateurs Atlantic SOKIO pilotés par 2 modules
**NodOn SIN-4-FP-21** en Zigbee2MQTT, sur un Raspberry Pi.

> **État actuel : jalon 1.** L'intégration s'installe, observe, calcule les
> bornes de confort et détecte les situations dégradées. **Elle n'applique
> encore aucun ordre fil pilote.** Seul le planning de repli natif agit, et
> uniquement en cas de panne.

## Contenu du dépôt

Le dépôt porte **deux implémentations** de la même logique :

| Chemin | Rôle |
|---|---|
| `custom_components/thermopt/` | **Intégration** (historique, distribuée par HACS) |
| `thermopt_app/` | **App Home Assistant** (cible à terme, via ingress + MQTT discovery) |
| `repository.yaml` | Déclare le dépôt comme dépôt d'apps auprès du Supervisor |
| `custom_components/thermopt/core/` | Ordres, buffer, sécurité, limiteur — Python pur |
| `custom_components/thermopt/perception/` | Tarif HC/HP, profil de confort, météo, liveness |
| `custom_components/thermopt/actuators/` | Abstraction fil pilote (driver `select`) |
| `blueprints/thermopt/` | Watchdog et planning de repli, à importer par URL |
| `ha_config/` | Helpers à créer dans l'interface |
| `docs/spec.md` | Document de cadrage fonctionnel (référence, amendé) |
| `docs/plan-initialisation.md` | Plan consolidé du jalon 1 |
| `tests/` | Tests unitaires purs + tests Home Assistant + app |

## Installation

### App Home Assistant (cible)

1. **Paramètres → Apps → Installer une app**, puis ⋮ → **Dépôts**.
2. Ajouter `https://github.com/SunNathan/thermopt`.
3. Installer **ThermOpt**, démarrer, puis **Ouvrir l'interface web**.

L'app publie ses entités via MQTT discovery (le broker Mosquitto de
Zigbee2MQTT convient, les identifiants sont fournis par le Supervisor) et ses
mises à jour passent par le bouton **Mettre à jour** de l'App store.

État actuel : **phase B+C+D+E** — configuration, perception, garde-fous,
historique persistant, identification du modèle et optimiseur MPC en
observation.

### Intégration (historique)

Voir **[docs/setup.md](docs/setup.md)**. En résumé, avec HACS (ou le
Marketplace intégré à Home Assistant 2026.11+) :

1. HACS → ⋮ → *Dépôts personnalisés* → URL de ce dépôt, catégorie **Intégration**.
2. Télécharger la dernière version, puis redémarrer Home Assistant.
3. *Paramètres → Appareils et services → Ajouter une intégration → ThermOpt*.
4. Ajouter chaque pièce via le bouton **Ajouter une entrée** de l'intégration.
5. Créer les helpers ([ha_config/helpers.md](ha_config/helpers.md)) et importer
   les deux blueprints.

## Réglage clé : la consigne Confort

Le fil pilote ne choisit pas une température, il choisit un échelon. Seule la
consigne **Confort** du radiateur est réglable ; tout le reste en découle :

| `C` (réglé sur le radiateur) | Confort | Confort−1 | Confort−2 | Eco | Hors-gel |
|---|---|---|---|---|---|
| 20,0 °C (déconseillé) | 20,0 | 19,0 | 18,0 | 16,5 | 7,0 |
| **20,5 °C (recommandé)** | **20,5** | **19,5** | **18,5** | **17,0** | **7,0** |

Avec 20,5 °C, les cibles du profil de confort (17 °C la nuit, 19,5 °C en
occupation) tombent exactement sur Eco et Confort−1, et le garde-fou de
confort ne se déclenche plus à tort chaque nuit.

Toute modification de cette consigne sur le radiateur doit être répercutée
dans les options de l'intégration.

## Entités créées

**Comprendre l'état en un coup d'œil :**

- `binary_sensor.thermopt_pilotage_actif` — **la réponse à « est-ce que ça
  pilote mon chauffage ? »**. `off` tant que la boucle fermée n'existe pas, avec
  un attribut `raison` qui explique pourquoi. `on` quand ThermOpt applique
  réellement ses ordres.
- `sensor.thermopt_statut` — mode lisible : `observation`, `pilotage`, `repli`,
  `manuel` ou `degrade` (états traduits).
- `sensor.thermopt_derniere_commande` — dernière commande écrite par ThermOpt
  (horodatage), avec `piece`, `ordre`, `resultat` et `source` en attributs.
- `sensor.thermopt_dernier_cycle` / `prochain_cycle` — battement de cœur (base du watchdog)
- `sensor.thermopt_prix_actuel`, `sensor.thermopt_temperature_exterieure`
- `binary_sensor.thermopt_mode_degrade`, `binary_sensor.thermopt_heures_creuses`

**Par pièce**, l'ordre demandé et l'ordre appliqué sont séparés :

- `sensor.<piece>_ordre_demande` — ce que ThermOpt veut appliquer
- `sensor.<piece>_ordre_applique` — ce que le module contient réellement, avec
  l'attribut `source` : `thermopt`, `manuel`, `repli` ou `inconnue`
- `sensor.<piece>_securite` — `inactif`, `plancher`, `hors_gel`, `fenetre` ou
  `override`, avec la raison en attribut

## Ce que ThermOpt écrit réellement

Une seule chose pour l'instant : **les garde-fous**. `pilotage_actif` est à
`on` avec `portee: securite`, et le mode vaut `securite`.

| Situation | Action |
|---|---|
| Pièce sous `T_min − 0,5 °C` | Confort forcé, notification |
| Pièce sous 7 °C | Confort forcé, alarme |
| Chute > 1,5 °C en 10 min | suspension 60 min, on laisse le SOKIO gérer |
| `select` changé à la main | pièce gelée 2 h |
| Ordre chauffant sans puissance mesurée | alerte `no_effect` |

Le garde-fou contourne la limite « 1 changement / 30 min » mais jamais le dwell
de 5 minutes, qui est une contrainte matérielle du module. L'optimisation
tarifaire (MPC) n'est pas encore branchée : `portee` passera à `optimiseur`.

Plus : température, humidité, consignes min/max, créneau, puissance, énergie,
problème, et un switch de supervision, ainsi que deux boutons de diagnostic.

Un **tableau de bord complet** prêt à coller est fourni dans
[`dashboards/thermopt.yaml`](dashboards/thermopt.yaml) : *Paramètres → Tableaux
de bord → ⋯ → Modifier → ⋯ → Éditeur de configuration brute*, tout
sélectionner, coller. Il ne référence que les entités `sensor.thermopt_*` (dont
les identifiants sont garantis) et construit le tableau des pièces depuis
`sensor.thermopt_pieces` : aucun nom de pièce n'est codé en dur.

Pour des cartes natives avec les vrais `entity_id`, appuie sur le bouton
**« Générer la vue »** : il lit le registre d'entités, valide le YAML produit et
le publie dans une notification, en listant les entités manquantes s'il y en a.

## Développement

```bash
python -m venv .venv
.venv/Scripts/activate           # Windows
pip install -r requirements_dev.txt
pytest -q                        # tests purs + tests Home Assistant
ruff check custom_components tests
ruff format custom_components tests
```

Avant chaque push, lancer le script qui reproduit exactement le job `quality`
de la CI (ruff, mypy, pytest) :

```powershell
.\scripts\check.ps1
```

Les tests Home Assistant utilisent `pytest-homeassistant-custom-component`
(qui impose la version de Home Assistant testée). Sur Windows, deux modules
Unix manquent au harnais : voir les commentaires de `tests/conftest.py`.

## Licence

MIT.
