from django.apps import AppConfig


class PartnersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.partners"
    label = "partners"
    verbose_name = "Partners + DSAs (US-S23 / ADR-0011)"

    def ready(self) -> None:
        # Attach get_<field>_label methods to every partners-module
        # model from the single-source-of-truth choice_field_map
        # (ADR-0010 §5). MODEL_FIELDS holds one entry per model.
        from django.apps import apps as django_apps

        from apps.data_management.labels import (
            _make_multi_label_method,
            _make_single_label_method,
        )

        from .choice_field_map import MODEL_FIELDS

        for model_name, fmap in MODEL_FIELDS.items():
            try:
                model = django_apps.get_model("partners", model_name)
            except LookupError:
                # Model not yet shipped; skip silently. E001 will flag
                # if a referenced model is missing.
                continue
            for field, (list_name, kind) in fmap.items():
                if kind == "multi":
                    setattr(
                        model, f"get_{field}_labels",
                        _make_multi_label_method(field, list_name),
                    )
                else:
                    setattr(
                        model, f"get_{field}_label",
                        _make_single_label_method(field, list_name),
                    )
