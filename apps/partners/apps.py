from django.apps import AppConfig


class PartnersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.partners"
    label = "partners"
    verbose_name = "Partners + DSAs (US-S23 / ADR-0011)"

    def ready(self) -> None:
        # Attach get_<field>_label methods to Partner (and the rest
        # of the partners-module models as they ship) from the
        # single-source-of-truth choice_field_map (ADR-0010 §5).
        from .choice_field_map import MODEL_FIELDS
        from .models import Partner

        # attach_label_methods accepts a (household_cls, member_cls)
        # pair; reuse it for any partner model by passing the partner
        # class as both args with a per-model field map. For now
        # MODEL_FIELDS only registers Partner; subsequent commits
        # extend this as PartnerContact / Programme / DSA land.
        if "Partner" in MODEL_FIELDS:
            # Borrow the helper indirectly by calling its internal
            # makers — keeps the labels.py contract intact.
            from apps.data_management.labels import (
                _make_multi_label_method,
                _make_single_label_method,
            )
            for field, (list_name, kind) in MODEL_FIELDS["Partner"].items():
                if kind == "multi":
                    setattr(
                        Partner, f"get_{field}_labels",
                        _make_multi_label_method(field, list_name),
                    )
                else:
                    setattr(
                        Partner, f"get_{field}_label",
                        _make_single_label_method(field, list_name),
                    )
