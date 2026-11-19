from django.urls import path

from .views import MeView, ProfileDetailsView

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("me/profile/", ProfileDetailsView.as_view(), name="me-profile"),
]
