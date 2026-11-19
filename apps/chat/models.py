"""
Chat between people involved in the same loan (borrower, investors, people
making offers, guarantor), plus a support line to staff. Offers show up in
the conversation as cards. Anyone can report a person or a message.
"""
import uuid

from django.conf import settings
from django.db import models


class ConversationKind(models.TextChoices):
    LOAN = "LOAN", "About a loan"
    SUPPORT = "SUPPORT", "Support"


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=8, choices=ConversationKind.choices, default=ConversationKind.LOAN)
    loan = models.ForeignKey("loans.Loan", null=True, blank=True, on_delete=models.PROTECT,
                             related_name="conversations")
    # For LOAN chats: the two people (sorted ids) so each pair has one conversation per loan.
    pair_key = models.CharField(max_length=80, blank=True)
    blocked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        constraints = [
            # Support chats have no loan (NULL), and NULLs never collide.
            models.UniqueConstraint(fields=["loan", "pair_key"], name="conversation_one_per_pair_per_loan"),
        ]


class Participant(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_memberships")
    last_read_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["conversation", "user"], name="participant_once"),
        ]


class MessageKind(models.TextChoices):
    TEXT = "TEXT", "Message"
    OFFER = "OFFER", "Offer"
    SYSTEM = "SYSTEM", "Notice"


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="chat_messages")
    kind = models.CharField(max_length=6, choices=MessageKind.choices, default=MessageKind.TEXT)
    body = models.TextField(max_length=2000)
    offer = models.ForeignKey("investments.LoanOffer", null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="messages")
    hidden_by_moderator = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]


class ReportReason(models.TextChoices):
    FRAUD = "FRAUD", "Fraud or scam"
    HARASSMENT = "HARASSMENT", "Harassment or threats"
    SPAM = "SPAM", "Spam"
    IMPERSONATION = "IMPERSONATION", "Pretending to be someone else"
    OFF_PLATFORM = "OFF_PLATFORM", "Asking to pay or lend outside the platform"
    INAPPROPRIATE = "INAPPROPRIATE", "Offensive or inappropriate"
    OTHER = "OTHER", "Something else"


class ReportStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    DISMISSED = "DISMISSED", "Dismissed"
    WARNED = "WARNED", "User warned"
    ACTIONED = "ACTIONED", "Account frozen / message hidden"


class UserReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reports_made")
    reported = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reports_received")
    reason = models.CharField(max_length=14, choices=ReportReason.choices)
    details = models.TextField(max_length=2000)
    message = models.ForeignKey(Message, null=True, blank=True, on_delete=models.SET_NULL, related_name="reports")
    conversation = models.ForeignKey(Conversation, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="reports")
    status = models.CharField(max_length=10, choices=ReportStatus.choices, default=ReportStatus.OPEN, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    resolution = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
