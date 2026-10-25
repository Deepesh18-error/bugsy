// A fixed Python harness keeps source text and public cases in data globals.
// Each case starts with a fresh namespace. Interpreter-wide effects are still
// possible, which is another reason these checks are only provisional.
export const FEEDBACK_HARNESS = `
import json

_outcomes = []
for _case in json.loads(_feedback_tests_json):
    _namespace = {"__name__": "__main__"}
    try:
        exec(compile(_feedback_source, "challenge.py", "exec"), _namespace)
        exec(compile(_case["test_code"], "public_test.py", "exec"), _namespace)
    except BaseException:
        _outcomes.append({"test_id": _case["test_id"], "passed": False,
                          "message": _case["failure_message"]})
    else:
        _outcomes.append({"test_id": _case["test_id"], "passed": True,
                          "message": None})
json.dumps(_outcomes)
`;
