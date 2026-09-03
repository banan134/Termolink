"""Alert e-mails (Polish), link back to the SPA alert list."""

from django.conf import settings
from django.core.mail import send_mail

from .models import Alert

SEVERITY_PL = {"info": "informacja", "warning": "ostrzeżenie", "critical": "KRYTYCZNY"}


def send_alert(alert: Alert, recipients: list[str]) -> None:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    link = f"{base}/t/{alert.tenant_id}/alerts" if alert.tenant_id else f"{base}/admin/alerts"
    tenant = alert.tenant.name if alert.tenant is not None else "operator"
    severity = SEVERITY_PL.get(alert.severity, alert.severity)
    send_mail(
        subject=f"Termolink — alarm ({severity}): {alert.message[:80]}",
        message=(
            f"Klient: {tenant}\n"
            f"Typ: {alert.get_type_display()}\n"
            f"Otwarty: {alert.opened_at:%Y-%m-%d %H:%M} UTC\n\n"
            f"{alert.message}\n\n"
            f"Szczegóły i potwierdzenie: {link}\n\n"
            "Termolink · Wodmiar"
        ),
        from_email=None,
        recipient_list=recipients,
    )
