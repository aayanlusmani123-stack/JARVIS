package com.jarvis.minecraft;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import net.minecraft.client.Minecraft;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.item.ItemStack;

final class MinecraftState {
    private static final Gson GSON = new GsonBuilder().serializeNulls().create();

    final String player_username;
    final double x;
    final double y;
    final double z;
    final float health;
    final int hunger;
    final int armor_points;
    final Item held_item;
    final List<Item> inventory;
    final String biome;
    final String dimension;
    final String game_mode;
    final int xp_level;
    final int time_of_day;
    final boolean alive;

    MinecraftState(String playerUsername, double x, double y, double z, float health, int hunger,
            int armorPoints, Item heldItem, List<Item> inventory, String biome, String dimension,
            String gameMode, int xpLevel, int timeOfDay, boolean alive) {
        this.player_username = playerUsername;
        this.x = x;
        this.y = y;
        this.z = z;
        this.health = health;
        this.hunger = hunger;
        this.armor_points = armorPoints;
        this.held_item = heldItem;
        this.inventory = List.copyOf(inventory);
        this.biome = biome;
        this.dimension = dimension;
        this.game_mode = gameMode;
        this.xp_level = xpLevel;
        this.time_of_day = timeOfDay;
        this.alive = alive;
    }

    static Optional<MinecraftState> capture(Minecraft client) {
        if (client.player == null || client.level == null || client.getConnection() == null || client.gameMode == null) {
            return Optional.empty();
        }

        var player = client.player;
        var level = client.level;
        var biomeKey = level.getBiome(player.blockPosition()).unwrapKey();
        if (biomeKey.isEmpty()) return Optional.empty();

        var playerInventory = player.getInventory();
        List<Item> items = new ArrayList<>();
        for (int slot = 0; slot < playerInventory.getContainerSize(); slot++) {
            ItemStack stack = playerInventory.getItem(slot);
            if (!stack.isEmpty()) items.add(itemFrom(stack, slot));
        }

        ItemStack heldStack = player.getMainHandItem();
        Item heldItem = heldStack.isEmpty() ? null : itemFrom(heldStack, null);
        String gameMode = client.gameMode.getPlayerMode().name().toLowerCase(Locale.ROOT);

        return Optional.of(new MinecraftState(
                player.getGameProfile().name(),
                player.getX(), player.getY(), player.getZ(),
                player.getHealth(), player.getFoodData().getFoodLevel(), player.getArmorValue(),
                heldItem, items,
                biomeKey.orElseThrow().identifier().toString(), level.dimension().identifier().toString(),
                gameMode, player.experienceLevel,
                (int) Math.floorMod(level.getOverworldClockTime(), 24_000L), player.isAlive()));
    }

    private static Item itemFrom(ItemStack stack, Integer slot) {
        return new Item(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString(), stack.getCount(), slot);
    }

    String toJson() {
        return GSON.toJson(this);
    }

    static final class Item {
        final String item_id;
        final int count;
        final Integer slot;

        Item(String itemId, int count, Integer slot) {
            this.item_id = itemId;
            this.count = count;
            this.slot = slot;
        }
    }
}
