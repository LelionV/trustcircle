"""
Database-portable "unique while a condition holds".

Partial unique indexes (UniqueConstraint(condition=...)) work on SQLite and
PostgreSQL but MySQL ignores them, so the platform uses a flag column instead:
the flag is 1 while the condition holds and NULL otherwise, and an ordinary
unique constraint covers (fields..., flag). Every database treats NULLs as
distinct, so only rows where the condition holds can collide.

    class Guarantee(ConditionalUnique, models.Model):
        CONDITIONAL_UNIQUE = {"live_flag": (lambda g: g.status in LIVE, Q(status__in=LIVE))}
        live_flag = flag_field()
        class Meta:
            constraints = [UniqueConstraint(fields=["loan", "live_flag"], name="...")]

The flag is set on save(). Code that changes the condition with
QuerySet.update() must set the flag too (or call Model.sync_flags()).
"""
from django.db import models


def flag_field():
    return models.PositiveSmallIntegerField(null=True, blank=True, editable=False,
                                            help_text="1 while the unique condition holds, otherwise empty.")


class ConditionalUnique:
    CONDITIONAL_UNIQUE: dict = {}

    def _set_flags(self):
        for flag, (holds, _q) in self.CONDITIONAL_UNIQUE.items():
            setattr(self, flag, 1 if holds(self) else None)

    def save(self, *args, **kwargs):
        self._set_flags()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | set(self.CONDITIONAL_UNIQUE)
        return super().save(*args, **kwargs)

    @classmethod
    def sync_flags(cls):
        """Recompute every flag in bulk (after loaddata or a bulk update)."""
        for flag, (_holds, q) in cls.CONDITIONAL_UNIQUE.items():
            cls._base_manager.filter(q).update(**{flag: 1})
            cls._base_manager.exclude(q).update(**{flag: None})
