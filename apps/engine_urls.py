"""URLs for the trust and risk engines (signed-in user's own score and rating)."""
from django.urls import path

from apps.risk_engine.views import MyRiskView
from apps.trust_engine.views import MyTrustView

urlpatterns = [
    path("trust/me/", MyTrustView.as_view(), name="trust-me"),
    path("risk/me/", MyRiskView.as_view(), name="risk-me"),
]
