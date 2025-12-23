import time
import discord

def activity_summary(member: discord.Member) -> str:
    # Берём "самое заметное" из activities; если ничего — пусто
    acts = list(getattr(member, "activities", []) or [])
    if not acts and getattr(member, "activity", None):
        acts = [member.activity]

    # отбрасываем custom, если есть другое
    non_custom = [a for a in acts if getattr(a, "type", None) != discord.ActivityType.custom]
    a = (non_custom[-1] if non_custom else (acts[-1] if acts else None))
    if not a:
        return ""

    name = getattr(a, "name", "") or ""
    if not name:
        return ""

    t = getattr(a, "type", None)
    if t == discord.ActivityType.playing:
        return f"Playing {name}"
    if t == discord.ActivityType.streaming:
        return f"Streaming {name}"
    if t == discord.ActivityType.listening:
        return f"Listening {name}"
    if t == discord.ActivityType.watching:
        return f"Watching {name}"
    return name

class PresencePoller:
    """
    Каждые N секунд сравнивает снапшоты member.status и activity.
    Требует включённых privileged intents (members + presences) в Dev Portal.
    """
    def __init__(self, guild: discord.Guild):
        self.guild = guild
        self.prev = {}  # user_id -> (status_str, activity_str)

    def snapshot(self):
        snap = {}
        for m in self.guild.members:
            if m.bot:
                continue
            st = str(getattr(m, "status", "unknown"))
            act = activity_summary(m)
            snap[m.id] = (st, act)
        return snap

    def diff(self, new_snap):
        events = []
        for uid, (st, act) in new_snap.items():
            old = self.prev.get(uid)
            if old is None:
                # first time; don't spam
                continue
            old_st, old_act = old
            if st != old_st:
                events.append((uid, f"Status: {old_st} -> {st}"))
            if act != old_act:
                if act:
                    events.append((uid, f"Activity: {old_act or '(none)'} -> {act}"))
                else:
                    events.append((uid, f"Activity cleared: {old_act} -> (none)"))
        self.prev = new_snap
        return events

    def prime(self):
        self.prev = self.snapshot()
