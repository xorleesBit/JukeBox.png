import os

class DevManager:
    def __init__(self):
        # Set of user IDs currently in "User Mode" (Developer pretending to be normal user)
        # If a dev ID is NOT in this set, they are in Admin/God mode.
        # Wait, requirements say: "Toggle... without debug mode - admin. with debug mode - normal user?"
        # Let's clarify:
        # "Пусть при включении режима отладки я для бота буду обычным пользователем" -> Debug Mode ON = User simulation.
        # "без включения режима отладки - администратором" -> Debug Mode OFF = Admin/God mode.
        
        # So: simulation_active_ids stores devs who turned ON the debug toggle (simulating user).
        self.simulation_active_ids = set()
        
        # Hardcoded Owner ID (Replace with actual ID or load from env)
        # You can find your ID in Discord. For now I'll use a placeholder or load from env.
        self.OWNER_IDS = set()
        try:
            oid = os.getenv("OWNER_ID")
            if oid:
                self.OWNER_IDS.add(int(oid))
        except: pass

    def is_dev(self, user_id: int) -> bool:
        return user_id in self.OWNER_IDS

    def is_god_mode(self, user_id: int) -> bool:
        """
        Returns True if user is a Dev AND they are NOT simulating a normal user.
        In this mode, they have infinite money, perms, etc.
        """
        if not self.is_dev(user_id):
            return False
        return user_id not in self.simulation_active_ids

    def toggle_simulation(self, user_id: int) -> bool:
        """
        Toggles state. Returns True if now simulating User, False if God Mode.
        """
        if user_id in self.simulation_active_ids:
            self.simulation_active_ids.remove(user_id)
            return False
        else:
            self.simulation_active_ids.add(user_id)
            return True

dev_manager = DevManager()
