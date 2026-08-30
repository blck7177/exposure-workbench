"""Every name a workflow method reads must be one something gives it.

V13-S5 added the three columns a limit check ran on, wrote the code that
persists them, and never passed the list through: `_persist_outputs` referenced
`limit_checks`, which was a local of `run()` eight hundred lines away. Python
resolves an unbound name as a global, so this compiled, imported, passed 1,333
offline tests, shipped, and failed on the only thing that exercises it — a real
exposure run, at the last step, after every calculation had already been done.
Every run since has failed the same way, which is why limit_checks holds 27 rows
from one August run and nothing after it.

The class is "a method reads a name nothing gives it", and it is checkable
without a database: a name a function treats as a global must resolve in the
module's namespace or in builtins. Nothing else about the workflow needs to be
true for this to be worth running, and it covers every method in the module
rather than the one that failed.
"""

from __future__ import annotations

import builtins
import inspect

import pytest

from exposure_workbench.workflow import exposure_workflow as ew
from exposure_workbench.workflow import issuer_research_workflow as irw
from exposure_workbench.workflow import readiness_workflow as rw

MODULES = [ew, irw, rw]


def _functions(module):
    """Every function defined in the module, including methods and nested ones."""
    seen = []
    for _name, obj in vars(module).items():
        if inspect.isfunction(obj) and obj.__module__ == module.__name__:
            seen.append(obj)
        elif inspect.isclass(obj) and obj.__module__ == module.__name__:
            for _mname, meth in vars(obj).items():
                if inspect.isfunction(meth):
                    seen.append(meth)
    return seen


def _unresolvable(fn, module) -> list[str]:
    code = fn.__code__
    # co_names holds globals AND attribute names; an attribute that happens to
    # match nothing is not an error, so only names that are not attribute
    # accesses matter. Distinguishing them needs the bytecode, and LOAD_GLOBAL
    # is the one that raises NameError.
    wanted = {
        instr.argval
        for instr in __import__("dis").get_instructions(code)
        if instr.opname == "LOAD_GLOBAL" and isinstance(instr.argval, str)
    }
    ns = vars(module)
    return sorted(n for n in wanted
                  if n not in ns and not hasattr(builtins, n))


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_no_workflow_function_reads_a_name_nothing_defines(module):
    offenders = {}
    for fn in _functions(module):
        missing = _unresolvable(fn, module)
        if missing:
            offenders[fn.__qualname__] = missing
    assert not offenders, (
        "these functions read names that resolve to nothing at module scope — "
        f"each is a NameError the moment that line runs: {offenders}"
    )


def test_the_persist_step_is_handed_the_checks_it_records():
    """The specific instance, named so a future reader knows which bug this is.

    Not a duplicate of the test above: that one holds the class, this one holds
    that the fix was to PASS the list rather than to stop recording it. Deleting
    the parameter and the four columns it feeds would satisfy the class test and
    lose V13-S5's whole point — a check that ran and stayed clear being as
    citable as one that fired.
    """
    params = inspect.signature(ew.ExposureWorkflow._persist_outputs).parameters
    assert "limit_checks" in params
    src = inspect.getsource(ew.ExposureWorkflow._persist_outputs)
    assert "current_value=" in src and "warning_level=" in src and "breach_level=" in src
