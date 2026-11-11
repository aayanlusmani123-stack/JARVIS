import unittest
from dataclasses import FrozenInstanceError

from integrations.minecraft import MinecraftContext, MinecraftContextProvider


class MinecraftContextTests(unittest.TestCase):
    def test_snapshot_defaults_to_unknown_and_empty_inventory(self):
        context = MinecraftContext()
        self.assertIsNone(context.x)
        self.assertIsNone(context.biome)
        self.assertEqual(context.inventory, ())
        self.assertEqual(context.equipped_items, ())

    def test_snapshot_carries_typed_game_state(self):
        context = MinecraftContext(
            player_name="Alex",
            x=1.5,
            y=64.0,
            z=-12.25,
            health=18.0,
            hunger=16,
            dimension="minecraft:overworld",
            biome="minecraft:plains",
            inventory=("minecraft:bread x3",),
            equipped_items=("minecraft:iron_chestplate",),
        )
        self.assertEqual(context.player_name, "Alex")
        self.assertEqual(context.inventory, ("minecraft:bread x3",))
        with self.assertRaises(FrozenInstanceError):
            context.x = 2.0

    def test_provider_is_a_protocol(self):
        self.assertTrue(hasattr(MinecraftContextProvider, "get_context"))


if __name__ == "__main__":
    unittest.main()
