"""Rule registry - all available safelint rules and their canonical order."""

from __future__ import annotations

from safelint.rules.base import BaseRule, Violation
from safelint.rules.blanket_suppression import BlanketSuppressionRule
from safelint.rules.complexity import ComplexityRule
from safelint.rules.dataflow import NullDereferenceRule, ReturnValueIgnoredRule, TaintedSinkRule
from safelint.rules.documentation import MissingAssertionsRule
from safelint.rules.dynamic_code_execution import DynamicCodeExecutionRule
from safelint.rules.error_handling import BareExceptRule, EmptyExceptRule, LoggingOnErrorRule
from safelint.rules.function_length import FunctionLengthRule
from safelint.rules.loop_safety import UnboundedLoopRule
from safelint.rules.max_arguments import MaxArgumentsRule
from safelint.rules.nesting_depth import NestingDepthRule
from safelint.rules.no_recursion import NoRecursionRule
from safelint.rules.resource_lifecycle import ResourceLifecycleRule
from safelint.rules.rust_rules import (
    DangerousMemOpsRule,
    InteriorMutableStaticRule,
    LockPoisoningIgnoredRule,
    NeedlessMutRule,
    PanicMacrosOutsideTestsRule,
    ResultUnwrapOutsideTestsRule,
    SilentResultDiscardRule,
    TruncatingAsCastRule,
    UncheckedArithmeticOnInputRule,
    UndocumentedUnsafeRule,
    UnloggedErrorBranchRule,
)
from safelint.rules.side_effects import SideEffectsHiddenRule, SideEffectsRule
from safelint.rules.spring import (
    SpringAsyncCheckedExceptionRule,
    SpringFieldInjectionRule,
    SpringMissingTransactionalRule,
    SpringUnvalidatedInputRule,
)
from safelint.rules.state_purity import GlobalMutationRule, GlobalStateRule, WideScopeDeclarationRule
from safelint.rules.test_coverage import TestCouplingRule, TestExistenceRule


# Canonical list - cheap structural rules first, dataflow rules last
# (they are more expensive and disabled by default).
ALL_RULES: list[type[BaseRule]] = [
    FunctionLengthRule,
    NestingDepthRule,
    MaxArgumentsRule,
    NoRecursionRule,
    BareExceptRule,
    EmptyExceptRule,
    GlobalStateRule,
    GlobalMutationRule,
    WideScopeDeclarationRule,
    UnboundedLoopRule,
    ComplexityRule,
    SideEffectsHiddenRule,
    SideEffectsRule,
    DynamicCodeExecutionRule,
    LoggingOnErrorRule,
    ResourceLifecycleRule,
    TestCouplingRule,
    TestExistenceRule,
    MissingAssertionsRule,
    BlanketSuppressionRule,
    # Dataflow hybrid rules - disabled by default; enable via
    # [tool.safelint.rules.<rule>] in pyproject.toml, or [rules.<rule>] in
    # a standalone safelint.toml.
    TaintedSinkRule,
    ReturnValueIgnoredRule,
    NullDereferenceRule,
    # Spring Boot framework-aware rules (SAFE9xx band) - Java-only,
    # disabled by default under the vanilla Java preset; enabled by
    # the [tool.safelint.java] framework = "spring-boot" preset.
    # See safelint.rules.spring for the per-rule rationale.
    SpringFieldInjectionRule,
    SpringMissingTransactionalRule,
    SpringUnvalidatedInputRule,
    SpringAsyncCheckedExceptionRule,
    # Rust-idiom rules (slotted into category bands per the SafeLint
    # numbering policy: 1xx function-shape, 2xx error-handling, 3xx
    # side-effects, 6xx documentation). All disabled by default; opt
    # in via [tool.safelint.rules.<name>] enabled = true.
    NeedlessMutRule,
    UncheckedArithmeticOnInputRule,
    PanicMacrosOutsideTestsRule,
    LockPoisoningIgnoredRule,
    SilentResultDiscardRule,
    UnloggedErrorBranchRule,
    ResultUnwrapOutsideTestsRule,
    DangerousMemOpsRule,
    TruncatingAsCastRule,
    UndocumentedUnsafeRule,
    InteriorMutableStaticRule,
]

RULE_BY_NAME: dict[str, type[BaseRule]] = {cls.name: cls for cls in ALL_RULES}

__all__ = [
    "ALL_RULES",
    "RULE_BY_NAME",
    "BareExceptRule",
    "BaseRule",
    "BlanketSuppressionRule",
    "ComplexityRule",
    "DangerousMemOpsRule",
    "DynamicCodeExecutionRule",
    "EmptyExceptRule",
    "FunctionLengthRule",
    "GlobalMutationRule",
    "GlobalStateRule",
    "InteriorMutableStaticRule",
    "LockPoisoningIgnoredRule",
    "LoggingOnErrorRule",
    "MaxArgumentsRule",
    "MissingAssertionsRule",
    "NeedlessMutRule",
    "NestingDepthRule",
    "NoRecursionRule",
    "NullDereferenceRule",
    "PanicMacrosOutsideTestsRule",
    "ResourceLifecycleRule",
    "ResultUnwrapOutsideTestsRule",
    "ReturnValueIgnoredRule",
    "SideEffectsHiddenRule",
    "SideEffectsRule",
    "SilentResultDiscardRule",
    "SpringAsyncCheckedExceptionRule",
    "SpringFieldInjectionRule",
    "SpringMissingTransactionalRule",
    "SpringUnvalidatedInputRule",
    "TaintedSinkRule",
    "TestCouplingRule",
    "TestExistenceRule",
    "TruncatingAsCastRule",
    "UnboundedLoopRule",
    "UncheckedArithmeticOnInputRule",
    "UndocumentedUnsafeRule",
    "UnloggedErrorBranchRule",
    "Violation",
    "WideScopeDeclarationRule",
]
