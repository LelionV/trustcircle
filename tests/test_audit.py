from decimal import Decimal

import pytest

from apps.audit import services
from apps.audit.models import AuditLog, ImmutableRecordError

pytestmark = pytest.mark.django_db


def test_record_creates_entry_with_json_safe_values(borrower):
    entry = services.record(
        action="config.interest_bracket.updated",
        entity_type="InterestBracket",
        entity_id=1,
        actor=borrower,
        before={"rate": Decimal("18.00")},
        after={"rate": Decimal("15.00")},
        reason="Quarterly pricing review",
    )
    entry.refresh_from_db()
    assert entry.before == {"rate": "18.00"}
    assert entry.after == {"rate": "15.00"}
    assert entry.actor == borrower


def test_entries_cannot_be_modified_or_deleted():
    entry = services.record(action="test", entity_type="X", entity_id="1")
    entry.reason = "tamper"
    with pytest.raises(ImmutableRecordError):
        entry.save()
    with pytest.raises(ImmutableRecordError):
        entry.delete()
    with pytest.raises(ImmutableRecordError):
        AuditLog.objects.filter(pk=entry.pk).update(reason="tamper")
    with pytest.raises(ImmutableRecordError):
        AuditLog.objects.all().delete()
