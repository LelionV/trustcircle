from django.contrib import admin

from .models import JournalEntry, LedgerAccount, LedgerLine


class ReadOnly(admin.ModelAdmin):
    """The ledger is append-only: inspect here, change money only through the services."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class LineInline(admin.TabularInline):
    model = LedgerLine
    extra = 0
    can_delete = False
    readonly_fields = ("account", "side", "amount", "memo", "balance_after")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(JournalEntry)
class JournalEntryAdmin(ReadOnly):
    list_display = ("reference", "kind", "description", "created_at")
    list_filter = ("kind",)
    search_fields = ("reference", "external_reference", "description")
    inlines = [LineInline]


@admin.register(LedgerAccount)
class LedgerAccountAdmin(ReadOnly):
    list_display = ("__str__", "kind", "balance")
    list_filter = ("kind",)
    search_fields = ("owner__email",)
