from .models import Notification


def notify_branch(branch, notification_type, title, message, priority="INFO"):
    from apps.accounts.models import User

    users = User.objects.filter(is_active=True).filter(branch=branch)
    for u in users:
        Notification.objects.create(
            user=u,
            branch=branch,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
        )
