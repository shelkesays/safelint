"""Rule registry and factory for safelint."""

from safelint.core.config import SafeLintConfig
from safelint.rules.base import Rule
from safelint.rules.error_handling import ErrorHandlingRule
from safelint.rules.function_length import FunctionLengthRule
from safelint.rules.nesting_depth import NestingDepthRule
from safelint.rules.resource_lifecycle import ResourceLifecycleRule
from safelint.rules.side_effects import SideEffectsRule


def build_rules(config: SafeLintConfig) -> list[Rule]:
    """Instantiate and return only the rules enabled in *config*."""
    available_rules: list[Rule] = [
        FunctionLengthRule(config),
        NestingDepthRule(config),
        ErrorHandlingRule(config),
        SideEffectsRule(config),
        ResourceLifecycleRule(config),
    ]
    enabled = set(config.enabled_rules)
    return [rule for rule in available_rules if rule.name in enabled]


__all__ = ["build_rules"]
