"""S1 replaces mandatory requirements with freely revisable task requests."""
import pytest

from exposure_workbench.agents import delegation as dl
from exposure_workbench.utils.ids import new_id

TASK = {"analyst": "risk", "subjects": ["port_001"], "lines": ["how big MSFT is"]}

def test_first_and_later_asks_need_only_tasks():
    first, = dl.parse_tasks({"tasks": [TASK]}, new_id)
    later, = dl.parse_tasks({"tasks": [{**TASK, "lines": ["compare it with the previous run"],
                                       "follow_up_of": first.task_id}]}, new_id)
    assert first.requirement_ids == later.requirement_ids == ()
    assert later.follow_up_of == first.task_id and "for" not in later.as_dict()
    schema = dl.ASK_TOOL["function"]["parameters"]
    assert set(schema["properties"]) == {"tasks"}
    assert "for" not in schema["properties"]["tasks"]["items"]["properties"]


@pytest.mark.parametrize("args", [
    {"tasks": [TASK], "requirements": []},
    {"tasks": [{**TASK, "for": ["R1"]}]},
    {"tasks": [{**TASK, "invented_control": True}]},
])
def test_one_current_protocol_no_silently_ignored_control_fields(args):
    with pytest.raises(dl.BadDelegation, match="no field"):
        dl.parse_tasks(args, new_id)

def test_original_natural_language_survives_dispatch():
    task, = dl.parse_tasks({"tasks": [TASK]}, new_id)
    assert task.lines == tuple(TASK["lines"])
