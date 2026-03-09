import importlib
import sys


def test_server_main_imports_without_circular_flow_template_validation_cycle() -> None:
    module = importlib.import_module("intric.server.main")

    assert module is not None


def test_flow_template_validation_shim_reexports_files_domain_helpers() -> None:
    files_validation = importlib.import_module("intric.files.docx_template_validation")
    flow_validation = importlib.import_module("intric.flows.flow_template_validation")

    assert (
        flow_validation.validate_docx_template_archive
        is files_validation.validate_docx_template_archive
    )
    assert flow_validation.validate_template_extension is files_validation.validate_template_extension
    assert (
        flow_validation.normalize_template_extraction_error
        is files_validation.normalize_template_extraction_error
    )


def test_intric_flows_package_does_not_import_services_as_side_effect() -> None:
    sys.modules.pop("intric.flows", None)
    sys.modules.pop("intric.flows.flow_service", None)
    sys.modules.pop("intric.flows.flow_run_service", None)

    importlib.import_module("intric.flows")

    assert "intric.flows.flow_service" not in sys.modules
    assert "intric.flows.flow_run_service" not in sys.modules


def test_intric_flows_runtime_package_does_not_import_celery_as_side_effect() -> None:
    sys.modules.pop("intric.flows.runtime", None)
    sys.modules.pop("intric.flows.runtime.celery_app", None)
    sys.modules.pop("intric.flows.runtime.celery_execution_backend", None)

    importlib.import_module("intric.flows.runtime")

    assert "intric.flows.runtime.celery_app" not in sys.modules
    assert "intric.flows.runtime.celery_execution_backend" not in sys.modules
