from io import BytesIO

from starlette.datastructures import UploadFile

from eneo.flows.definition import FlowDefinition, FormField, LlmProcessing, LlmStep
from eneo.flows.flow_models import FlowRunStatus
from eneo.server.dependencies.container import load_container_upload_admission


async def test_long_text_is_processed_and_summarized_without_losing_sections(
    db_container, published, provider
):
    async with db_container() as container:
        definition = FlowDefinition(
            form_fields=[FormField(key="topic", label="Material", type="text")],
            steps=[
                LlmStep(
                    key="read",
                    name="Read",
                    prompt="Read this section",
                    input="{{form.topic}}",
                    model_id=published["flow"].definition.steps[0].model_id,
                    processing=LlmProcessing(
                        mode="summarize",
                        section_tokens=256,
                        summary_prompt="Produce final summary",
                    ),
                )
            ],
        )
        await container.flow_service().update_flow(
            published["flow"].id, definition=definition
        )
        await container.flow_service().publish_flow(published["flow"].id)
        provider.answer = (
            lambda prompt, text: "final summary"
            if "Synthesis instructions:" in prompt
            else "short section summary"
        )
        original = " ".join(f"word{i}" for i in range(5000))
        runs = container.flow_run_service()
        run = await runs.create_run(
            published["flow"].id, values={"topic": original}, files={}
        )
        await runs.execute_run(run.id)
        result = await runs.get_run(run.id)
        assert result.status == FlowRunStatus.COMPLETED
        output = result.steps[0].output_payload_json
        coverage = output["coverage"][0]
        assert coverage["coverage"] == "complete"
        assert coverage["items"]["D1"]["planned"] > 1
        assert (
            coverage["items"]["D1"]["planned"] == coverage["items"]["D1"]["processed"]
        )
        assert any("word4999" in call["text_input"] for call in provider.calls)
        assert output["text"] == "final summary"
        assert output["processing_calls"] == len(provider.calls)


async def test_each_file_is_read_separately_and_references_remain_distinct(
    db_container, published, provider
):
    async with db_container() as container:
        await load_container_upload_admission(container)
        files = [
            await container.file_service().save_file(
                UploadFile(
                    filename=f"source-{index}.txt",
                    file=BytesIO(text.encode()),
                    headers={"content-type": "text/plain"},
                )
            )
            for index, text in enumerate(
                ["FIRST PRIVATE SOURCE", "SECOND PRIVATE SOURCE"]
            )
        ]
        file_ids = [file.id for file in files]
    async with db_container() as container:
        definition = FlowDefinition(
            form_fields=[FormField(key="docs", label="Sources", type="file")],
            steps=[
                LlmStep(
                    key="read",
                    name="Read",
                    prompt="Read",
                    input="",
                    files_from=["docs"],
                    model_id=published["flow"].definition.steps[0].model_id,
                    processing=LlmProcessing(mode="per_source"),
                )
            ],
        )
        await container.flow_service().update_flow(
            published["flow"].id, definition=definition
        )
        await container.flow_service().publish_flow(published["flow"].id)
        runs = container.flow_run_service()
        run = await runs.create_run(
            published["flow"].id, values={}, files={"docs": file_ids}
        )
        await runs.execute_run(run.id)
        result = await runs.get_run(run.id)
        assert result.status == FlowRunStatus.COMPLETED
        assert len(provider.calls) == 2
        assert "SECOND PRIVATE" not in provider.calls[0]["text_input"]
        assert "FIRST PRIVATE" not in provider.calls[1]["text_input"]
        assert [
            source["file_id"]
            for source in result.steps[0].output_payload_json["sources"]
        ] == [str(file_id) for file_id in file_ids]
