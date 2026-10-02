import json
import unittest

from workflow_model import response


def tool(name, **parameters):
    return {"type": "function", "function": {"name": name, "parameters": parameters}}


class WorkflowModelTest(unittest.TestCase):
    def test_ordinary_requests_keep_existing_mock_behavior(self):
        self.assertIsNone(
            response({"messages": [{"role": "user", "content": "hello"}]})
        )

    def test_only_offered_tools_are_called(self):
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": 'E2E_WORKFLOW_REPORT {"filename":"book.xlsx","file_ref":"eneo-file:0123456789abcdef0123456789abcdef"}',
                }
            ]
        }
        self.assertEqual(
            response(payload)["content"], "E2E workflow unavailable: inspect_table"
        )
        payload["tools"] = [tool("approved__inspect_table")]
        call = response(payload)["tool_calls"][0]["function"]
        self.assertEqual(call["name"], "approved__inspect_table")
        self.assertEqual(
            json.loads(call["arguments"])["files"][0]["filename"], "book.xlsx"
        )

    def test_skill_activation_uses_the_offered_key(self):
        payload = {
            "messages": [{"role": "user", "content": "E2E_WORKFLOW_REPORT"}],
            "tools": [
                tool(
                    "eneo_activate_skill",
                    properties={"skill_key": {"enum": ["skill-2"]}},
                )
            ],
        }
        call = response(payload)["tool_calls"][0]["function"]
        self.assertEqual(json.loads(call["arguments"]), {"skill_key": "skill-2"})


if __name__ == "__main__":
    unittest.main()
