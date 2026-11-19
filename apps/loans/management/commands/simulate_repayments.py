"""
See the trust engine react to repayment behaviour (DEBUG only).

    python manage.py simulate_repayments borrower@p2plend.local --installments 6 --days-early 7 --complete
    python manage.py simulate_repayments borrower@p2plend.local --installments 3 --days-early -5

Records simulated, fully paid installments for a made-up loan (reference
starting with SIM-) through the same service the repayment engine will use
in Phase 8, then prints the score after each one. This writes simulated
history into your development database; delete db.sqlite3 to start clean.
"""
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.trust_engine.models import LoanOutcome, TrustScore
from apps.trust_engine.services import record_installment_payment, record_loan_outcome


class Command(BaseCommand):
    help = "Simulate repayments for a borrower to watch their trust score change (development only)."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--installments", type=int, default=6)
        parser.add_argument("--days-early", type=int, default=7, help="Negative for late payments.")
        parser.add_argument("--amount", default="5000.00")
        parser.add_argument("--complete", action="store_true", help="Mark the simulated loan as repaid in full.")
        parser.add_argument("--default", action="store_true", help="Mark the simulated loan as defaulted.")

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("simulate_repayments only runs with DEBUG=True.")
        user = User.objects.filter(email=opts["email"].lower()).first()
        if user is None or user.role != Role.BORROWER:
            raise CommandError("Give the email of an existing borrower.")
        score = TrustScore.objects.filter(user=user).first()
        if score is None or score.score is None:
            raise CommandError("This borrower has no trust score yet. Approve their identity documents first.")

        loan_ref = f"SIM-{secrets.token_hex(4).upper()}"
        today = timezone.localdate()
        self.stdout.write(f"Simulated loan {loan_ref}; starting score {score.score}")
        for k in range(1, opts["installments"] + 1):
            due = today - timedelta(days=30 * (opts["installments"] - k + 1))
            record = record_installment_payment(
                user=user, loan_reference=loan_ref, installment_reference=f"{loan_ref}-{k}",
                due_date=due, paid_on=due - timedelta(days=opts["days_early"]),
                amount_due=Decimal(opts["amount"]), amount_paid=Decimal(opts["amount"]),
            )
            score.refresh_from_db()
            self.stdout.write(f"  installment {k}: {record.counted_points:+d} points -> score {score.score} "
                              f"({score.get_confidence_display()})")
        if opts["complete"] or opts["default"]:
            outcome = LoanOutcome.Outcome.DEFAULTED if opts["default"] else LoanOutcome.Outcome.COMPLETED
            record_loan_outcome(user=user, loan_reference=loan_ref, outcome=outcome)
            score.refresh_from_db()
            self.stdout.write(f"  loan {outcome.label.lower()} -> score {score.score}")
        self.stdout.write(self.style.SUCCESS(f"Final score {score.score}"))
