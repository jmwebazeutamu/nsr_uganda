"""US-122 regression tests: unknown choice codes wait in DIH, never coerce."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.management import call_command

from apps.ingestion_hub.models import (
    Connector,
    DataProvisionAgreement,
    MappingRule,
    MappingRuleVersion,
    SourceSystem,
    SourceSystemKind,
    StageRecordState,
    UnmappedChoiceValue,
)
from apps.ingestion_hub.services import (
    DihError,
    land_payload,
    process_stage_record,
    promote_stage_record,
    stage_from_landing,
    start_connector_run,
)
from apps.reference_data.models import ChoiceList, ChoiceListStatus, ChoiceOption


@pytest.fixture
def choice_source(db):
    source = SourceSystem.objects.create(
        code="US122-SOURCE", name="US-122 source", kind=SourceSystemKind.UBOS,
        # US-122's control is that an uninterpretable code stops the
        # wave. That used to be implied by `kind == UBOS` in the service;
        # it is now stated on the source system, so a test about
        # blocking has to configure blocking. Migration
        # ingestion_hub.0009 sets it on the UBOS rows that already
        # existed.
        blocks_on_unmapped_choice_value=True,
    )
    DataProvisionAgreement.objects.create(
        source_system=source, reference="DPA-US122",
        valid_from=date(2026, 1, 1), valid_to=date(2030, 1, 1),
    )
    return source


@pytest.fixture
def approved_sex_list(db):
    # The Questionnaire/Reference Data migration owns the production sex
    # list.  Tests use that same registry record rather than manufacturing a
    # parallel list with the same canonical identifier.
    choices = ChoiceList.objects.filter(
        list_name="sex", status=ChoiceListStatus.ACTIVE,
    ).order_by("-version").first()
    if choices is None:
        choices = ChoiceList.objects.create(
            list_name="sex", version=99, description="test sex codes",
            effective_from=date(2026, 1, 1), status=ChoiceListStatus.ACTIVE,
            author="author", approved_by="approver",
        )
    ChoiceOption.objects.get_or_create(
        choice_list=choices, code="M", language="en",
        defaults={"label": "Male", "status": ChoiceOption.Status.ACTIVE},
    )
    return choices


def _mapping_version(source):
    rule = MappingRule.objects.create(
        source_system=source, code="US122-QUESTIONNAIRE", description="test mapping",
    )
    return MappingRuleVersion.objects.create(
        rule=rule, version=1, spec={}, is_active=True,
    )


def _stage(source, payload, *, source_reference="wave-us122", mapping_version=None):
    connector = Connector.objects.create(source_system=source, name="US-122 import")
    run = start_connector_run(connector)
    landing = land_payload(run, {"source_answer": payload}, source_reference=source_reference)
    return stage_from_landing(
        landing, canonical_payload=payload,
        mapping_rule_version=mapping_version or _mapping_version(source),
    ), landing


@pytest.mark.django_db
class TestUnmappedChoiceCodes:
    def test_unknown_code_is_preserved_visible_and_blocks_staging(
        self, choice_source, approved_sex_list,
    ):
        payload = {"members": [{"line_number": 1, "sex": "X-UNDECIDED"}]}
        stage, landing = _stage(choice_source, payload)

        occurrence = UnmappedChoiceValue.objects.get(stage_record=stage)
        assert occurrence.canonical_path == "members.0.sex"
        assert occurrence.choice_list_name == "sex"
        assert occurrence.source_code == "X-UNDECIDED"
        assert stage.state == StageRecordState.QUALITY_FAILED
        assert stage.dqa_summary["blocking_failures"][0]["source_code"] == "X-UNDECIDED"
        with pytest.raises(DihError, match="unmapped"):
            promote_stage_record(stage, actor="us122-promoter")
        landing.refresh_from_db()
        assert landing.payload == {"source_answer": payload}

        # The queue/API projection reads the persisted DIH fact; no client
        # side mapping or sample data is needed to make the problem visible.
        from apps.ingestion_hub.api import StageRecordSerializer
        projected = StageRecordSerializer(stage).data["unmapped_choice_values"]
        assert projected[0]["choice_list"] == "sex"
        assert projected[0]["source_code"] == "X-UNDECIDED"

    def test_exact_approved_code_is_not_marked_unmapped(
        self, choice_source, approved_sex_list,
    ):
        stage, _ = _stage(choice_source, {"members": [{"line_number": 1, "sex": "M"}]})

        assert not UnmappedChoiceValue.objects.filter(stage_record=stage).exists()
        process_stage_record(stage, actor="us122-test", allow_fast_track=False)
        stage.refresh_from_db()
        assert stage.state != StageRecordState.QUALITY_FAILED

    def test_report_groups_records_by_canonical_item_code_and_wave(
        self, choice_source, approved_sex_list, capsys,
    ):
        connector = Connector.objects.create(source_system=choice_source, name="US-122 wave")
        run = start_connector_run(connector)
        mapping_version = _mapping_version(choice_source)
        for reference in ("household-a", "household-b"):
            payload = {"members": [{"line_number": 1, "sex": "X-UNDECIDED"}]}
            landing = land_payload(run, {"source": reference}, source_reference=reference)
            stage_from_landing(
                landing, canonical_payload=payload,
                mapping_rule_version=mapping_version,
            )

        call_command("report_unmapped_codes", "--format", "csv")
        report = capsys.readouterr().out
        assert "source_system,wave_run,choice_list,canonical_path,source_code,records" in report
        assert "US122-SOURCE" in report
        assert "members.0.sex" in report
        assert "X-UNDECIDED" in report
        assert ",2," in report


class TestEveryPayloadIsChecked:
    """The gate used to run for UBOS only.

    `sync_unmapped_choice_values` returned early unless the source kind
    was UBOS, on the stated grounds that other connectors had not been
    admitted to the Questionnaire/ChoiceList contract. Kobo is admitted:
    its canonical payload resolves through PAYLOAD_FIELDS to the right
    list, and 114 of 1,087 codes on the most recent wave are housing
    codes from the retired frame. Those findings were being skipped.
    """

    @pytest.fixture
    def kobo_source(self, db, approved_sex_list):
        source = SourceSystem.objects.create(
            code="KOBO-CHECK", name="Kobo check", kind=SourceSystemKind.KOBO,
        )
        DataProvisionAgreement.objects.create(
            source_system=source, reference="DPA-KOBO-CHECK",
            valid_from=date(2026, 1, 1), valid_to=date(2030, 12, 31),
        )
        return source

    PAYLOAD = {"members": [{"line_number": 1, "sex": "X-UNDECIDED"}]}

    def test_a_kobo_code_outside_the_list_is_recorded(self, kobo_source):
        """The finding exists, which it did not before."""
        stage, _landing = _stage(kobo_source, self.PAYLOAD)
        rows = stage.unmapped_choice_values.filter(is_current=True)
        assert [r.source_code for r in rows] == ["X-UNDECIDED"]

    def test_recording_is_not_blocking(self, kobo_source):
        """391 of 392 households on the current Kobo wave carry a
        retired housing code. Failing them all would stop national
        intake without fixing the form, so the observation is written
        and the record proceeds."""
        stage, _landing = _stage(kobo_source, self.PAYLOAD)
        assert stage.state != StageRecordState.QUALITY_FAILED

    def test_a_non_blocking_finding_is_not_reported_as_blocking(
        self, kobo_source,
    ):
        """A BLOCK severity routes the record to QUALITY_FAILED
        downstream, so the DQA contract must not say "blocked" while the
        policy says "proceed" — the record would stop one step later
        with a worse message."""
        stage, _landing = _stage(kobo_source, self.PAYLOAD)
        summary = stage.dqa_summary or {}
        assert summary.get("blocking_failures") == []
        assert summary.get("flagged"), "the finding must still be reported"

    def test_a_blocking_source_still_stops(self, kobo_source):
        """The policy is configuration, not the connector's kind."""
        kobo_source.blocks_on_unmapped_choice_value = True
        kobo_source.save(update_fields=["blocks_on_unmapped_choice_value"])
        stage, _landing = _stage(kobo_source, self.PAYLOAD)
        assert stage.state == StageRecordState.QUALITY_FAILED
        assert stage.dqa_summary["blocking_failures"]

    def test_a_valid_code_records_nothing(self, kobo_source):
        """The check has to be able to pass, or it says nothing."""
        stage, _landing = _stage(
            kobo_source, {"members": [{"line_number": 1, "sex": "1"}]},
        )
        assert not stage.unmapped_choice_values.filter(is_current=True).exists()
