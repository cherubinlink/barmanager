from django.urls import re_path

from chat.consumers import BarRealtimeConsumer

websocket_urlpatterns = [
    re_path(r"^ws/bar/(?P<bar_id>\d+)/$", BarRealtimeConsumer.as_asgi()),
]
