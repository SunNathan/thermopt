"""ThermOpt app: supervision of a pilot-wire heater.

This package runs inside a Home Assistant app container. It talks to Home
Assistant through the Supervisor proxy and publishes its entities with MQTT
discovery, so they behave like native entities.
"""

__version__ = "0.5.2"
