"""Versioned platform rules: fees, limits, interest split, extensions, overdue handling."""
from apps.common.versioned import VersionedConfig, one_active_constraint, unique_version_constraint


class PlatformRules(VersionedConfig):
    class Meta(VersionedConfig.Meta):
        verbose_name_plural = "platform rules"
        constraints = [
            one_active_constraint("platform_rules_one_active"),
            unique_version_constraint("platform_rules_unique_version"),
        ]
