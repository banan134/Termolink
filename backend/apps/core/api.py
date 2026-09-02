"""Core API views. Views hold no business logic (docs/02)."""

from django.db import DatabaseError, connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness/readiness probe: process is up and the database answers."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses=inline_serializer(
            name="Health",
            fields={
                "status": serializers.CharField(),
                "db": serializers.BooleanField(),
            },
        ),
        auth=[],
    )
    def get(self, request: Request) -> Response:
        db_ok = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except DatabaseError:
            db_ok = False
        return Response(
            {"status": "ok" if db_ok else "degraded", "db": db_ok},
            status=200 if db_ok else 503,
        )
