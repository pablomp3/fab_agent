"""Product policy values that are not tool calibration.

These values belong to the product gate, not to a tool model. Keeping them out
of ``src/core`` means a YAML file cannot lower a safety limit by accident.
"""

# An anomaly at or above this robust-z level, outside the configured check,
# prevents a bare "Fault Confirmed". The number is a product choice; it is not
# a sensor calibration and is not configurable per tool.
COVERAGE_UNEXPLAINED_LARGE_Z = 5.0
