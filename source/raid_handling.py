import asyncio
import datetime
import dateparser
import discord
from discord.ext import commands
import os
import re

from initialise import add_emojis, get_role_emojis
from raid import Raid
from role_handling import get_role
from player import Player, PlayerClass
from utils import alphabet_emojis


class Tier(commands.Converter):
    async def convert(self, ctx, argument):
        return await self.converter(argument)

    async def converter(self, argument):
        tier = re.search(r'\d+', argument)  # Filter out non-numbers
        if tier is None:
            raise commands.BadArgument("Failed to parse tier argument: " + argument)
        tier = "T{0}".format(tier.group())
        return tier


class Time(commands.Converter):
    def __init__(self, tz):
        self.tz = tz

    async def convert(self, ctx, argument):
        return await self.converter(argument)

    async def converter(self, argument):
        if "server" in argument:
            # Strip off server (time) and return as server time
            argument = argument.partition("server")[0]
            my_settings = {'PREFER_DATES_FROM': 'future', 'TIMEZONE': self.tz, 'RETURN_AS_TIMEZONE_AWARE': True}
        else:
            my_settings = {'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True}
        time = dateparser.parse(argument, settings=my_settings)
        if time is None:
            raise commands.BadArgument("Failed to parse time argument: " + argument)
        time = convert2UTC(time)
        # Check if time is in near future.
        current_time = datetime.datetime.now()
        delta_time = datetime.timedelta(days=7)
        if current_time + delta_time < time:
            error_message = "You are not allowed to post raids more than a week in advance."
            raise commands.BadArgument(error_message)
        return time


async def raid_command(ctx, name, tier, boss, time, role_names, boss_name, server_tz, roster=False):
    name = name.capitalize()
    boss = boss.capitalize()
    raid = Raid(name, tier, boss, time)
    emojis = await get_role_emojis(ctx.guild, role_names)
    if roster:
        raid.set_roster(roster)
        set_default_roster(raid, emojis)
    embed = build_raid_message(raid, "\u200B", server_tz)
    post = await ctx.send(embed=embed)
    raid.set_post_id(post.id)
    raid.set_channel_id(ctx.channel.id)
    raid.set_guild_id(ctx.guild.id)
    emojis.append("\u2705")  # Check mark emoji
    emojis.append("\u274C")  # Cancel emoji
    boss_emoji = discord.utils.get(ctx.guild.emojis, name=boss_name)
    emojis.append(boss_emoji)
    emojis.append("\u23F2")  # Timer emoji
    emojis.append("\u26CF")  # Pick emoji
    await add_emojis(emojis, post)
    await asyncio.sleep(0.25)
    await post.pin()
    return raid


async def raid_update(bot, payload, raid, role_names, boss_name, raid_leader_name, server_tz):
    guild = bot.get_guild(payload.guild_id)
    channel = guild.get_channel(payload.channel_id)
    user = guild.get_member(payload.user_id)
    emoji = payload.emoji
    emojis = await get_role_emojis(guild, role_names)
    boss_emoji = discord.utils.get(guild.emojis, name=boss_name)
    update = False

    def check(msg):
        return msg.author == user

    if emoji == boss_emoji:
        raid_leader = await get_role(guild, raid_leader_name)
        if raid_leader not in user.roles:
            error_msg = "You do not have permission to change the raid boss. This incident will be reported."
            print("Putting {0} on the naughty list.".format(user.name))
            await channel.send(error_msg, delete_after=15)
            return False
        await channel.send("Please specify the new raid boss.", delete_after=15)
        try:
            response = await bot.wait_for('message', check=check, timeout=300)
        except asyncio.TimeoutError:
            return False
        finally:
            await response.delete()
        boss = response.content.capitalize()
        raid.set_boss(boss)
        update = True
    elif str(emoji) == "\u23F2":  # Timer emoji
        raid_leader = await get_role(guild, raid_leader_name)
        if raid_leader not in user.roles:
            error_msg = "You do not have permission to change the raid time. This incident will be reported."
            print("Putting {0} on the naughty list.".format(user.name))
            await channel.send(error_msg, delete_after=15)
            return False
        await channel.send("Please specify the new raid time.", delete_after=15)
        try:
            response = await bot.wait_for('message', check=check, timeout=300)
        except asyncio.TimeoutError:
            return False
        try:
            time = await Time(server_tz).converter(response.content)
        except commands.BadArgument:
            error_msg = "Failed to parse time argument: " + response.content
            await channel.send(error_msg, delete_after=20)
            return False
        finally:
            await response.delete()
        raid.set_time(time)
        update = True
    elif str(emoji) == "\u26CF":  # Pick emoji
        if not raid.roster:
            await channel.send("Roster is not enabled for this raid.", delete_after=10)
            return False
        raid_leader = await get_role(guild, raid_leader_name)
        if raid_leader not in user.roles:
            error_msg = "You do not have permission to change the raid boss. This incident will be reported."
            print("Putting {0} on the naughty list.".format(user.name))
            await channel.send(error_msg, delete_after=15)
            return False
        await select_players(bot, user, channel, raid, emojis)
    elif str(emoji) == "\u274C":  # Cancel emoji
        update = raid.remove_player(user)
    elif str(emoji) == "\u2705":  # Check mark emoji
        has_class_role = False
        for emoji in emojis:
            if emoji.name in [role.name for role in user.roles]:
                update = raid.add_player(user, emoji)
                has_class_role = True
        if not has_class_role:
            error_msg = "{0} you have not assigned yourself any class roles.".format(user.mention)
            await channel.send(error_msg, delete_after=15)
    elif emoji in emojis:
        update = raid.add_player(user, emoji)
    msg = build_raid_players(raid.players)
    embed = build_raid_message(raid, msg, server_tz)
    post = await channel.fetch_message(raid.post_id)
    try:
        await post.edit(embed=embed)
    except discord.HTTPException:
        print("An error occurred sending the following messages as embed.")
        print(embed.title)
        print(embed.description)
        print(embed.fields)
        await channel.send("That's an error. Check the logs.")
    return update


def set_default_roster(raid, emojis):
    main_tank = set()
    off_tank = set()
    heals = set()
    lm = set()
    burg = set()
    dps_capt = set()
    dps = set()
    for emoji in emojis:
        if 'Guardian' == emoji.name:
            main_tank.add(str(emoji))
    for emoji in emojis:
        if 'Captain' == emoji.name:
            off_tank.add(str(emoji))
    for emoji in emojis:
        if emoji.name in ['Beorning', 'Minstrel']:
            heals.add(str(emoji))
    for emoji in emojis:
        if 'Loremaster' == emoji.name:
            lm.add(str(emoji))
    for emoji in emojis:
        if 'Burglar' == emoji.name:
            burg.add(str(emoji))
    for emoji in emojis:
        if 'Captain' == emoji.name:
            dps_capt.add(str(emoji))
    for emoji in emojis:
        if emoji.name in ['Champion', 'Hunter', 'Runekeeper', 'Warden']:
            dps.add(str(emoji))
    raid.set_slot(0, main_tank)
    raid.set_slot(1, off_tank)
    raid.set_slot(2, heals)
    raid.set_slot(3, heals)
    raid.set_slot(4, lm)
    raid.set_slot(5, burg)
    raid.set_slot(6, dps_capt)
    for i in range(7, 12):
        raid.set_slot(i, dps)


async def select_players(bot, author, channel, raid, emojis):

    def check(reaction, user):
        return user == author

    class_emojis = emojis
    reactions = alphabet_emojis()
    reactions = reactions[:10]
    available = [player for player in raid.players if player not in raid.assigned_players]
    if not available:
        await channel.send("There are no players to assign for this raid!", delete_after=10)
        return
    if len(available) > 10:
        available = available[:10]
        await channel.send("**Warning**: removing some noobs from available players!", delete_after=10)
    msg_content = "Please select the player you want to assign a spot in the raid from the list below  using the " \
                  "corresponding reaction and then select a class. Assignment will finish after 30s of no " \
                  "interaction.\n"
    counter = 0
    for player in available:
        msg_content = msg_content + str(reactions[counter]) + " " + player.display_name + "\n"
        counter = counter + 1
    msg = await channel.send(msg_content)
    for reaction in reactions[:len(available)] + class_emojis:
        await msg.add_reaction(reaction)

    while True:
        # Update msg
        msg_content = "Please select the player you want to assign a spot in the raid from the list below  using the " \
                      "corresponding reaction and then select a class. Assignment will finish after 30s of no " \
                      "interaction.\n"
        counter = 0
        available = [player for player in raid.players if player not in raid.assigned_players]
        for player in available:
            msg_content = msg_content + str(reactions[counter]) + " " + player.display_name + "\n"
            counter = counter + 1
        await msg.edit(content=msg_content)
        # Get player
        try:
            (reaction, user) = await bot.wait_for('reaction_add', timeout=30, check=check)
        except asyncio.TimeoutError:
            await channel.send("Player assignment finished!", delete_after=10)
            break
        else:
            await msg.remove_reaction(reaction, user)
            try:
                index = reactions.index(reaction.emoji)
            except ValueError:
                await channel.send("That is not a player, please try again!", delete_after=10)
                continue
            else:
                try:
                    selected_player = available[index]
                except IndexError:
                    await channel.send("That is not a player, please try again!", delete_after=10)
                    continue
        # Get class
        try:
            (reaction, user) = await bot.wait_for('reaction_add', timeout=30, check=check)
        except asyncio.TimeoutError:
            await channel.send("Player assignment finished!", delete_after=10)
            break
        else:
            await msg.remove_reaction(reaction, user)
            if reaction.emoji in class_emojis:
                emoji_str = str(reaction.emoji)
                if PlayerClass(reaction.emoji) not in selected_player.classes:
                    await channel.send("That player did not sign up with this class!", delete_after=10)
                    continue

            else:
                await channel.send("That is not a class, please start over!", delete_after=10)
                continue
        # Check for free slot
        updated = False
        for i in range(len(raid.slots)):
            slot = raid.slot(i)
            if emoji_str in slot:
                updated = raid.assign_player(selected_player, i)
                if updated:
                    raid.set_slot(i, emoji_str)
                    msg_content = "Assigned {0} to {1}.".format(selected_player.display_name, emoji_str)
                    await channel.send(msg_content, delete_after=10)
                    break
        if not updated:
            await channel.send("There are no slots available for the selected class.", delete_after=10)
    await msg.delete()


def convert2UTC(time):
    offset = time.utcoffset()
    time = time.replace(tzinfo=None)
    time = time - offset
    return time


def convert2local(time):
    offset = time.utcoffset()
    time = time.replace(tzinfo=None)
    time = time + offset
    return time


def build_raid_message(raid, embed_texts, server_tz):

    def pstr(player):
        if not isinstance(player, Player):
            return "<Available>"
        else:
            return player.display_name

    server_time = local_time(raid.time, server_tz)
    header_time = format_time(server_time) + " server time"
    embed_title = "{0} {1} at {2}".format(raid.name, raid.tier, header_time)
    embed_description = "Bosses: {0}".format(raid.boss)
    embed = discord.Embed(title=embed_title, colour=discord.Colour(0x3498db), description=embed_description)
    time_string = build_time_string(raid.time)
    embed.add_field(name="Time zones:", value=time_string)
    embed.add_field(name="\u200B", value="\u200B")
    if raid.roster:
        embed_name = "The following line up has been selected:"
        embed_text = ""
        for i in range(6):
            embed_text = embed_text + raid.slot(i) + ": " + pstr(raid.assigned_players[i]) + "\n"
        embed.add_field(name=embed_name, value=embed_text)
        embed_name = "\u200B"
        embed_text = ""
        for i in range(6, 12):
            embed_text = embed_text + raid.slot(i) + ": " + pstr(raid.assigned_players[i]) + "\n"
        embed.add_field(name=embed_name, value=embed_text)
    # Add a field for each embed text
    for i in range(len(embed_texts)):
        if i == 0:
            embed_name = "The following {0} players are available:".format(len(raid.players))
        else:
            embed_name = "\u200B"
        embed.add_field(name=embed_name, value=embed_texts[i])
    embed.set_footer(text="Raid time in your local time (beta)")
    embed.timestamp = raid.time
    return embed


def build_raid_players(players, block_size=6):
    player_strings = []
    # Create the player strings
    for player in players:
        player_string = player.display_name + " "
        for emoji in player.classes:
            player_string = player_string + str(emoji)
        player_string = player_string + "\n"
        player_strings.append(player_string)
    # Sort the strings by length
    player_strings.sort(key=len, reverse=True)
    # Compute number of fields
    number_of_players = len(players)
    if number_of_players == 0:
        number_of_fields = 1
    else:
        number_of_fields = ((len(players) - 1) // block_size) + 1
    msg = [""] * number_of_fields
    # Add the players to the fields, spreading large strings.
    number_of_players_added = 0
    remainder = number_of_players % block_size
    if remainder:
        cap_index_last_field = number_of_fields * remainder
    else:
        cap_index_last_field = number_of_fields * block_size
    for player_string in player_strings:
        if number_of_players_added < cap_index_last_field:
            index = number_of_players_added % number_of_fields
        else:
            index = number_of_players_added % (number_of_fields - 1)
        number_of_players_added = number_of_players_added + 1
        msg[index] = msg[index] + player_string
    # Do not send an empty embed if there are no players.
    if msg[0] == "":
        msg[0] = "\u200B"
    # Check if the length does not exceed embed limit and split if we can.
    if len(max(msg, key=len)) >= 1024 and block_size >= 2:
        msg = build_raid_players(players, block_size=block_size // 2)
    return msg


def build_time_string(time):
    ny_time = local_time(time, "US/Eastern")
    lon_time = local_time(time, "Europe/London")
    syd_time = local_time(time, "Australia/Sydney")
    time_string = 'New York: ' + format_time(ny_time) + '\n' + 'London: ' + format_time(
        lon_time) + '\n' + 'Sydney: ' + format_time(syd_time)
    return time_string


def format_time(time):
    if os.name == "nt":  # Windows uses '#' instead of '-'.
        time_string = time.strftime("%A %#I:%M %p")
    else:
        time_string = time.strftime("%A %-I:%M %p")
    return time_string


def local_time(time, timezone):
    local_settings = {'TIMEZONE': timezone, 'RETURN_AS_TIMEZONE_AWARE': True}
    local_time = dateparser.parse(str(time), settings=local_settings)
    local_time = convert2local(local_time)
    return local_time
