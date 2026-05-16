"""DQA admin forms (US-076 / DQA-5).

Today the DqaRule admin accepts the JSON expression as a raw textarea
— authors have to know the SAD §4.2.1 DSL grammar to write it. This
module adds a form-based builder that compiles a leaf expression
{field, op, value} from user-friendly form fields and writes the
resulting JSON to DqaRule.expression on save.

Composite expressions (all_of / any_of) remain editable via the JSON
textarea — the wizard targets the 80% case of single-leaf rules. The
admin change form template renders both surfaces in tandem; the
operator picks whichever fits.

Field-selector cascade reads the active FormVersion.schema from
apps.intake. Operator dropdown contents are filtered by the chosen
field's declared type per the brief:

    string   → eq, neq, in, regex
    numeric  → gt, lt, le, ge, between, accuracy_le
    date     → between, gt, lt
    geometry → within_polygon, accuracy_le
    list     → count_eq, count_neq, in, not_in
"""

from __future__ import annotations

import json

from django import forms

from .engine import OPERATORS, DSLError, evaluate_expression
from .models import DqaRule

# Map declared field-type → operator allow-list. Kept on the form (not
# the engine) because this is presentation policy: every operator in
# the registry works on every value type as far as the engine cares,
# but the Rule Editor uses this filter to keep the dropdown sane.
OPERATOR_PALETTE: dict[str, tuple[str, ...]] = {
    "string":   ("eq", "neq", "in", "not_in", "regex"),
    "numeric":  ("gt", "lt", "le", "ge", "between", "accuracy_le", "eq", "neq"),
    "date":     ("between", "gt", "lt", "eq", "neq"),
    "geometry": ("within_polygon", "accuracy_le"),
    "list":     ("count_eq", "count_neq", "in", "not_in"),
    "boolean":  ("eq", "neq"),
}


def _active_form_schema() -> dict:
    """Return the active FormVersion schema, or {} when none seeded.
    Used to populate the cascading entity → section → field dropdown
    in the admin builder.
    """
    try:
        from apps.intake.models import FormVersion
        fv = FormVersion.objects.filter(is_active=True).order_by("-version").first()
        return fv.schema if fv else {}
    except Exception:
        # No intake app, no fixture, no schema — Rule Editor falls
        # back to free-text field path. The wizard becomes a hint,
        # not a constraint.
        return {}


class DqaRuleAdminForm(forms.ModelForm):
    """Admin form for DqaRule with a leaf-expression builder.

    Each `wizard_*` field is opt-in: if the user fills them, the
    form compiles them into the expression JSON on clean(). If they
    leave them blank, the raw JSON textarea wins (matches the legacy
    behaviour authors are used to).
    """

    wizard_field = forms.CharField(
        required=False, label="Wizard: field path",
        help_text=(
            "Dot-notation field path (e.g. surname, gps.acc). When "
            "set, the wizard compiles {field, op, value} into the "
            "expression JSON on save."
        ),
    )
    wizard_field_type = forms.ChoiceField(
        required=False, label="Wizard: field type",
        choices=[("", "—")] + [(k, k.title()) for k in OPERATOR_PALETTE],
        help_text="Filters the operator dropdown below.",
    )
    wizard_op = forms.ChoiceField(
        required=False, label="Wizard: operator",
        choices=[("", "—")] + sorted([(k, k) for k in OPERATORS]) + [
            ("cross_field_eq", "cross_field_eq"),
        ],
    )
    wizard_value = forms.CharField(
        required=False, label="Wizard: value",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=(
            "Literal value or JSON (e.g. 10 for le, [1,2,3] for in, "
            "a WKT POLYGON for within_polygon)."
        ),
    )

    class Meta:
        model = DqaRule
        # Explicit field list per DJ007. Matches the ModelAdmin
        # fieldsets — every editable column lives here; the four
        # wizard_* fields are added by the form above (not model
        # fields, so excluded from the Meta list).
        fields = (
            "rule_id", "version", "status",
            "description", "severity", "applicability_filter",
            "expression", "error_message_template",
            "effective_from", "effective_to",
            "author", "approved_by",
        )

    def clean(self):
        cleaned = super().clean()
        wiz_field = (cleaned.get("wizard_field") or "").strip()
        wiz_op = (cleaned.get("wizard_op") or "").strip()
        wiz_value = (cleaned.get("wizard_value") or "").strip()
        wiz_type = (cleaned.get("wizard_field_type") or "").strip()

        if wiz_field and wiz_op:
            # Coerce value from string per the operator. JSON parsing
            # covers lists, polygons, numbers — fall back to the raw
            # string if parsing fails.
            try:
                value = json.loads(wiz_value) if wiz_value else None
            except json.JSONDecodeError:
                value = wiz_value
            # Operator policy: when the wizard knows the field type
            # AND the operator isn't in the palette for that type,
            # raise — keeps the author from authoring a within_polygon
            # rule on a numeric field by accident.
            if wiz_type and wiz_op not in OPERATOR_PALETTE.get(wiz_type, ()):
                raise forms.ValidationError(
                    f"operator {wiz_op!r} is not valid for field type "
                    f"{wiz_type!r} — choose one of "
                    f"{', '.join(OPERATOR_PALETTE[wiz_type])}",
                )
            cleaned["expression"] = {
                "field": wiz_field, "op": wiz_op, "value": value,
            }

        # Validate whatever ended up in expression by running it
        # through the engine against an empty record — catches
        # unknown operators and malformed all_of/any_of at save time
        # so authors don't get a runtime DSLError in production.
        expr = cleaned.get("expression")
        if expr:
            try:
                evaluate_expression(expr, {})
            except DSLError as e:
                # within_polygon raises on empty field; that's expected
                # and not a save-time error. Other DSLError messages
                # are author bugs.
                msg = str(e).lower()
                if "polygon" not in msg and "cross_field_eq" not in msg:
                    raise forms.ValidationError(f"invalid expression: {e}") from e
        return cleaned
