"""基础 Agent 实现 - 纯 OpenAI 版本"""
import json
from openai import OpenAI
from config.settings import Config
from tools import TOOLS, TOOL_SCHEMAS
from agent.prompts import SYSTEM_PROMPT
from utils import print_rainbow_logo

class BasicAgent:
    def __init__(self, tools=None, debug: bool = False):
        self.client = Config.get_client()
        self.model = Config.DEFAULT_MODEL
        self.tool_schemas = tools or TOOL_SCHEMAS
        self.chat_history = []
        self.debug = debug

    def _execute_tool(self, name: str, args: dict) -> str:
        return TOOLS[name](**args)

    def run(self, query: str) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": query}]
        while True:
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=self.tool_schemas, tool_choice="auto"
            )
            msg = resp.choices[0].message
            messages.append(msg)

            if msg.content and not msg.tool_calls:
                return msg.content

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    result = self._execute_tool(tc.function.name, json.loads(tc.function.arguments))
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    def chat(self):
        print_rainbow_logo()
        if self.debug:
            print(f"Chain Peer v0.1(Debug Mode: {self.debug}) 输入 'quit' 退出")
        else:
            print(f"Chain Peer v0.1")
            print("Welcome back!")
        print("-" * 50)
        self.chat_history = [{"role": "system", "content": SYSTEM_PROMPT}]

        while True:
            user_input = input("\n> ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("再见！👋")
                break
            if not user_input:
                continue

            print("\nAgent: ", end="", flush=True)
            self.chat_history.append({"role": "user", "content": user_input})

            try:
                while True:
                    if self.debug:
                        # 非流式模式 (Debug Mode)
                        resp = self.client.chat.completions.create(
                            model=self.model, messages=self.chat_history,
                            tools=self.tool_schemas, tool_choice="auto", stream=False
                        )
                        msg = resp.choices[0].message
                        print(msg)
                        if msg.content:
                            # print(msg.content)
                            self.chat_history.append({"role": "assistant", "content": msg.content})
                        
                        if msg.tool_calls:
                            self.chat_history.append(msg)
                            for tc in msg.tool_calls:
                                print(f"\n[Debug] Tool Call: {tc.function.name}({tc.function.arguments})")
                                result = self._execute_tool(tc.function.name, json.loads(tc.function.arguments))
                                print(f"[Debug] Tool executed. Tool Result: {result}")
                                self.chat_history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                                if not msg.content: # 如果没有content只有tool call，需要打印换行
                                    print()
                        else:
                            break
                    else:
                        # 流式模式 (Default)
                        resp = self.client.chat.completions.create(
                            model=self.model, messages=self.chat_history,
                            tools=self.tool_schemas, tool_choice="auto", stream=True
                        )

                        tool_calls, content_parts = [], []

                        for chunk in resp:
                            delta = chunk.choices[0].delta
                            if delta.content:
                                print(delta.content, end="", flush=True)
                                content_parts.append(delta.content)
                            if delta.tool_calls:
                                for tc in delta.tool_calls:
                                    idx = tc.index
                                    while len(tool_calls) <= idx:
                                        tool_calls.append({"id": "", "name": "", "arguments": ""})
                                    if tc.id: tool_calls[idx]["id"] = tc.id
                                    if tc.function:
                                        if tc.function.name: tool_calls[idx]["name"] = tc.function.name
                                        if tc.function.arguments: tool_calls[idx]["arguments"] += tc.function.arguments

                        if content_parts:
                            self.chat_history.append({"role": "assistant", "content": "".join(content_parts)})

                        if tool_calls:
                            msg = {"role": "assistant", "tool_calls": [
                                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                for tc in tool_calls
                            ]}
                            self.chat_history.append(msg)

                            for tc in tool_calls:
                                result = self._execute_tool(tc["name"], json.loads(tc["arguments"]))
                                self.chat_history.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                        else:
                            break

                print()

            except Exception as e:
                print(f"\nError: {e}")
