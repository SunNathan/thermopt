# ThermOpt

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

| Chemin | Rôle |
|---|---|
| `custom_components/thermopt/` | L'intégration (seul dossier déployé par HACS) |
| `custom_components/thermopt/core/` | Modèle, ordres, buffer, limiteur — Python pur, sans Home Assistant |
| `custom_components/thermopt/perception/` | Tarif HC/HP, profil de confort, météo, liveness |
| `custom_components/thermopt/actuators/` | Abstraction fil pilote (driver `select`) |
| `blueprints/thermopt/` | Watchdog et planning de repli, à importer par URL |
| `ha_config/` | Helpers à créer dans l'interface |
| `docs/spec.md` | Document de cadrage fonctionnel (référence, amendé) |
| `docs/plan-initialisation.md` | Plan consolidé du jalon 1 |
| `tests/` | Tests unitaires purs + tests Home Assistant |

## Installation

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

Plus : température, humidité, consignes min/max, créneau, puissance, énergie,
problème, et un switch de supervision, ainsi que deux boutons de diagnostic.

Une vue Lovelace prête à coller est fournie dans
[`dashboards/thermopt.yaml`](dashboards/thermopt.yaml). Elle ne référence que
les entités `sensor.thermopt_*` (dont les identifiants sont garantis) et
construit le tableau des pièces depuis `sensor.thermopt_pieces` : aucun nom de
pièce n'est codé en dur.

Pour obtenir des cartes natives avec les vrais `entity_id`, appuie sur le
bouton **« Générer la vue »** : il lit le registre d'entités, publie le YAML
adapté dans une notification et liste les entités manquantes, s'il y en a.

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
