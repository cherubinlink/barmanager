from django import forms

from .models import NotificationPreference, NotificationType

CHANNELS = [("in_app", "Dans l'application"), ("push", "Push"), ("sms", "SMS"), ("email", "E-mail")]
DEFAULTS = {"in_app": True, "push": True, "sms": False, "email": False}


class PreferencesForm(forms.Form):
    """Une case par type de notification et par canal (champs « TYPE__canal »)."""

    def __init__(self, *args, user, bar, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.bar = user, bar
        existing = {p.type: p for p in NotificationPreference.objects.filter(user=user, bar=bar)}
        for value, _label in NotificationType.choices:
            pref = existing.get(value)
            for channel, _ in CHANNELS:
                self.fields[f"{value}__{channel}"] = forms.BooleanField(
                    required=False, initial=getattr(pref, channel) if pref else DEFAULTS[channel])

    def rows(self):
        """[{type, label, fields: [boundfield par canal]}] pour afficher le tableau."""
        return [{"type": value, "label": label,
                 "fields": [self[f"{value}__{channel}"] for channel, _ in CHANNELS]}
                for value, label in NotificationType.choices]

    def save(self):
        for value, _label in NotificationType.choices:
            values = {channel: self.cleaned_data[f"{value}__{channel}"] for channel, _ in CHANNELS}
            NotificationPreference.objects.update_or_create(
                user=self.user, bar=self.bar, type=value, defaults=values)   # conserve muted_until


class MuteForm(forms.Form):
    DURATIONS = [("1", "1 heure"), ("8", "8 heures"), ("24", "24 heures"), ("0", "Réactiver maintenant")]
    hours = forms.ChoiceField(label="Mettre en sourdine", choices=DURATIONS)