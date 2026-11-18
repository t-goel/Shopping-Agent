"""Deterministic verification of observed fields, without benchmark answers."""

from typing import Literal

from shopping_agent.comparison import matches
from shopping_agent.contracts import Constraint, Contract, EvidenceItem, ProductObservation
from shopping_agent.interfaces import Claim


class ConstraintCheck(Contract):
    constraint: Constraint
    status: Literal["pass", "fail", "unknown"]


def field_value(observation: ProductObservation, field: str):
    product = observation.product

    if field in type(product).model_fields:
        return getattr(product, field)

    return product.attributes.get(field)


def check_constraints(observation: ProductObservation, constraints: list[Constraint]) -> list[ConstraintCheck]:
    checks = []

    for constraint in constraints:
        if not constraint.hard:
            continue

        value = field_value(observation, constraint.attribute)

        if value is None:
            status = "unknown"
        elif matches(observation.product, constraint):
            status = "pass"
        else:
            status = "fail"

        checks.append(ConstraintCheck(constraint=constraint, status=status))

    return checks


def eligible(observation: ProductObservation, constraints: list[Constraint]) -> bool:
    return observation.product.stock > 0 and all(
        check.status == "pass" for check in check_constraints(observation, constraints)
    )


def verification_failure_reason(
    observation: ProductObservation, constraints: list[Constraint]
) -> str:
    """Explain, in observation form, why a refreshed product failed the gate.

    Names each failed hard constraint (or stock requirement) and the value that was
    actually observed, so an agent can feed the reason back into its ReAct loop and
    pick a different candidate. Unknown fields are reported as failures because the
    gate does not relax a hard constraint it cannot verify.
    """
    product = observation.product
    problems = []

    if product.stock < 1:
        problems.append(f"stock is {product.stock} (at least 1 required)")

    for check in check_constraints(observation, constraints):
        if check.status == "pass":
            continue
        constraint = check.constraint
        observed = field_value(observation, constraint.attribute)
        problems.append(
            f"{constraint.attribute} {constraint.operator} {constraint.value!r} "
            f"{check.status} (observed {observed!r})"
        )

    if not problems:
        return f"{product.product_id} is no longer eligible"
    return "; ".join(problems)


def verify_claims(observation: ProductObservation, claims: list[Claim]) -> list[EvidenceItem]:
    evidence = []

    for claim in claims:
        if claim.product_id != observation.product.product_id:
            raise ValueError("claim and observation product IDs must match")

        observed = field_value(observation, claim.field)

        # Evidence contracts support scalar facts, not composite reviews/attributes.
        if type(observed) not in (str, int, float, bool):
            observed = None

        supported = matches(
            observation.product,
            Constraint(attribute=claim.field, operator="eq", value=claim.value),
        )

        if observed is None:
            status = "unknown"
        elif supported:
            status = "supports"
        else:
            status = "contradicts"

        evidence.append(
            EvidenceItem(
                claim_id=claim.claim_id,
                product_id=claim.product_id,
                field=claim.field,
                claimed_value=claim.value,
                observed_value=observed,
                status=status,
                source_url=observation.source_url,
                observed_at=observation.observed_at,
            )
        )

    return evidence
