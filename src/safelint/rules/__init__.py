"""Rule registry — all available safelint rules and their canonical order."""

from __future__ import annotations

from safelint.rules.base import BaseRule, Violation
from safelint.rules.complexity import ComplexityRule
from safelint.rules.dataflow import NullDereferenceRule, ReturnValueIgnoredRule, TaintedSinkRule
from safelint.rules.documentation import MissingAssertionsRule
from safelint.rules.error_handling import BareExceptRule, EmptyExceptRule, LoggingOnErrorRule
from safelint.rules.function_length import FunctionLengthRule
from safelint.rules.loop_safety import UnboundedLoopRule
from safelint.rules.max_arguments import MaxArgumentsRule
from safelint.rules.nesting_depth import NestingDepthRule
from safelint.rules.resource_lifecycle import ResourceLifecycleRule
from safelint.rules.side_effects import SideEffectsHiddenRule, SideEffectsRule
from safelint.rules.state_purity import GlobalMutationRule, GlobalStateRule
from safelint.rules.test_coverage import TestCouplingRule, TestExistenceRule

# Canonical list — cheap structural rules first, dataflow rules last
# (they are more expensive and disabled by default).
ALL_RULES: list[type[BaseRule]] = [
    FunctionLengthRule,
    NestingDepthRule,
    MaxArgumentsRule,
    BareExceptRule,
    EmptyExceptRule,
    GlobalStateRule,
    GlobalMutationRule,
    UnboundedLoopRule,
    ComplexityRule,
    SideEffectsHiddenRule,
    SideEffectsRule,
    LoggingOnErrorRule,
    ResourceLifecycleRule,
    TestCouplingRule,
    TestExistenceRule,
    MissingAssertionsRule,
    # Dataflow hybrid rules — disabled by default, enable in .ai-safety.yaml
    TaintedSinkRule,
    ReturnValueIgnoredRule,
    NullDereferenceRule,
]

RULE_BY_NAME: dict[str, type[BaseRule]] = {cls.name: cls for cls in ALL_RULES}

__all__ = [
    "ALL_RULES",
    "RULE_BY_NAME",
    "BaseRule",
    "Violation",
    "FunctionLengthRule",
    "NestingDepthRule",
    "MaxArgumentsRule",
    "ComplexityRule",
    "BareExceptRule",
    "EmptyExceptRule",
    "LoggingOnErrorRule",
    "GlobalStateRule",
    "GlobalMutationRule",
    "SideEffectsHiddenRule",
    "SideEffectsRule",
    "ResourceLifecycleRule",
    "UnboundedLoopRule",
    "MissingAssertionsRule",
    "TestExistenceRule",
    "TestCouplingRule",
    "TaintedSinkRule",
    "ReturnValueIgnoredRule",
    "NullDereferenceRule",
]
