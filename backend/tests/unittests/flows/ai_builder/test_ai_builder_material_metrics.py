from __future__ import annotations

from intric.flows.ai_builder.ai_builder_material_metrics import (
    MaterialMetricStep,
    compute_material_metrics,
    compute_per_step_material_metrics,
    compute_step_material_metrics,
)


def _metric_step(
    *,
    ref: str,
    order: int,
    input_source: str = "previous_step",
    input_type: str = "text",
    output_type: str = "text",
    question: str = "",
) -> MaterialMetricStep:
    return MaterialMetricStep(
        step_ref=ref,
        step_order=order,
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        question=question,
    )


def test_compute_material_metrics_counts_section_chain_material_costs() -> None:
    steps = (
        _metric_step(
            ref="step_a",
            order=1,
            input_source="flow_input",
            input_type="audio",
            output_type="text",
        ),
        _metric_step(ref="step_b", order=2, output_type="json"),
        _metric_step(
            ref="step_c",
            order=3,
            input_type="json",
            output_type="text",
            question=(
                "{{ step_b.output.structured.summary }}\n"
                "{{ step_b.output.structured.decisions }}\n"
                "{{ step_a.output.text }}"
            ),
        ),
    )

    metrics = compute_material_metrics(steps)

    assert metrics.binding_bytes == len(steps[2].question.encode("utf-8"))
    assert metrics.fan_in_width == 2
    assert metrics.structured_field_count == 2
    assert metrics.whole_output_reference_count == 1
    assert metrics.source_duplication_count == 1
    assert metrics.all_previous_steps_count == 0


def test_source_duplication_counts_document_and_audio_sources_but_not_text_drafts() -> (
    None
):
    steps = (
        _metric_step(
            ref="step_a",
            order=1,
            input_source="flow_input",
            input_type="text",
            output_type="text",
        ),
        _metric_step(
            ref="step_b",
            order=2,
            input_source="flow_input",
            input_type="document",
            output_type="text",
        ),
        _metric_step(
            ref="step_c",
            order=3,
            question="{{ step_a.output.text }}\n{{ step_b.output.text }}",
        ),
    )

    metrics = compute_material_metrics(steps)

    assert metrics.fan_in_width == 2
    assert metrics.whole_output_reference_count == 2
    assert metrics.source_duplication_count == 1


def test_source_duplication_excludes_audio_source_when_output_is_json() -> None:
    steps = (
        _metric_step(
            ref="step_a",
            order=1,
            input_source="flow_input",
            input_type="audio",
            output_type="json",
        ),
        _metric_step(ref="step_b", order=2, question="{{ step_a.output.text }}"),
    )

    metrics = compute_material_metrics(steps)

    assert metrics.whole_output_reference_count == 1
    assert metrics.source_duplication_count == 0


def test_runtime_and_form_field_references_do_not_count_as_step_fan_in() -> None:
    steps = (
        _metric_step(
            ref="step_a",
            order=1,
            input_source="flow_input",
            question="{{ step_input.text }} {{ customer_name }}",
        ),
    )

    metrics = compute_material_metrics(steps, form_field_names={"customer_name"})

    assert metrics.fan_in_width == 0
    assert metrics.binding_bytes == len(steps[0].question.encode("utf-8"))
    assert metrics.runtime_input_reference_count == 1
    assert metrics.form_field_reference_count == 1


def test_all_previous_steps_count_is_independent_from_targeted_references() -> None:
    steps = (
        _metric_step(ref="step_a", order=1, input_source="flow_input"),
        _metric_step(ref="step_b", order=2, input_source="all_previous_steps"),
        _metric_step(ref="step_c", order=3, question="{{ step_a.output.text }}"),
    )

    metrics = compute_material_metrics(steps)

    assert metrics.all_previous_steps_count == 1
    assert metrics.fan_in_width == 1


def test_whole_structured_reference_is_not_a_structured_field_reference() -> None:
    steps = (
        _metric_step(ref="step_a", order=1, input_source="flow_input"),
        _metric_step(
            ref="step_b",
            order=2,
            question="{{ step_a.output.structured }}\n{{ step_a.output.structured.foo }}",
        ),
    )

    metrics = compute_material_metrics(steps)

    assert metrics.whole_output_reference_count == 1
    assert metrics.structured_field_count == 1


def test_step_metrics_use_utf8_binding_bytes_and_local_all_previous_count() -> None:
    steps = (
        _metric_step(ref="step_a", order=1, input_source="flow_input"),
        _metric_step(ref="step_b", order=2, input_source="all_previous_steps"),
        _metric_step(ref="step_c", order=3, question="{{ step_a.output.text }} åäö"),
    )

    targeted_metrics = compute_step_material_metrics(steps, step_order=3)
    all_previous_metrics = compute_step_material_metrics(steps, step_order=2)

    assert targeted_metrics.binding_bytes == len(
        "{{ step_a.output.text }} åäö".encode("utf-8")
    )
    assert targeted_metrics.fan_in_width == 1
    assert targeted_metrics.all_previous_steps_count == 0
    assert all_previous_metrics.all_previous_steps_count == 1


def test_per_step_metrics_sum_to_aggregate_for_additive_material_costs() -> None:
    steps = (
        _metric_step(
            ref="step_a",
            order=1,
            input_source="flow_input",
            input_type="audio",
            output_type="text",
        ),
        _metric_step(
            ref="step_b",
            order=2,
            output_type="json",
            question="{{ step_a.output.text }}",
        ),
        _metric_step(
            ref="step_c",
            order=3,
            output_type="json",
            question=(
                "{{ step_b.output.structured }}\n"
                "{{ step_b.output.structured.summary }}\n"
                "{{ step_a.output.text }}"
            ),
        ),
    )

    aggregate = compute_material_metrics(steps)
    per_step = compute_per_step_material_metrics(steps)

    assert [step_order for step_order, _metrics in per_step] == [1, 2, 3]
    assert sum(metrics.binding_bytes for _step_order, metrics in per_step) == (
        aggregate.binding_bytes
    )
    assert (
        sum(metrics.source_duplication_count for _step_order, metrics in per_step)
        == aggregate.source_duplication_count
    )
    assert (
        sum(metrics.whole_output_reference_count for _step_order, metrics in per_step)
        == aggregate.whole_output_reference_count
    )
    assert (
        sum(metrics.structured_field_count for _step_order, metrics in per_step)
        == aggregate.structured_field_count
    )
    assert aggregate.fan_in_width == 2
    assert sum(metrics.fan_in_width for _step_order, metrics in per_step) == 3
    assert sum(
        metrics.all_previous_steps_count for _step_order, metrics in per_step
    ) == (aggregate.all_previous_steps_count)
    assert (
        sum(metrics.runtime_input_reference_count for _step_order, metrics in per_step)
        == aggregate.runtime_input_reference_count
    )
    assert (
        sum(metrics.form_field_reference_count for _step_order, metrics in per_step)
        == aggregate.form_field_reference_count
    )
    assert (
        sum(metrics.text_prior_count for _step_order, metrics in per_step)
        == aggregate.text_prior_count
    )
    assert (
        sum(metrics.text_prior_ref_count for _step_order, metrics in per_step)
        == aggregate.text_prior_ref_count
    )


def test_structured_prior_coverage_detects_missing_json_priors_for_composer() -> (
    None
):
    steps = (
        _metric_step(ref="step_a", order=1, output_type="text"),
        _metric_step(ref="step_b", order=2, output_type="json"),
        _metric_step(ref="step_c", order=3, output_type="json"),
        _metric_step(ref="step_d", order=4, output_type="json"),
        _metric_step(
            ref="step_e",
            order=5,
            output_type="text",
            question=(
                "{{ step_b.output.structured.problem }}\n"
                "{{ step_d.output.structured.plan }}"
            ),
        ),
    )

    final_metrics = compute_step_material_metrics(steps, step_order=5)

    assert final_metrics.structured_prior_count == 3
    assert final_metrics.structured_prior_ref_count == 2
    assert final_metrics.structured_prior_coverage_ratio == 2 / 3
    assert final_metrics.missing_structured_prior_steps == ("step_c",)
    assert final_metrics.whole_output_reference_count == 0


def test_multi_section_report_composer_golden_uses_targeted_fields_without_blobs() -> (
    None
):
    steps = (
        _metric_step(ref="step_a", order=1, input_source="flow_input"),
        _metric_step(ref="step_b", order=2, output_type="json"),
        _metric_step(ref="step_c", order=3, output_type="json"),
        _metric_step(ref="step_d", order=4, output_type="json"),
        _metric_step(
            ref="step_e",
            order=5,
            output_type="text",
            question=(
                "Problem: {{ step_b.output.structured.problem }}\n"
                "Lösning: {{ step_c.output.structured.solution }}\n"
                "Tidplan: {{ step_d.output.structured.timeline }}"
            ),
        ),
    )

    final_metrics = compute_step_material_metrics(steps, step_order=5)

    assert final_metrics.structured_prior_count == 3
    assert final_metrics.structured_prior_ref_count == 3
    assert final_metrics.structured_prior_coverage_ratio == 1.0
    assert final_metrics.missing_structured_prior_steps == ()
    assert final_metrics.whole_output_reference_count == 0


def test_text_prior_coverage_detects_hidden_all_previous_final_assembler() -> None:
    steps = (
        _metric_step(
            ref="step_a",
            order=1,
            input_source="flow_input",
            input_type="document",
            output_type="text",
        ),
        _metric_step(ref="step_b", order=2, output_type="json"),
        _metric_step(ref="step_c", order=3, output_type="text"),
        _metric_step(ref="step_d", order=4, output_type="text"),
        _metric_step(
            ref="step_e",
            order=5,
            input_source="all_previous_steps",
            output_type="text",
        ),
        _metric_step(ref="step_f", order=6, output_type="docx"),
    )

    final_metrics = compute_step_material_metrics(steps, step_order=5)

    assert final_metrics.text_prior_count == 2
    assert final_metrics.text_prior_ref_count == 0
    assert final_metrics.text_prior_coverage_ratio == 0.0
    assert final_metrics.missing_text_prior_steps == ("step_c", "step_d")
    assert final_metrics.all_previous_steps_count == 1


def test_multi_section_report_composer_golden_uses_section_outputs_without_source_blob() -> (
    None
):
    steps = (
        _metric_step(
            ref="step_a",
            order=1,
            input_source="flow_input",
            input_type="document",
            output_type="text",
        ),
        _metric_step(ref="step_b", order=2, output_type="json"),
        _metric_step(ref="step_c", order=3, output_type="text"),
        _metric_step(ref="step_d", order=4, output_type="text"),
        _metric_step(
            ref="step_e",
            order=5,
            output_type="text",
            question=(
                "Section one: {{ step_c.output.text }}\n"
                "Section two: {{ step_d.output.text }}"
            ),
        ),
        _metric_step(ref="step_f", order=6, output_type="docx"),
    )

    final_metrics = compute_step_material_metrics(steps, step_order=5)

    assert final_metrics.text_prior_count == 2
    assert final_metrics.text_prior_ref_count == 2
    assert final_metrics.text_prior_coverage_ratio == 1.0
    assert final_metrics.missing_text_prior_steps == ()
    assert final_metrics.source_duplication_count == 0


def test_canonical_wide_targeted_fan_in_keeps_source_duplication_per_step_bounded() -> (
    None
):
    section_steps = tuple(
        _metric_step(
            ref=f"step_{letter}",
            order=order,
            output_type="json",
            question=(
                f"{{{{ step_{chr(ord(letter) - 1)}.output.structured }}}}\n\n"
                "Källmaterial: {{ step_a.output.text }}"
            ),
        )
        for order, letter in enumerate("cdefghijk", start=3)
    )
    final_question = "\n\n".join(
        [
            "{{ step_k.output.structured }}",
            *(
                f"Section {letter}: {{{{ step_{letter}.output.structured.field }}}}"
                for letter in "bcdefghijk"
            ),
            "Transkribera ljud: {{ step_a.output.text }}",
        ]
    )
    steps = (
        _metric_step(
            ref="step_a",
            order=1,
            input_source="flow_input",
            input_type="audio",
            output_type="text",
        ),
        _metric_step(ref="step_b", order=2, output_type="json"),
        *section_steps,
        _metric_step(ref="step_l", order=12, question=final_question),
        _metric_step(ref="step_m", order=13, output_type="docx"),
    )

    aggregate = compute_material_metrics(steps)
    per_step = dict(compute_per_step_material_metrics(steps))

    assert aggregate.all_previous_steps_count == 0
    assert aggregate.fan_in_width == 11
    assert aggregate.source_duplication_count == 10
    assert aggregate.whole_output_reference_count == 20
    assert max(metrics.source_duplication_count for metrics in per_step.values()) == 1
    assert per_step[12].structured_field_count == 10


def test_canonical_legitimate_broad_fan_in_is_limited_to_comparison_step() -> None:
    steps = (
        _metric_step(
            ref="step_a",
            order=1,
            input_source="flow_input",
            input_type="document",
            output_type="json",
        ),
        _metric_step(ref="step_b", order=2, output_type="text"),
        _metric_step(
            ref="step_c",
            order=3,
            input_source="all_previous_steps",
            output_type="text",
        ),
        _metric_step(
            ref="step_d",
            order=4,
            output_type="text",
            question="{{ step_c.output.text }}\n{{ step_a.output.structured.fact }}",
        ),
    )

    aggregate = compute_material_metrics(steps)
    per_step = dict(compute_per_step_material_metrics(steps))

    assert aggregate.all_previous_steps_count == 1
    assert per_step[3].all_previous_steps_count == 1
    assert per_step[4].all_previous_steps_count == 0
    assert per_step[4].fan_in_width == 2
    assert per_step[4].source_duplication_count == 0


def test_canonical_quality_chain_routes_only_needed_material() -> None:
    steps = (
        _metric_step(
            ref="step_a",
            order=1,
            input_source="flow_input",
            input_type="audio",
            output_type="text",
        ),
        _metric_step(
            ref="step_b",
            order=2,
            output_type="json",
            question="{{ step_a.output.text }}\n\nrapportton: {{ rapportton }}",
        ),
        _metric_step(
            ref="step_c",
            order=3,
            output_type="text",
            question=(
                "{{ step_b.output.structured }}\n\n"
                "Källmaterial: {{ step_a.output.text }}\n\n"
                "ticket_id: {{ ticket_id }}\n"
                "kundnamn: {{ kundnamn }}\n"
                "rapportton: {{ rapportton }}"
            ),
        ),
        _metric_step(
            ref="step_d",
            order=4,
            output_type="json",
            question="{{ step_c.output.text }}\n\nrapportton: {{ rapportton }}",
        ),
        _metric_step(
            ref="step_e",
            order=5,
            output_type="text",
            question=(
                "{{ step_d.output.structured }}\n\n"
                "{{ step_b.output.structured.agenda_point_1_json }}\n"
                "{{ step_b.output.structured.agenda_point_2_json }}\n"
                "{{ step_b.output.structured.agenda_point_3_json }}\n"
                "{{ step_b.output.structured.agenda_point_4_json }}\n"
                "{{ step_d.output.structured.tackning }}\n"
                "{{ step_d.output.structured.ton }}\n"
                "{{ step_d.output.structured.saknade_beslut }}\n\n"
                "Transkribera ljud: {{ step_a.output.text }}\n\n"
                "Skriv Word-utkast för rapport: {{ step_c.output.text }}\n\n"
                "rapportton: {{ rapportton }}"
            ),
        ),
        _metric_step(ref="step_f", order=6, output_type="docx"),
    )

    aggregate = compute_material_metrics(steps, form_field_names={"rapportton"})
    per_step = dict(
        compute_per_step_material_metrics(steps, form_field_names={"rapportton"})
    )

    assert aggregate.all_previous_steps_count == 0
    assert aggregate.fan_in_width == 4
    assert aggregate.source_duplication_count == 3
    assert aggregate.whole_output_reference_count == 7
    assert aggregate.structured_field_count == 7
    assert per_step[5].fan_in_width == 4
    assert per_step[5].source_duplication_count == 1
