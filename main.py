from config.settings import Config
from agent.basic_agent import BasicAgent
import argparse
import os

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Basic Agent CLI")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode (non-streaming output)")
    parser.add_argument("--allow-unsafe-bash", action="store_true", help="Allow potentially dangerous shell commands")
    args = parser.parse_args()

    Config.validate()
    if args.allow_unsafe_bash:
        os.environ["AGENT_ALLOW_UNSAFE_BASH"] = "1"
    agent = BasicAgent(debug=args.debug)
    agent.chat()
