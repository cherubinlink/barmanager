from django.db import transaction

from tenants.models import Bar, Subscription


@transaction.atomic
def create_bar(*, owner, name, client_code, **extra) -> Bar:
    """Crée un bar complet : essai 30 j, rôles par défaut, gérant, canal « Équipe »."""
    from accounts.models import BarMembership, Role
    from chat.models import Conversation, ConversationParticipant

    bar = Bar.objects.create(owner=owner, name=name, client_code=client_code, **extra)
    Subscription.start_trial(bar)
    roles = Role.create_defaults(bar)
    BarMembership.objects.create(bar=bar, user=owner, role=roles["gerant"], is_owner=True)
    channel = Conversation.objects.create(
        bar=bar, kind=Conversation.Kind.CHANNEL, name="Équipe",
        is_default_channel=True, created_by=owner,
    )
    ConversationParticipant.objects.create(
        conversation=channel, user=owner, role=ConversationParticipant.Role.ADMIN
    )
    return bar
