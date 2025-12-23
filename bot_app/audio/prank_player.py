import os
import time
import asyncio
import random
import discord

from bot_app.core.config import FFMPEG_EXE, PRANK_RANDOM_OFFSET_MIN_SEC, PRANK_RANDOM_OFFSET_MAX_SEC


class PrankPlayer:
    """
    Plays exactly one random clip each minute at a random second inside that minute.
    """
    def __init__(self, logger, sampler):
        self.logger = logger
        self.sampler = sampler

        self.enabled = False
        self._task: asyncio.Task | None = None

    def start(self):
        if self.enabled:
            return
        self.enabled = True
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        self.enabled = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self):
        while self.enabled:
            # schedule next play at random second in the next minute
            now = time.time()
            next_minute = (int(now // 60) + 1) * 60
            offset = random.randint(PRANK_RANDOM_OFFSET_MIN_SEC, PRANK_RANDOM_OFFSET_MAX_SEC)
            target = next_minute + offset
            await asyncio.sleep(max(0.0, target - time.time()))

            if not self.enabled:
                break

            vc = self.logger.vc
            if not vc or not vc.is_connected():
                continue

            if vc.is_playing():
                continue

            picked = self.sampler.bank.pick_random()
            if not picked:
                continue

            user_id, path = picked
            if not path or not os.path.exists(path):
                continue

            # prevent sampling while playing (avoid echo/feedback collection)
            self.logger.is_prank_playing = True
            try:
                # Discord voice play via FFmpegPCMAudio is the simplest for wav. [web:271]
                source = discord.FFmpegPCMAudio(executable=FFMPEG_EXE if os.path.exists(FFMPEG_EXE) else "ffmpeg", source=path)
                vc.play(source)
                self.logger.log_event(time.time(), "🎭", f"Prank clip played from user={user_id}")
                while vc.is_connected() and vc.is_playing():
                    await asyncio.sleep(0.2)
            except Exception:
                pass
            finally:
                self.logger.is_prank_playing = False
