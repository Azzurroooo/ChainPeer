import unittest
import json
import dataclasses

from agent.domain.events import (
    RuntimeEvent,
    AssistantDeltaEvent,
    ToolProgressEvent,
    TurnCompletedEvent
)


class TestRuntimeEvents(unittest.TestCase):
    def test_event_initialization(self):
        event = AssistantDeltaEvent(text="Hello")
        self.assertEqual(event.type, "assistant_delta")
        self.assertEqual(event.text, "Hello")
        self.assertTrue(isinstance(event.ts, str))

    def test_event_serialization(self):
        event = ToolProgressEvent(tool_call_id="call_123", tool_name="bash", payload={"stdout": "test"})
        # Should be easily serializable using dataclasses.asdict
        event_dict = dataclasses.asdict(event)
        self.assertEqual(event_dict["type"], "tool_progress")
        self.assertEqual(event_dict["tool_call_id"], "call_123")
        self.assertEqual(event_dict["tool_name"], "bash")
        self.assertEqual(event_dict["payload"], {"stdout": "test"})
        
        # Ensure it can be dumped to JSON
        json_str = json.dumps(event_dict)
        self.assertIn("tool_progress", json_str)
        self.assertIn("call_123", json_str)

    def test_inheritance(self):
        event = TurnCompletedEvent()
        self.assertTrue(isinstance(event, RuntimeEvent))
        self.assertEqual(event.type, "turn_completed")


if __name__ == "__main__":
    unittest.main()
