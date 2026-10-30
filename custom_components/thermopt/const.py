"""Constants for the ThermOpt integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "thermopt"
NAME = "ThermOpt"

PLATFORMS: list[str] = ["binary_sensor", "button", "sensor", "switch"]

VERSION = "0.1.0"

# --- Persistence -------------------------------------------------------------
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.state"
STORAGE_SAVE_DELAY = 60  # seconds, debounced writes

# --- Timing ------------------------------------------------------------------
CYCLE_INTERVAL = timedelta(minutes=15)
SAMPLE_INTERVAL = timedelta(minutes=5)
FORECAST_REFRESH = timedelta(hours=1)

# --- Safety ------------------------------------------------------------------
WATCHDOG_MAX_AGE = timedelta(minutes=20)
DWELL_TIME = timedelta(minutes=5)
MAX_CHANGES_PER_WINDOW = 1
RATE_WINDOW = timedelta(minutes=30)
SENSOR_MISSING_AFTER = 10 * 60  # seconds
SENSOR_FROZEN_WINDOW = 45 * 60  # seconds
SENSOR_FROZEN_DELTA = 0.05  # °C

# --- Configuration keys: system ---------------------------------------------
CONF_WEATHER_ENTITY = "weather_entity"
CONF_HC_BINARY_ENTITY = "hc_binary_entity"
CONF_PRESENCE_ENTITY = "presence_entity"
CONF_AUTO_ENTITY = "auto_entity"
CONF_FALLBACK_ENTITY = "fallback_entity"
CONF_HP_PRICE = "hp_price"
CONF_HC_PRICE = "hc_price"
CONF_HC_WINDOWS = "hc_windows"
CONF_COMFORT_SETPOINT = "comfort_setpoint"
CONF_FROST_SETPOINT = "frost_setpoint"
CONF_TOLERANCE = "tolerance"
CONF_HIGH_MARGIN = "high_margin"
CONF_T_MIN_PRESENT_DAY = "t_min_present_day"

CONF_START_NIGHT = "start_night"
CONF_START_MORNING = "start_morning"
CONF_START_DAY = "start_day"
CONF_START_EVENING = "start_evening"

CONF_T_MIN_NIGHT_WEEKDAY = "t_min_night_weekday"
CONF_T_MIN_MORNING_WEEKDAY = "t_min_morning_weekday"
CONF_T_MIN_DAY_WEEKDAY = "t_min_day_weekday"
CONF_T_MIN_EVENING_WEEKDAY = "t_min_evening_weekday"

CONF_T_MIN_NIGHT_WEEKEND = "t_min_night_weekend"
CONF_T_MIN_MORNING_WEEKEND = "t_min_morning_weekend"
CONF_T_MIN_DAY_WEEKEND = "t_min_day_weekend"
CONF_T_MIN_EVENING_WEEKEND = "t_min_evening_weekend"

# --- Configuration keys: room subentries ------------------------------------
SUBENTRY_ROOM = "room"

CONF_ROOM_NAME = "name"
CONF_ROOM_AREA = "area_id"
CONF_ROOM_TEMP_ENTITY = "temp_entity"
CONF_ROOM_HUMIDITY_ENTITY = "humidity_entity"
CONF_ROOM_FIL_PILOTE_ENTITY = "fil_pilote_entity"
CONF_ROOM_RELAY_ENTITY = "relay_entity"
CONF_ROOM_POWER_ENTITY = "power_entity"
CONF_ROOM_ENERGY_ENTITY = "energy_entity"
CONF_ROOM_NOMINAL_POWER = "nominal_power"
CONF_ROOM_SURFACE = "surface"
CONF_ROOM_VOLUME = "volume"

# --- Reference values --------------------------------------------------------
DEFAULT_HP_PRICE = 0.2065
DEFAULT_HC_PRICE = 0.1579
DEFAULT_HC_WINDOWS = "22:00-06:00, 12:00-14:00"
DEFAULT_COMFORT_SETPOINT = 20.5
DEFAULT_FROST_SETPOINT = 7.0
DEFAULT_NOMINAL_POWER = 1500.0
DEFAULT_FALLBACK_ENTITY = "input_boolean.thermopt_repli"

# --- Supervisor states (§ 7.4) ----------------------------------------------
STATE_INIT = "init"
STATE_COLLECTE = "collecte"
STATE_EXCITATION = "excitation"
STATE_SHADOW = "shadow"
STATE_CLOSED_LOOP = "boucle_fermee"
STATE_FALLBACK = "repli"
STATE_MANUAL = "manuel"

# --- Public modes exposed by ``sensor.thermopt_statut`` ----------------------
# Readable, translated, stable: they are what the user and automations see.
MODE_OBSERVATION = "observation"
MODE_SECURITE = "securite"
MODE_PILOTAGE = "pilotage"
MODE_REPLI = "repli"
MODE_MANUEL = "manuel"
MODE_DEGRADE = "degrade"

SUPERVISOR_MODES = [
    MODE_OBSERVATION,
    MODE_SECURITE,
    MODE_PILOTAGE,
    MODE_REPLI,
    MODE_MANUEL,
    MODE_DEGRADE,
]

# --- Actuation gates ---------------------------------------------------------
# Two independent scopes. The safety layer is allowed to write; the optimiser
# (MPC) is not built yet. Guard rails must never be blocked by a degraded
# situation: a cold room must be rescued even if the comfort profile is wrong.
SAFETY_ACTUATION = True
OPTIMIZER_ACTUATION = False

SAFETY_REASON = (
    "Sécurité seule : ThermOpt n'envoie un ordre que si la pièce passe sous sa borne de confort."
)
OBSERVATION_REASON = "Sécurité et optimisation désactivées : aucun ordre n'est envoyé au radiateur."

# --- Degradation reasons -----------------------------------------------------
DEGRADED_WEATHER = "weather_unavailable"
DEGRADED_SENSOR_MISSING = "sensor_missing"
DEGRADED_SENSOR_FROZEN = "sensor_frozen"
DEGRADED_ACTUATOR_UNAVAILABLE = "actuator_unavailable"
DEGRADED_RELAY_OFF = "relay_off"
DEGRADED_TARIFF_MISMATCH = "tariff_mismatch"
DEGRADED_PROFILE_UNREACHABLE = "profile_unreachable"
DEGRADED_NO_ROOM = "no_room_configured"
DEGRADED_NO_EFFECT = "no_effect"

# --- Misc --------------------------------------------------------------------
MANUFACTURER = "ThermOpt"
MODEL = "Heating supervisor"
