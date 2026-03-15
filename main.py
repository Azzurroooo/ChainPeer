from config.settings import Config
from agent.basic_agent import BasicAgent
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Basic Agent CLI")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode (non-streaming output)")
    args = parser.parse_args()

    Config.validate()
    agent = BasicAgent(debug=args.debug)
    agent.chat()
