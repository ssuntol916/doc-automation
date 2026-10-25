"""Task-local binder controls; observations here are synthetic contract fixtures."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/quality_records.py"
SPEC = importlib.util.spec_from_file_location("quality_repair_binder", PATH)
binder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(binder)


def fixture():
    files = {n: {"path": f"/synthetic-contract-fixture/{n}", "sha256": str(i) * 64}
             for i, n in enumerate(("native_before", "native_saved", "native_after", "pdf"), 1)}
    report_ref = {"path": "/synthetic-contract-fixture/report.json", "sha256": "5" * 64}
    report = {"recorded_at": "2026-10-24T08:00:03Z"}
    targets = ("native_before", "native_saved", "native_saved", "native_after", "native_after", "native_after", "native_after", "pdf")
    events = [{"action": action, "status": "passed", "observed_at": f"2026-10-24T08:00:0{i}Z",
               "artifact": deepcopy(files[target]), "observation": "Synthetic contract control; no UI was performed."}
              for i, (action, target) in enumerate(zip(binder.REPAIR_ACTIONS, targets))]
    events[3]["report"] = deepcopy(report_ref)
    native = {"workflow": binder.REPAIR_WORKFLOW, "native_saved": deepcopy(files["native_saved"]),
              "package_postprocess": deepcopy(report_ref), "events": events}
    return native, files, report, report_ref


def same_ref(actual, wanted, base, label):
    if actual != wanted:
        raise ValueError(f"{label}: different binding")


def validate(native, files, report, report_ref, workflow=None):
    return binder.validate_native_events(native, workflow or binder.REPAIR_WORKFLOW, files, same_ref, Path("/"),
                                         repair=report, repair_ref=report_ref)


def test_exact_eight_actions_distinguish_intermediate_and_final_bytes():
    native, files, report, report_ref = fixture()
    states, times = validate(native, files, report, report_ref)
    assert states == ["passed"] * 8
    assert times == sorted(times)


@pytest.mark.parametrize("mutation", ["missing_close", "wrong_order", "wrong_final", "wrong_export", "stale_report", "wrong_saved"])
def test_incomplete_or_misbound_action_chain_is_rejected(mutation):
    native, files, report, report_ref = fixture()
    if mutation == "missing_close":
        native["events"].pop(2)
    elif mutation == "wrong_order":
        native["events"][4], native["events"][5] = native["events"][5], native["events"][4]
    elif mutation == "wrong_final":
        native["events"][4]["artifact"] = files["native_saved"]
    elif mutation == "wrong_export":
        native["events"][-1]["artifact"] = files["native_after"]
    elif mutation == "stale_report":
        native["events"][3]["report"]["sha256"] = "0" * 64
    else:
        native["native_saved"] = files["native_before"]
    with pytest.raises(ValueError):
        validate(native, files, report, report_ref)


@pytest.mark.parametrize("when", ["2026-10-24T08:00:01Z", "2026-10-24T08:00:04Z"])
def test_postprocess_time_cannot_precede_close_or_follow_its_observation(when):
    native, files, report, report_ref = fixture()
    report["recorded_at"] = when
    with pytest.raises(ValueError, match="repair must occur"):
        validate(native, files, report, report_ref)


def test_postprocess_cannot_be_claimed_without_verified_report():
    native, files, report, report_ref = fixture()
    with pytest.raises(ValueError, match="requires exact"):
        validate(native, files, None, None)


def test_pending_ui_is_preserved_and_does_not_become_a_pass():
    native, files, report, report_ref = fixture()
    native["events"][4]["status"] = "pending"
    states, _ = validate(native, files, report, report_ref)
    assert "pending" in states and not all(s == "passed" for s in states)


def test_workflow_requires_explicit_matching_selection():
    native, files, report, report_ref = fixture()
    native.pop("workflow")
    with pytest.raises(ValueError, match="workflow differs"):
        validate(native, files, report, report_ref)


def test_final_bytes_cannot_be_the_unchanged_native_save_as():
    native, files, report, report_ref = fixture()
    files["native_after"]["sha256"] = files["native_saved"]["sha256"]
    with pytest.raises(ValueError, match="distinguish"):
        validate(native, files, report, report_ref)


def test_default_five_action_contract_remains_unchanged():
    native = {"events": [{"action": a, "status": "passed", "observed_at": f"2026-10-24T08:00:0{i}Z",
                          "observation": "Synthetic ordinary contract control."}
                         for i, a in enumerate(binder.ACTIONS)]}
    states, _ = binder.validate_native_events(native, binder.STANDARD_WORKFLOW, {}, same_ref, Path("/"))
    assert states == ["passed"] * 5
    native["package_postprocess"] = {"path": "hidden-repair.json", "sha256": "0" * 64}
    with pytest.raises(ValueError, match="explicit repair workflow"):
        binder.validate_native_events(native, binder.STANDARD_WORKFLOW, {}, same_ref, Path("/"))
