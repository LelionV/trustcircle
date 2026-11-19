from django.urls import path

from . import views

urlpatterns = [
    path("overview/", views.OverviewView.as_view(), name="admin-overview"),
    path("users/", views.UserListView.as_view(), name="admin-users"),
    path("users/<uuid:pk>/", views.UserDetailView.as_view(), name="admin-user-detail"),
    path("users/<uuid:pk>/freeze/", views.FreezeUserView.as_view(), name="admin-user-freeze"),
    path("users/<uuid:pk>/unfreeze/", views.UnfreezeUserView.as_view(), name="admin-user-unfreeze"),
    path("users/<uuid:pk>/role/", views.RoleChangeView.as_view(), name="admin-user-role"),
    path("users/<uuid:pk>/trust/adjust/", views.TrustAdjustView.as_view(), name="admin-user-trust-adjust"),
    path("users/<uuid:pk>/risk/override/", views.RiskOverrideView.as_view(), name="admin-user-risk-override"),
    path("audit-logs/", views.AuditLogListView.as_view(), name="admin-audit-logs"),
    path("config/", views.ConfigView.as_view(), name="admin-config"),
    path("config/brackets/", views.BracketConfigView.as_view(), name="admin-config-brackets"),
    path("config/trust/", views.TrustConfigView.as_view(), name="admin-config-trust"),
    path("config/risk/", views.RiskConfigView.as_view(), name="admin-config-risk"),
]
