"""
Double-entry ledger.

* LedgerAccount  one per (owner, kind). Platform accounts have no owner.
* JournalEntry   one financial event, with a unique reference and an
                 optional idempotency key so retries never post twice.
* LedgerLine     debit or credit of a positive amount; every entry's debits
                 equal its credits. Lines and entries are never edited or
                 deleted; mistakes are corrected with a reversing entry.

Normal balances
  Credit-normal (what the platform owes, or has earned):
    user WALLET_AVAILABLE, WALLET_PENDING, WALLET_ESCROW, WALLET_FROZEN, WALLET_GUARANTEE_LOCK,
    platform REVENUE_*
  Debit-normal (money the platform holds):
    platform CLEARING_* (money at M-Pesa, the bank or the sandbox)

Invariant checked by reconciliation:
  sum of debit-normal balances == sum of credit-normal balances.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.constraints import ConditionalUnique, flag_field


class AccountKind(models.TextChoices):
    WALLET_AVAILABLE = "WALLET_AVAILABLE", "Available"
    WALLET_PENDING = "WALLET_PENDING", "Withdrawal in progress"
    WALLET_ESCROW = "WALLET_ESCROW", "Committed to loans"
    WALLET_FROZEN = "WALLET_FROZEN", "Held"
    WALLET_GUARANTEE_LOCK = "WALLET_GUARANTEE_LOCK", "Locked for guarantees"
    CLEARING_SANDBOX = "CLEARING_SANDBOX", "Sandbox clearing"
    CLEARING_MPESA = "CLEARING_MPESA", "M-Pesa clearing"
    CLEARING_BANK = "CLEARING_BANK", "Bank clearing"
    CLEARING_GATEWAY = "CLEARING_GATEWAY", "Card and checkout clearing"
    REVENUE_INTEREST = "REVENUE_INTEREST", "Interest commission"
    REVENUE_EXTENSION_INTEREST = "REVENUE_EXTENSION_INTEREST", "Extension interest"
    REVENUE_EXTENSION_FEE = "REVENUE_EXTENSION_FEE", "Extension fees"
    REVENUE_LATE_FEE = "REVENUE_LATE_FEE", "Late payment fees"
    REVENUE_DEPOSIT_FEE = "REVENUE_DEPOSIT_FEE", "Deposit fees"
    REVENUE_WITHDRAWAL_FEE = "REVENUE_WITHDRAWAL_FEE", "Withdrawal fees"
    REVENUE_TRANSFER_FEE = "REVENUE_TRANSFER_FEE", "Transfer fees"
    REVENUE_ACCOUNT_FEE = "REVENUE_ACCOUNT_FEE", "Account management fees"


USER_KINDS = {AccountKind.WALLET_AVAILABLE, AccountKind.WALLET_PENDING, AccountKind.WALLET_ESCROW,
              AccountKind.WALLET_FROZEN, AccountKind.WALLET_GUARANTEE_LOCK}
DEBIT_NORMAL = {AccountKind.CLEARING_SANDBOX, AccountKind.CLEARING_MPESA, AccountKind.CLEARING_BANK,
                AccountKind.CLEARING_GATEWAY}
REVENUE_KINDS = {k for k in AccountKind if k.value.startswith("REVENUE_")}


class LedgerAccount(ConditionalUnique, models.Model):
    CONDITIONAL_UNIQUE = {"platform_flag": (lambda a: a.owner_id is None, Q(owner__isnull=True))}

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                              related_name="ledger_accounts")
    kind = models.CharField(max_length=32, choices=AccountKind.choices)
    currency = models.CharField(max_length=3, default="KES")
    balance = models.DecimalField(max_digits=16, decimal_places=2, default=0,
                                  help_text="Cached; reconciliation re-derives it from the lines.")
    platform_flag = flag_field()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "kind", "currency"], name="ledger_account_unique_owner_kind"),
            models.UniqueConstraint(fields=["kind", "currency", "platform_flag"],
                                    name="ledger_account_unique_platform_kind"),
        ]

    def __str__(self):
        who = self.owner.email if self.owner_id else "Platform"
        return f"{who} {self.get_kind_display()}"

    @property
    def is_debit_normal(self):
        return self.kind in DEBIT_NORMAL


class EntryKind(models.TextChoices):
    DEPOSIT = "DEPOSIT", "Deposit"
    WITHDRAWAL_REQUEST = "WITHDRAWAL_REQUEST", "Withdrawal requested"
    WITHDRAWAL_PAID = "WITHDRAWAL_PAID", "Withdrawal paid out"
    WITHDRAWAL_RETURNED = "WITHDRAWAL_RETURNED", "Withdrawal returned"
    TRANSFER = "TRANSFER", "Transfer"
    INVESTMENT = "INVESTMENT", "Investment committed"
    INVESTMENT_RELEASE = "INVESTMENT_RELEASE", "Investment returned"
    DISBURSEMENT = "DISBURSEMENT", "Loan paid out"
    REPAYMENT = "REPAYMENT", "Loan repayment"
    RECOVERY = "RECOVERY", "Recovery from guarantor"
    FEE = "FEE", "Fee"
    HOLD = "HOLD", "Funds held"
    GUARANTEE_LOCK = "GUARANTEE_LOCK", "Locked for a guarantee"
    GUARANTEE_UNLOCK = "GUARANTEE_UNLOCK", "Guarantee lock released"
    OFFER_HOLD = "OFFER_HOLD", "Held for a loan offer"
    OFFER_RELEASE = "OFFER_RELEASE", "Loan offer returned"
    RELEASE = "RELEASE", "Hold released"
    REVERSAL = "REVERSAL", "Reversal"


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Ledger records can't be edited; post a reversal instead.")

    def delete(self):
        raise PermissionError("Ledger records can't be deleted; post a reversal instead.")


class JournalEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=40, unique=True)
    kind = models.CharField(max_length=24, choices=EntryKind.choices, db_index=True)
    description = models.CharField(max_length=255)
    loan = models.ForeignKey("loans.Loan", null=True, blank=True, on_delete=models.PROTECT, related_name="journal_entries")
    external_reference = models.CharField(max_length=80, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=80, null=True, blank=True, unique=True)
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    reverses = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "journal entries"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Ledger records can't be edited; post a reversal instead.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} {self.get_kind_display()}"


class LedgerLine(models.Model):
    class Side(models.TextChoices):
        DEBIT = "DEBIT", "Debit"
        CREDIT = "CREDIT", "Credit"

    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="lines")
    side = models.CharField(max_length=6, choices=Side.choices)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=3, default="KES")
    memo = models.CharField(max_length=160, blank=True)
    balance_after = models.DecimalField(max_digits=16, decimal_places=2)

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="ledger_line_amount_positive")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Ledger records can't be edited; post a reversal instead.")
        super().save(*args, **kwargs)

    @property
    def signed_for_owner(self):
        """+ when the account balance went up, - when it went down."""
        up = (self.side == self.Side.CREDIT) != self.account.is_debit_normal
        return self.amount if up else -self.amount
