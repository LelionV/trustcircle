from django.urls import path

from .views import web_app

urlpatterns = [
    path("", web_app, name="web-app"),
]
