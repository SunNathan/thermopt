# Phase 0 — Préparation et checklist

À dérouler **avant** de laisser l'intégration toucher aux radiateurs (jalon 2).
Chaque case doit être cochée ; la plupart demandent moins de cinq minutes.

## 1. Compteur et tarif

- [ ] Relever les plages Heures Creuses réelles sur le Linky (bouton « + »
      jusqu'à « Heures creuses ») ou sur la facture.
- [ ] Les saisir dans *Options* de l'intégration, format `HH:MM-HH:MM` séparés
      par des virgules. Vérifier le passage de minuit (ex. `22:00-06:00`).
- [ ] Saisir les prix HP et HC en vigueur (révision tarifaire = mise à jour des
      options, pas une nouvelle version).
- [ ] Vérifier `binary_sensor.thermopt_heures_creuses` : il doit basculer aux
      bons horaires. Si vous avez un capteur Linky, le renseigner comme
      « signal HC réel » et surveiller les discordances dans les journaux.

## 2. Radiateurs

- [ ] Passer le firmware des modules SIN-4-FP-21 à jour par OTA depuis Z2M.
- [ ] Régler `power_on_behavior = previous` sur chaque module.
- [ ] Régler la consigne **Confort** sur **20,5 °C** et la consigne **Hors-gel**
      sur **7 °C** (ou la valeur validée) sur chaque radiateur.
- [ ] Relever les deux valeurs et les saisir dans les options de l'intégration.
- [ ] Vérifier que le radiateur accepte bien 20,5 °C (certains modèles
      n'acceptent que des pas de 1 °C ; sinon passer à 21 °C et vérifier que le
      garde-fou de confort reste cohérent).
- [ ] Fixer le mode local des radiateurs sur **Confort** (l'optimiseur prend le
      relais en changeant l'ordre, pas le mode interne).
- [ ] Laisser la détection de fenêtre ouverte du SOKIO **active** ; désactiver
      le délestage interne (géré par l'optimiseur).
- [ ] Vérifier les 6 ordres depuis Z2M : pour chaque valeur, attendre 30 min et
      contrôler la puissance mesurée et le comportement du radiateur.
      *Déjà fait une fois : les 6 ordres sont interprétés. À refaire après tout
      changement de câblage ou de radiateur.*

## 3. Entités Home Assistant

- [ ] `select.<radiateur>_pilot_wire_mode` existe et expose les 6 options.
- [ ] `switch.<radiateur>` existe et est à `on`.
- [ ] `sensor.<radiateur>_power` et `sensor.<radiateur>_energy` remontent.
- [ ] Relever la cadence de report de `power` (elle conditionne la future
      identification de `P_rad`).
- [ ] Capteur de température par pièce, avec une précision affichée d'au moins
      0,1 °C.
- [ ] Intégration météo fournissant `weather.get_forecasts` en horaire.

## 4. Pièces et profil de confort

- [ ] Pour chaque pièce : surface, volume, puissance nominale du radiateur,
      exposition.
- [ ] Valider les créneaux du profil (nuit / matin / journée / soirée).
- [ ] Décider du support du signal « présence continue » : `input_boolean`
      manuel, calendrier, ou routine.
- [ ] Vérifier que `binary_sensor.thermopt_mode_degrade` est à `off` après
      configuration. S'il est à `on`, lire l'attribut `reasons`.

## 5. Sécurité et repli

- [ ] Helpers créés (`input_boolean.thermopt_auto`,
      `input_boolean.thermopt_repli`).
- [ ] Blueprint watchdog instancié.
- [ ] Blueprint planning de repli instancié **pour chaque pièce**.
- [ ] Test de panne effectué : intégration désactivée → repli armé en moins de
      20 min, notification reçue, ordres appliqués par le natif.
- [ ] Test relais effectué : `switch` à `off` → `mode_degrade` à `on` et
      remise à `on`.

## 6. Historique

- [ ] Laisser tourner l'intégration **au moins 14 jours** en mode collecte
      (phase 1 du calendrier) avant toute identification de modèle.
- [ ] Vérifier que `sensor.<pièce>_energie` progresse et que le buffer se
      remplit (bouton *Dumper l'état* → journaux).
