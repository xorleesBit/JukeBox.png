import sys
import argparse

try:
    import audioop
except ImportError:
    import audioop_lts as audioop
    sys.modules["audioop"] = audioop

from bot_app.bot_entry import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Loger Bot")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode using DISCORD_BOT_TOKEN_DEBUG")
    args = parser.parse_args()
    
    run(debug_mode=args.debug)