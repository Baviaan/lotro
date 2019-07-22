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
    emojis.append("\U0001F6E0")  # Config emoji
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

    if str(emoji) in ["\u23F2", "\u26CF", "\U0001F6E0"] or emoji == boss_emoji:
        raid_leader = await get_role(guild, raid_leader_name)
        if raid_leader not in user.roles:
            error_msg = "You do not have permission to change the raid settings. This incident will be reported."
            print("Putting {0} on the naughty list.".format(user.name))
            await channel.send(error_msg, delete_after=15)
            return False
    if emoji == boss_emoji:
        await channel.send("Please specify the new raid boss.", delete_after=15)
        try:
            response = await bot.wait_for('message', check=check, timeout=300)
        except asyncio.TimeoutError:
            return False
        else:
            await response.delete()
        boss = response.content.capitalize()
        raid.set_boss(boss)
        update = True
    elif str(emoji) == "\u23F2":  # Timer emoji
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
        update = await select_players(bot, user, channel, raid, emojis)
    elif str(emoji) == "\U0001F6E0":  # Config emoji
        await roster_configure(bot, user, channel, raid, emojis)
    elif str(emoji) == "\u274C":  # Cancel emoji
        try:
            player = Player(user)
            if player in raid.assigned_players:
                error_msg = "Dearest raid leader, {0} would like to cancel their availability but you have assigned them a spot in the raid. Please resolve this conflict.".format(user.mention)
                await channel.send(error_msg)
                update = False
            else:
                update = raid.remove_player(user)
        except AttributeError:
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


def set_default_roster(raid, emojis, slots=range(12)):
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
    if 0 in slots:
        raid.set_slot(0, main_tank)
    if 1 in slots:
        raid.set_slot(1, off_tank)
    if 2 in slots:
        raid.set_slot(2, heals)
    if 3 in slots:
        raid.set_slot(3, heals)
    if 4 in slots:
        raid.set_slot(4, lm)
    if 5 in slots:
        raid.set_slot(5, burg)
    if 6 in slots:
        raid.set_slot(6, dps_capt)
    for i in range(7, 12):
        if i in slots:
            raid.set_slot(i, dps)


def set_roster(raid, emoji, slot):
    raid.set_slot(slot, str(emoji))


async def roster_configure(bot, author, channel, raid, emojis):

    def check(msg):
        return author == msg.author

    text = "Please respond with 'yes/no' to indicate whether you want to use the roster for this raid."
    msg = await channel.send(text)
    try:
        reply = await bot.wait_for('message', timeout=20, check=check)
    except asyncio.TimeoutError:
        await channel.send("Roster configuration finished!", delete_after=10)
        return False
    else:
        await reply.delete()
        if 'n' in reply.content.lower():
            if raid.roster:
                raid.set_roster(False)
                await channel.send("Roster disabled for this raid.\nRoster configuration finished!", delete_after=10)
                return True
        elif 'y' not in reply.content.lower():
            await channel.send("Roster configuration finished!", delete_after=10)
            return False
    finally:
        await msg.delete()
    update = False
    if not raid.roster:
        raid.set_roster(True)
        set_default_roster(raid, emojis)
        update = True
    await channel.send("Roster enabled for this raid.", delete_after=10)
    text = "If you wish to overwrite a default raid slot please respond with the slot number followed by the class " \
           "emojis you would like. Configuration will finish 20s after no interaction. "
    msg = await channel.send(text)
    while True:
        try:
            reply = await bot.wait_for('message', timeout=20, check=check)
        except asyncio.TimeoutError:
            await channel.send("Roster configuration finished!", delete_after=10)
            break
        else:
            await reply.delete()
            new_classes = ""
            counter = 0
            if reply.content[0].isdigit():
                index = int(reply.content[0])
                if index == 1:
                    if reply.content[1].isdigit():
                        index = int(reply.content[0:2])
                if index <= 0 or index > len(raid.slots):
                    await channel.send("No valid slot provided!", delete_after=10)
                    return update
            else:
                await channel.send("No slot provided!", delete_after=10)
                return update
            for emoji in emojis:
                emoji_str = str(emoji)
                if emoji_str in reply.content:
                    counter = counter + 1
                    new_classes = new_classes + emoji_str
                if counter > 3:
                    break  # allow maximum of 4 classes
            if new_classes != "":
                set_roster(raid, new_classes, index-1)
                await channel.send("Classes for slot {0} updated!".format(index), delete_after=10)
                update = True
    await msg.delete()
    return update


async def select_players(bot, author, channel, raid, emojis):

    def check(reaction, user):
        return user == author

    reaction_limit = 20
    class_emojis = emojis
    reactions = alphabet_emojis()
    reactions = reactions[:reaction_limit]
    available = [player for player in raid.players]
    if not available:
        await channel.send("There are no players to assign for this raid!", delete_after=10)
        return False
    if len(available) > reaction_limit:
        available = available[:20]
        await channel.send("**Warning**: removing some noobs from available players!", delete_after=10)
    msg_content = "Please select the player you want to assign a spot in the raid from the list below  using the " \
                  "corresponding reaction. Assignment will finish after 20s of no " \
                  "interaction.\nAvailable players:\n"
    counter = 0
    for player in available:
        if player in raid.assigned_players:
            msg_content = msg_content + str(reactions[counter]) + " ~~" + player.display_name + "~~\n"
        else:
            msg_content = msg_content + str(reactions[counter]) + " " + player.display_name + "\n"
        counter = counter + 1
    msg = await channel.send(msg_content)
    for reaction in reactions[:len(available)]:
        await msg.add_reaction(reaction)
    class_msg_content = "Select the class for this player."
    class_msg = await channel.send(class_msg_content)
    for reaction in class_emojis:
        await class_msg.add_reaction(reaction)

    while True:
        # Update msg
        msg_content = "Please select the player you want to assign a spot in the raid from the list below  using the " \
                      "corresponding reaction. Assignment will finish after 20s of no " \
                      "interaction.\nAvailable players:\n"
        counter = 0
        for player in available:
            if player in raid.assigned_players:
                msg_content = msg_content + str(reactions[counter]) + " ~~" + player.display_name + "~~\n"
            else:
                msg_content = msg_content + str(reactions[counter]) + " " + player.display_name + "\n"
            counter = counter + 1
        await msg.edit(content=msg_content)
        # Get player
        try:
            (reaction, user) = await bot.wait_for('reaction_add', timeout=20, check=check)
        except asyncio.TimeoutError:
            await channel.send("Player assignment finished!", delete_after=10)
            break
        else:
            try:
                index = reactions.index(reaction.emoji)
            except ValueError:
                await class_msg.remove_reaction(reaction, user)
                await channel.send("Please select a player first!", delete_after=10)
                continue
            else:
                await msg.remove_reaction(reaction, user)
                selected_player = available[index]
                try:
                    index = raid.assigned_players.index(selected_player)
                    raid.unassign_player(selected_player, index)
                    set_default_roster(raid, emojis, [index])
                    text = "Removed {0} from the line up!".format(selected_player.display_name)
                    await channel.send(text, delete_after=10)
                    continue
                except ValueError:
                    pass
        # Get class
        try:
            (reaction, user) = await bot.wait_for('reaction_add', timeout=20, check=check)
        except asyncio.TimeoutError:
            await channel.send("Player assignment finished!", delete_after=10)
            break
        else:
            if reaction.emoji in class_emojis:
                await class_msg.remove_reaction(reaction, user)
                emoji_str = str(reaction.emoji)
                if PlayerClass(reaction.emoji) not in selected_player.classes:
                    text = "{0} did not sign up with {1}!".format(selected_player.display_name, emoji_str)
                    await channel.send(text, delete_after=10)
                    continue

            else:
                await msg.remove_reaction(reaction, user)
                await channel.send("That is not a class, please start over!", delete_after=10)
                continue
        # Check for free slot
        updated = False
        for i in range(len(raid.slots)):
            slot = raid.slot(i)
            if emoji_str in slot:
                updated = raid.assign_player(selected_player, i)
                if updated:
                    raid.set_slot(i, emoji_str, False)
                    msg_content = "Assigned {0} to {1}.".format(selected_player.display_name, emoji_str)
                    await channel.send(msg_content, delete_after=10)
                    break
        if not updated:
            await channel.send("There are no slots available for the selected class.", delete_after=10)
    await msg.delete()
    await class_msg.delete()
    return True


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
