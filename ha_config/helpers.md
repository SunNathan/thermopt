# Helpers à créer dans Home Assistant

Les helpers sont créés par l'utilisateur, **pas** par l'intégration : c'est
volontaire. Ils doivent rester lisibles et modifiables par les automatisations
natives même si ThermOpt est en panne.
*Paramètres → Appareils et services → Entrées (Helpers) → Créer une entrée.*

## 1. `input_boolean.thermopt_auto` — obligatoire

| Champ | Valeur |
|---|---|
| Nom | ThermOpt auto |
| Type | Interrupteur (input_boolean) |
| Icône | `mdi:robot` |
| Catégorie | — |

**Rôle** : source de vérité du mode auto/manuel.

- `on` → ThermOpt est autorisé à superviser (et le watchdog surveille le battement de cœur).
- `off` → mode manuel : l'intégration n'écrit jamais d'ordre, et le watchdog
  ne déclenche pas le repli.

À renseigner dans l'intégration (champ « Interrupteur auto/manuel »).

## 2. `input_boolean.thermopt_repli` — obligatoire

| Champ | Valeur |
|---|---|
| Nom | ThermOpt repli |
| Type | Interrupteur (input_boolean) |
| Icône | `mdi:shield-alert` |

**Rôle** : drapeau « repli actif ». Il est piloté **uniquement** par le
blueprint watchdog, jamais par l'intégration. Le blueprint de planning de repli
ne fait rien tant qu'il est à `off`.

À renseigner dans les deux blueprints.

## 3. Signal de présence continue — optionnel

Au choix :

- un `input_boolean.thermopt_presence_jour`, basculé manuellement la veille ;
- un `calendar.thermopt_teletravail`, avec des événements « journée entière » les
  jours concernés.

À renseigner dans l'intégration (champ « Présence continue »). Quand le signal
est actif, la borne basse de journée passe de 17 °C à 19 °C pour les pièces
concernées, et l'optimiseur replanifie au cycle suivant.

## 4. Vérification

Après création, les entités doivent apparaître immédiatement :

```text
input_boolean.thermopt_auto
input_boolean.thermopt_repli
```

Statuts attendus au repos : `thermopt_auto` à `on`, `thermopt_repli` à `off`.

> Les entités créées doivent être ajoutées à `recorder` si vous voulez suivre
> l'historique des bascules. Les helpers `input_boolean` sont enregistrés par
> défaut.
