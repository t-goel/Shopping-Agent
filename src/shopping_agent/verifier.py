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
