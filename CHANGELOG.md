# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
versionnage sémantique. La version de `thermopt_app/config.yaml` doit toujours
correspondre au tag publié.

## [Unreleased]

## [0.7.0] — 2026-10-31

### Ajouté

- **Tableau de bord vivant** : la page interroge `state.json` toutes les 10 s et
  met à jour sans rechargement la température, la puissance, l'ordre appliqué,
  la consigne min, la prévision, la sécurité et le dernier cycle. Seules les
  mesures utiles sont relues dans Home Assistant à chaque appel.

### Modifié

- **Mode actif autoritaire** : ThermOpt applique l'ordre du profil dans les
  deux sens (Eco la nuit et en journée, Confort−1 le matin et le soir), même si
  l'ordre courant a été réglé à la main, par une scène ou par une autre
  automatisation. Le gel manuel de 2 h et l'état `override` sont supprimés : le
  mode observation est désormais la façon de reprendre la main.

### Corrigé

- **Ordre de chauffage jamais redescendu** : quand le garde-fou forçait Confort
  et que la cible baissait (nuit, fin de préchauffage), rien ne ramenait le
  radiateur vers Eco tant que l'optimiseur n'était pas actif. Sans optimiseur,
  ThermOpt applique désormais l'ordre du profil à chaque cycle, sous la limite
  d'un changement par 30 min.
- **Tableau de bord figé** : température, puissance et ordre appliqué étaient
  lus dans un instantané pris au démarrage (le cache HA remplace son
  dictionnaire à chaque rafraîchissement). La page lit maintenant le cache
  vivant, et un rafraîchissement ciblé est déclenché à chaque interrogation.

## [0.6.0] — 2026-10-30

### Modifié

- **Dépôt recentré sur l'app.** L'intégration Home Assistant est retirée :
  `custom_components/`, `manifest.json` et `hacs.json` disparaissent. Le code
  partagé déménage dans `lib/thermopt_lib/`, le Dockerfile le copie tel quel.
- La CI ne teste plus que l'app : les jobs hassfest et HACS sont supprimés, et
  `pytest-homeassistant-custom-component` n'est plus une dépendance (suite de
  tests 3× plus rapide).
- `mypy` couvre désormais `lib/thermopt_lib` **et** `thermopt_app/app`.
- La version ne vit plus qu'à un endroit : `thermopt_app/config.yaml`.
- Version portée à **0.6.0**.

### Ajouté

- **Rétention de l'historique** : le mois courant et les deux précédents, purgés
  automatiquement une fois par jour. L'interface affiche la plage conservée.
- **Surveillance du disque** : espace libre de `/data` vérifié chaque jour,
  mode dégradé sous 200 Mo, et erreurs d'écriture remontées dans les alertes.
- **Export CSV borné par deux dates** depuis la page Historique.

### Corrigé

- **Bascule actif/observation sans effet visible** : le mode affiché provenait
  du dernier cycle et restait donc figé jusqu'à 15 minutes. Il est maintenant
  recalculé immédiatement à chaque changement de configuration, et la bascule
  déclenche un cycle en tâche de fond pour mettre à jour les entités MQTT.
- Un cycle ne peut plus s'exécuter deux fois en parallèle (garde de réentrance).
- **Version de Home Assistant retirée** du tableau de bord ; l'information
  reste dans les journaux de l'app.

### Ajouté

- **Consigne Eco indépendante** : Eco n'est plus forcément Confort − 3,5.
  Le champ *Consigne Eco* de la configuration accepte une valeur absolue
  (celle réglée sur le radiateur) ; vide, il retombe sur l'ancien calcul.
  Confort−1 et Confort−2 restent des offsets du protocole.
  La validation exige Hors-gel < Eco < Confort, et le message d'alerte cite
  désormais Eco quand il est explicite.

### Ajouté

- **Phase E : optimiseur MPC.**
  - plan de 24 h au pas de 15 min, minimisant `prix × puissance + λ × écart²`
    sous contraintes (un changement par 30 min, jamais sous 7 °C) ;
  - puissance par ordre modélisée par saturation sur la consigne de l'ordre ;
  - plan glouton à horizon 2 h puis hill-climbing, budget 1 000 simulations ;
  - **observation par défaut** : le plan est publié, rien n'est appliqué tant
    que l'option n'est pas cochée ;
  - onglet **Plan** : coût 24 h, changements, température minimale, prochaine
    action et tableau horaire ;
  - `sensor.thermopt_<piece>_cout_24h` et `_prochaine_action` ;
  - verrou : aucun plan sans modèle identifié.

### Modifié

- Version portée à **0.5.0** (intégration et app).

### Corrigé

- **Faux positif « Deux superviseurs détectés »** : la détection cherchait
  n'importe quelle entité `sensor.thermopt_*`, donc elle se déclenchait sur les
  entités publiées par l'app elle-même. Elle repose désormais sur une liste
  d'entités que seule l'ancienne intégration créait, ignore les entités
  indisponibles, et un bouton permet d'acquitter l'avertissement.
- **« Météo indisponible » systématique** : la réponse d'un appel de service
  REST avec `return_response` est enveloppée dans `service_response` ; elle
  était lue à la racine, donc toujours vide. La température extérieure n'était
  jamais enregistrée dans l'historique, ce qui rendait les échantillons
  inutilisables pour l'identification.
- Carte **Météo** sur le tableau de bord : entité configurée, état, température
  actuelle, et une ligne indiquant le nombre de points de prévision ou l'erreur
  exacte.

### Corrigé

- **Redirection après enregistrement** : `Location: /` renvoyait vers l'accueil
  de Home Assistant, puisque l'app est servie sous
  `/api/hassio_ingress/<token>/`. Les redirections sont désormais relatives
  (`./`), y compris après la bascule actif/observation.

### Ajouté

- **Phase C : collecte persistante et audit.**
  - historique en JSONL append-only dans `/data/history/`, un fichier par mois ;
  - onglet **Historique** : jours couverts, trous, temps par ordre, puissance
    moyenne par ordre, périodes de refroidissement ;
  - export CSV complet ;
  - audit bloquant selon les seuils du cadrage (14 jours, 2 ordres × 20 h,
    10 périodes de refroidissement).
- **Phase D : identification du modèle thermique.**
  - ARX d'ordre 2 identifié par moindres carrés (numpy), sans optimiseur
    non linéaire ;
  - validation par simulation libre de 12 h, **rejet au-delà de 0,5 °C** ;
  - déperditions équivalentes, constantes de temps et gain extérieur dérivés ;
  - `P_rad` estimée par la puissance mesurée, par ordre ;
  - paramètres dans `/data/model.json` ;
  - `sensor.thermopt_<piece>_temperature_prevue_12h`.

### Modifié

- Version portée à **0.4.0** (intégration et app).
- Ajout de `numpy` à l'image de l'app (légitime dans un conteneur).

### Sécurité, entités et tableau de bord

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
