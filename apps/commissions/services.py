from . import calculators as calc
from .models import PlatformRules


def active_rules():
    return PlatformRules.active(calc.default_parameters)


def rules():
    """The active parameters, with defaults filled in for sections added after the version was saved."""
    params = dict(active_rules().parameters)
    for section, values in calc.DEFAULT_PARAMETERS.items():
        if section not in params:
            params[section] = calc.default_parameters()[section]
        elif isinstance(values, dict):
            params[section] = {**values, **params[section]}
    return params
