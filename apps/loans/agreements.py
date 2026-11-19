"""
Loan agreements. The text is generated from the locked terms; the borrower
must accept the latest version before the money is paid out, and again
after an extension changes the terms.
"""
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.common.exceptions import BusinessRuleViolation

from .models import LoanAgreement


def _terms(loan):
    installments = list(loan.installments.order_by("sequence"))
    guarantee = loan.guarantees.filter(status__in=["ACCEPTED", "REQUESTED"]).select_related("guarantor").first()
    return {
        "reference": loan.reference,
        "borrower": loan.borrower.full_name,
        "amount": str(loan.amount),
        "annual_rate": str(loan.annual_rate),
        "interest_method": loan.get_interest_method_display(),
        "rate_basis": loan.get_rate_basis_display(),
        "frequency": loan.get_repayment_frequency_display(),
        "installment_count": len(installments),
        "total_interest": str(sum((i.interest for i in installments), 0)),
        "extension_charges": str(sum((i.extension_interest + i.extension_fee for i in installments), 0)),
        "total_repayable": str(sum((i.amount_due for i in installments), 0)),
        "first_due_date": installments[0].due_date.isoformat() if installments else None,
        "final_due_date": installments[-1].due_date.isoformat() if installments else None,
        "guarantor": guarantee.guarantor.full_name if guarantee else None,
        "extensions": loan.extension_count,
        "schedule": [
            {"sequence": i.sequence, "due_date": i.due_date.isoformat(), "amount": str(i.amount_due)}
            for i in installments
        ],
    }


def _text(t, rules):
    overdue = rules["overdue"]
    fee = (f"{overdue['late_fee_value']}% of the installment" if overdue["late_fee_type"] == "PERCENT"
           else f"KES {overdue['late_fee_value']}")
    lines = [
        f"LOAN AGREEMENT {t['reference']}",
        "",
        f"1. {t['borrower']} (the borrower) borrows KES {t['amount']} from the investors who funded this loan "
        f"through P2P Lend.",
        f"2. Interest is {t['annual_rate']}% ({t['rate_basis'].lower()}, {t['interest_method'].lower()}). "
        f"Total interest: KES {t['total_interest']}.",
        f"3. The borrower repays KES {t['total_repayable']} in {t['installment_count']} "
        f"{t['frequency'].lower()} installments, from {t['first_due_date']} to {t['final_due_date']}.",
    ]
    if t["extensions"]:
        lines.append(f"4. This version includes {t['extensions']} approved extension(s) adding KES "
                     f"{t['extension_charges']} in extension charges.")
    lines += [
        f"5. A payment not made within {overdue['grace_days']} days of its due date incurs a late fee of {fee}. "
        f"A loan with a payment more than {overdue['default_after_days']} days overdue is in default.",
        "6. Payments are applied to late fees first, then extension charges, then interest, then principal, "
        "oldest installment first.",
        "7. The borrower may pay ahead at any time with no extra charge; early payments are applied to the "
        "scheduled installments in order (scheduled interest is not recalculated).",
    ]
    if t["guarantor"]:
        lines.append(f"8. {t['guarantor']} guarantees this loan and may be asked to repay what is owed if the "
                     "loan defaults.")
    lines += ["", "By accepting, the borrower agrees to these terms and to the repayment schedule attached."]
    return "\n".join(lines)


@transaction.atomic
def issue(loan):
    from apps.commissions.services import rules

    latest = loan.agreements.order_by("-version").first()
    terms = _terms(loan)
    return LoanAgreement.objects.create(loan=loan, version=(latest.version + 1) if latest else 1, terms=terms,
                                        text=_text(terms, rules()))


def current(loan):
    return loan.agreements.order_by("-version").first()


@transaction.atomic
def accept(loan, user, request=None):
    if loan.borrower_id != user.pk:
        raise BusinessRuleViolation("Only the borrower can accept the agreement.", code="not_owner")
    agreement = current(loan)
    if agreement is None:
        raise BusinessRuleViolation("There's no agreement to accept yet.", code="no_agreement")
    if agreement.accepted_at:
        return agreement
    agreement.accepted_at = timezone.now()
    agreement.accepted_ip = audit._client_ip(request) if request else None
    agreement.save(update_fields=["accepted_at", "accepted_ip"])
    audit.record(action="loan.agreement_accepted", entity_type="Loan", entity_id=loan.pk, actor=user,
                 after={"version": agreement.version}, request=request)
    return agreement
