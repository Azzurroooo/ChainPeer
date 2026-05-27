from agent.basic_agent import BasicAgent
from agent.infrastructure.config import Config
from agent.version import __version__
import argparse
import os

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Basic Agent CLI")
    parser.add_argument("--version", action="version", version=f"chainpeer {__version__}")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode (non-streaming output)")
    parser.add_argument("--allow-unsafe-bash", action="store_true", help="Allow potentially dangerous shell commands")
    parser.add_argument("--session", type=str, default=None, help="Session ID to load")
    parser.add_argument("-c", "--resume-latest", action="store_true", help="Resume the latest session if available")
    parser.add_argument("--session-dir", type=str, default=None, help="Session storage directory")
    args = parser.parse_args()

    Config.validate()
    if args.allow_unsafe_bash:
        os.environ["AGENT_ALLOW_UNSAFE_BASH"] = "1"
    agent = BasicAgent(
        debug=args.debug,
        session_dir=args.session_dir,
        session_id=args.session,
        resume_latest=args.resume_latest,
    )
    agent.chat()
