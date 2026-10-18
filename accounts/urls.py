from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("accounts/login/", views.login_view, name="accounts_login"),
    path("logout/", views.logout_view, name="logout"),
    path("api/auth/whoami/", views.whoami_view, name="whoami"),
]
