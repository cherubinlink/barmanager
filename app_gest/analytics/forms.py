from datetime import timedelta

from django import forms

MAX_RANGE_DAYS = 400


def _date():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class RangeForm(forms.Form):
    """Période d'analyse : un raccourci (7, 30, 90 jours, 12 mois) ou deux dates. Tous les champs sont facultatifs."""

    DAYS = [("7", "7 derniers jours"), ("30", "30 derniers jours"), ("90", "90 derniers jours"), ("365", "12 derniers mois")]
    days = forms.ChoiceField(label="Période", choices=DAYS, required=False)
    start = forms.DateField(label="Du", required=False, widget=_date())
    end = forms.DateField(label="Au", required=False, widget=_date())

    def bounds(self, today):
        """(début, fin) à appliquer. À appeler après is_valid()."""
        d = getattr(self, "cleaned_data", {})
        start, end = d.get("start"), d.get("end")
        if start and end:
            if start > end:
                start, end = end, start
            return max(start, end - timedelta(days=MAX_RANGE_DAYS - 1)), end
        days = int(d.get("days") or 30)
        return today - timedelta(days=days - 1), today


class RankingForm(RangeForm):
    SORTS = [("revenue", "Chiffre d'affaires"), ("qty", "Quantités vendues"), ("margin", "Marge"), ("lost", "Pertes")]
    sort = forms.ChoiceField(label="Trier par", choices=SORTS, required=False)
    q = forms.CharField(label="Produit", max_length=80, required=False)


class ForecastFilterForm(forms.Form):
    WITHIN = [("3", "Sous 3 jours"), ("7", "Sous 7 jours"), ("14", "Sous 14 jours"), ("30", "Sous 30 jours")]
    within = forms.ChoiceField(label="Rupture probable", choices=WITHIN, required=False)
    q = forms.CharField(label="Produit", max_length=80, required=False)