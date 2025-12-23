import sys
try:
    import audioop
except ImportError:
    import audioop_lts as audioop
    sys.modules["audioop"] = audioop

from bot_app.bot_entry import run

if __name__ == "__main__":
    run()