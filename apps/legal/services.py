"""Reading, accepting and publishing the terms and conditions."""
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation

from .models import TermsAcceptance, TermsDocument


def current_terms():
    return TermsDocument.objects.filter(is_active=True).first()


def acceptance_status(user):
    """{'terms': active TermsDocument or None, 'accepted': bool}. With no published terms nothing is blocked."""
    terms = current_terms()
    if terms is None:
        return {"terms": None, "accepted": True}
    return {"terms": terms, "accepted": TermsAcceptance.objects.filter(user=user, terms=terms).exists()}


def pending_terms_for(user):
    """The version the user still has to accept, or None."""
    status = acceptance_status(user)
    return None if status["accepted"] else status["terms"]


@transaction.atomic
def accept(user, *, ip=None, user_agent=""):
    terms = current_terms()
    if terms is None:
        raise BusinessRuleViolation("There are no terms to accept right now.", code="no_terms")
    TermsAcceptance.objects.get_or_create(
        user=user, terms=terms,
        defaults={"ip_address": ip or None, "user_agent": (user_agent or "")[:255], "accepted_at": timezone.now()},
    )
    return terms


@transaction.atomic
def publish(actor, *, title, body, request=None):
    """Create the next version and make it the only active one. Existing acceptances stay on record."""
    latest = TermsDocument.objects.order_by("-version").values_list("version", flat=True).first() or 0
    TermsDocument.objects.filter(is_active=True).update(is_active=False)
    terms = TermsDocument.objects.create(
        version=latest + 1, title=title.strip(), body=body.strip(), is_active=True,
        published_at=timezone.now(), published_by=actor,
    )
    audit.record(action="terms.published", entity_type="TermsDocument", entity_id=terms.pk, actor=actor,
                 after={"version": terms.version, "title": terms.title}, request=request)
    return terms
