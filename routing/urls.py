from django.urls import path

from routing.views import TripFuelRouteView

urlpatterns = [
    path("route/", TripFuelRouteView.as_view(), name="tripfuel-route"),
]
