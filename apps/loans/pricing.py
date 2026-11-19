"""Interest brackets: the active version, changes, and the rate for a score."""
from django.db import transaction

from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation

from . import calculators as calc
from .defaults import INITIAL_INTEREST_BRACKETS, INITIAL_RATE_BASIS
from .models import InterestBracket, InterestBracketSet


def active_bracket_set():
    current = InterestBracketSet.objects.filter(is_active=True).prefetch_related("brackets").first()
    if current is None:
        with transaction.atomic():
            current = InterestBracketSet.objects.create(version=1, is_active=True, reason="Initial configuration",
                                                        rate_basis=INITIAL_RATE_BASIS)
            InterestBracket.objects.bulk_create([
                InterestBracket(bracket_set=current, min_score=lo, max_score=hi, label=label, annual_rate=rate)
                for lo, hi, label, rate in INITIAL_INTEREST_BRACKETS
            ])
        current = InterestBracketSet.objects.prefetch_related("brackets").get(pk=current.pk)
    return current


def rows(bracket_set):
    return [b.as_row() for b in bracket_set.brackets.all()]


def rate_for_score(score):
    """(bracket_set, bracket_row or None). Row's annual_rate is None for manual review."""
    bracket_set = active_bracket_set()
    if score is None:
        return bracket_set, None
    return bracket_set, calc.find_bracket(rows(bracket_set), score)


@transaction.atomic
def publish_brackets(*, actor, brackets, reason, rate_basis=None, request=None):
    try:
        cleaned = calc.validate_brackets(brackets)
    except calc.BracketError as exc:
        raise BusinessRuleViolation(str(exc), code="invalid_brackets") from exc
    previous = active_bracket_set()
    rate_basis = rate_basis or previous.basis
    if rate_basis not in ("MONTHLY", "ANNUAL", "PER_LOAN"):
        raise BusinessRuleViolation("Choose per month, per year or per loan.", code="invalid_rate_basis")
    latest_version = InterestBracketSet.objects.select_for_update().order_by("-version").first().version
    InterestBracketSet.objects.filter(is_active=True).update(is_active=False, active_flag=None)
    new_set = InterestBracketSet.objects.create(
        version=latest_version + 1, is_active=True, reason=reason, created_by=actor, rate_basis=rate_basis
    )
    InterestBracket.objects.bulk_create([InterestBracket(bracket_set=new_set, **row) for row in cleaned])
    audit.record(
        action="config.brackets.published",
        entity_type="InterestBracketSet",
        entity_id=new_set.pk,
        actor=actor,
        before={"version": previous.version, "rate_basis": previous.basis, "brackets": rows(previous)},
        after={"version": new_set.version, "rate_basis": rate_basis, "brackets": cleaned},
        reason=reason,
        request=request,
    )
    return new_set
