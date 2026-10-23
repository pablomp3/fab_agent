from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Predicate, PredicateSet, Verdict


@dataclass(frozen=True, slots=True)
class ConstraintRule:
    require_all: frozenset[Predicate] = frozenset()
    forbid_any: frozenset[Predicate] = frozenset()
    veto_if_any: frozenset[Predicate] = frozenset()


@dataclass(frozen=True, slots=True)
class ConstraintResult:
    verdict: Verdict
    satisfied: tuple[Predicate, ...]
    unmet: tuple[Predicate, ...]
    forbidden: tuple[Predicate, ...]
    vetoed: tuple[Predicate, ...]


def evaluate_rule(rule: ConstraintRule, predicates: PredicateSet) -> ConstraintResult:
    vetoed = tuple(
        sorted(
            (item for item in rule.veto_if_any if predicates.enabled(item)),
            key=lambda item: item.value,
        )
    )
    unmet = tuple(
        sorted(
            (item for item in rule.require_all if not predicates.enabled(item)),
            key=lambda item: item.value,
        )
    )
    forbidden = tuple(
        sorted(
            (item for item in rule.forbid_any if predicates.enabled(item)),
            key=lambda item: item.value,
        )
    )
    satisfied = tuple(
        sorted(
            (item for item in rule.require_all if predicates.enabled(item)),
            key=lambda item: item.value,
        )
    )
    if vetoed:
        verdict = Verdict.VETOED
    elif unmet or forbidden:
        verdict = Verdict.INSUFFICIENT
    else:
        verdict = Verdict.SUPPORTED
    return ConstraintResult(verdict, satisfied, unmet, forbidden, vetoed)
