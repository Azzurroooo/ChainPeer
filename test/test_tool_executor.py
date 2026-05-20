from agent.application.tool_executor import ToolExecutor


class FakeRegistry:
    @property
    def schemas(self):
        return []

    def has(self, name: str) -> bool:
        return name in {"sync_tool", "async_tool"}

    def is_async(self, name: str) -> bool:
        return name == "async_tool"

    def call(self, name: str, args: dict):
        return f"sync:{args.get('value')}"

    async def call_async(self, name: str, args: dict):
        return f"async:{args.get('value')}"


def test_tool_executor_exposes_async_tool_check() -> None:
    executor = ToolExecutor(registry=FakeRegistry())

    if executor.is_async_tool("async_tool") is not True:
        raise AssertionError("Expected async_tool to be async")
    if executor.is_async_tool("sync_tool") is not False:
        raise AssertionError("Expected sync_tool to be sync")


def main() -> int:
    test_tool_executor_exposes_async_tool_check()
    print("ToolExecutor tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
