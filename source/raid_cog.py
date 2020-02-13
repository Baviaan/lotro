import asyncio
import csv
import datetime
import dateparser
import discord
from discord.ext import commands
import json
import os
import pickle
import re

from initialise import add_emojis, get_role_emojis
from raid import Raid
from role_handling import get_role
from player import Player, PlayerClass
from utils import alphabet_emojis, get_match


class Tier(commands.Converter):
    async def convert(self, ctx, argument):
        return await self.converter(argument)

    @staticmethod
    async def converter(argument):
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
        time = RaidCog.convert2UTC(time)
        # Check if time is in near future.
        current_time = datetime.datetime.now()
        delta_time = datetime.timedelta(days=7)
        if current_time + delta_time < time:
            error_message = "You are not allowed to post raids more than a week in advance."
            raise commands.BadArgument(error_message)
        return time


class RaidCog(commands.Cog):
    # Get local timezone using mad hacks.
    local_tz = str(datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo)
    print("Default timezone: " + local_tz)
    # Load config file.
    with open('config.json', 'r') as f:
        config = json.load(f)
    # Get server timezone
    server_tz = config['SERVER_TZ']
    print("Server timezone: " + server_tz)

    def __init__(self, bot, raids):
        self.bot = bot
        self._last_member = None
        self.raids = raids
        # Load config file.
        with open('config.json', 'r') as f:
            config = json.load(f)

        # Specify names for class roles.
        # These will be automatically created on the server if they do not exist.
        self.raid_leader_name = config['LEADER']
        role_names = config['CLASSES']
        # change to immutable tuple
        self.role_names = tuple(role_names)
        bot.loop.create_task(self.background_task())

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        update = False
        guild = self.bot.get_guild(payload.guild_id)
        user = guild.get_member(payload.user_id)
        if user == self.bot.user:
            return
        for raid in self.raids:
            if payload.message_id == raid.post_id:
                update = await self.raid_update(payload, raid)
                emoji = payload.emoji
                channel = guild.get_channel(payload.channel_id)
                message = await channel.fetch_message(payload.message_id)
                await message.remove_reaction(emoji, user)
                break
        if update:
            self.save()

    @commands.command(aliases=['instance', 'r'])
    async def raid(self, ctx, name, tier: Tier, *, time: Time(server_tz)):
        """Schedules a raid"""
        raid = await self.raid_command(ctx, name, tier, "All", time)
        self.raids.append(raid)
        self.save()

    raid_brief = "Schedules a raid"
    raid_description = "Schedules a raid. Day/timezone will default to today/{0} if not specified. " \
                       "You can use 'server' as timezone. Usage:".format(local_tz)
    raid_example = "Examples:\n!raid Anvil 2 Friday 4pm server\n!raid throne t3 21:00"
    raid.update(help=raid_example, brief=raid_brief, description=raid_description)

    @commands.command(aliases=['anvil', 'nod'])
    async def fastraid(self, ctx, *, time: Time(server_tz)):
        """Shortcut to schedule a raid"""
        name = ctx.invoked_with
        if name == "fastraid":
            name = "unknown raid"
        try:
            tier = await Tier().converter(ctx.channel.name)
        except commands.BadArgument:
            await ctx.send("Channel name does not specify tier.")
        else:
            if '1' in tier or '2' in tier:
                roster = False
            else:
                roster = True
            raid = await self.raid_command(ctx, name, tier, "All", time, roster=roster)
            self.raids.append(raid)
            self.save()

    fastraid_brief = "Shortcut to schedule a raid"
    fastraid_description = "Schedules a raid with the name of the command, tier from channel name and bosses 'All'. " \
                        "Day/timezone will default to today/{0} if not specified. You can use 'server' as timezone. " \
                        "Usage:".format(local_tz)
    fastraid_example = "Examples:\n!anvil Friday 4pm server\n!anvil 21:00 BST"
    fastraid.update(help=fastraid_example, brief=fastraid_brief, description=fastraid_description)

    @staticmethod
    def get_raid_name(name):
        with open('list-of-raids.csv', 'r') as f:
            reader = csv.reader(f)
            raid_list = list(reader)
            names = [x[0] for x in raid_list]
            match = get_match(name, names)
            if match[0]:
                return match[0]
            nicknames = [x[1] for x in raid_list]
            match = get_match(name, nicknames)
            if match[0]:
                result = [x[0] for x in raid_list if x[1] == match[0]]
                return result[0]
            return name

    async def raid_command(self, ctx, name, tier, boss, time, roster=False):
        name = self.get_raid_name(name)
        boss = boss.capitalize()
        raid = Raid(name, tier, boss, time)
        class_emojis = await get_role_emojis(ctx.guild, self.role_names)
        if roster:
            raid.set_roster(roster)
            self.set_default_roster(raid, class_emojis)
        embed = self.build_raid_message(raid, "\u200B")
        post = await ctx.send(embed=embed)
        raid.set_post_id(post.id)
        raid.set_channel_id(ctx.channel.id)
        raid.set_guild_id(ctx.guild.id)
        emojis = ["\U0001F6E0", "\u26CF", "\u274C", "\u2705"]  # Config, pick, cancel, check
        emojis.extend(class_emojis)
        await add_emojis(emojis, post)
        await asyncio.sleep(0.25)
        await post.pin()
        return raid

    async def raid_update(self, payload, raid):
        bot = self.bot
        guild = bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        user = guild.get_member(payload.user_id)
        emoji = payload.emoji
        emojis = await get_role_emojis(guild, self.role_names)
        update = False

        def check(msg):
            return msg.author == user

        if str(emoji) in ["\U0001F6E0", "\u26CF"]:
            raid_leader = await get_role(guild, self.raid_leader_name)
            if raid_leader not in user.roles:
                error_msg = "You do not have permission to change the raid settings. This incident will be reported."
                print("Putting {0} on the naughty list.".format(user.name))
                await channel.send(error_msg, delete_after=15)
                return False
        if str(emoji) == "\u26CF":  # Pick emoji
            if not raid.roster:
                await channel.send("Roster is not enabled for this raid.", delete_after=10)
                return False
            update = await self.select_players(user, channel, raid, emojis)
        elif str(emoji) == "\U0001F6E0":  # Config emoji
            update = await self.configure(user, channel, raid, emojis)
        elif str(emoji) == "\u274C":  # Cancel emoji
            try:
                player = Player(user)
                if player in raid.assigned_players:
                    error_msg = "Dearest raid leader, {0} would like to cancel their availability but you have " \
                                "assigned them a spot in the raid. Please resolve this conflict.".format(user.mention)
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
        msg = self.build_raid_players(raid.players)
        embed = self.build_raid_message(raid, msg)
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

    async def configure(self, user, channel, raid, emojis):
        bot = self.bot

        def check(msg):
            return user == msg.author

        text = "Please respond with 'roster', 'time' or 'boss' to indicate which setting you wish to update for this " \
               "raid. "
        msg = await channel.send(text)
        try:
            reply = await bot.wait_for('message', timeout=20, check=check)
        except asyncio.TimeoutError:
            await msg.delete()
            await channel.send("Configuration finished!", delete_after=10)
            return False
        else:
            await msg.delete()
            await reply.delete()
            if reply.content.lower().startswith('r'):
                update = await self.roster_configure(user, channel, raid, emojis)
            elif reply.content.lower().startswith('t'):
                update = await self.time_configure(user, channel, raid)
            elif reply.content.lower().startswith('b'):
                update = await self.boss_configure(user, channel, raid)
            else:
                update = False
        return update

    @staticmethod
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

    @staticmethod
    def set_roster(raid, emoji, slot):
        raid.set_slot(slot, str(emoji))

    async def boss_configure(self, author, channel, raid):
        bot = self.bot

        def check(msg):
            return author == msg.author

        msg = await channel.send("Please specify the new raid boss.")
        try:
            response = await bot.wait_for('message', check=check, timeout=30)
        except asyncio.TimeoutError:
            return False
        else:
            await response.delete()
        finally:
            await msg.delete()
        boss = response.content.capitalize()
        raid.set_boss(boss)
        return True

    async def time_configure(self, author, channel, raid):
        bot = self.bot

        def check(msg):
            return author == msg.author

        msg = await channel.send("Please specify the new raid time.")
        try:
            response = await bot.wait_for('message', check=check, timeout=30)
        except asyncio.TimeoutError:
            return False
        finally:
            await msg.delete()
        try:
            time = await Time(self.server_tz).converter(response.content)
        except commands.BadArgument:
            error_msg = "Failed to parse time argument: " + response.content
            await channel.send(error_msg, delete_after=20)
            return False
        finally:
            await response.delete()
        raid.set_time(time)
        return True

    async def roster_configure(self, author, channel, raid, emojis):
        bot = self.bot

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
            self.set_default_roster(raid, emojis)
            update = True
        await channel.send("Roster enabled for this raid.", delete_after=10)
        text = "If you wish to overwrite a default raid slot please respond with the slot number followed by the " \
               "class emojis you would like. Configuration will finish after 20s of no interaction. "
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
                    self.set_roster(raid, new_classes, index-1)
                    await channel.send("Classes for slot {0} updated!".format(index), delete_after=10)
                    update = True
        await msg.delete()
        return update

    async def select_players(self, author, channel, raid, emojis):
        bot = self.bot

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
            msg_content = "Please select the player you want to assign a spot in the raid from the list below using " \
                          "the corresponding reaction. Assignment will finish after 20s of no interaction.\nAvailable" \
                          " players:\n "
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
                        self.set_default_roster(raid, emojis, [index])
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

    @staticmethod
    def convert2UTC(time):
        offset = time.utcoffset()
        time = time.replace(tzinfo=None)
        time = time - offset
        return time

    @staticmethod
    def convert2local(time):
        offset = time.utcoffset()
        time = time.replace(tzinfo=None)
        time = time + offset
        return time

    def build_raid_message(self, raid, embed_texts):

        def pstr(player):
            if not isinstance(player, Player):
                return "<Available>"
            else:
                return player.display_name

        server_time = self.local_time(raid.time, self.server_tz)
        header_time = self.format_time(server_time) + " server time"
        embed_title = "{0} {1} at {2}".format(raid.name, raid.tier, header_time)
        embed_description = "Bosses: {0}".format(raid.boss)
        embed = discord.Embed(title=embed_title, colour=discord.Colour(0x3498db), description=embed_description)
        time_string = self.build_time_string(raid.time)
        embed.add_field(name="Time zones:", value=time_string)
        if raid.roster:
            embed_name = "Selected line up:"
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

    def build_raid_players(self, players, block_size=6):
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
            msg = self.build_raid_players(players, block_size=block_size // 2)
        return msg

    def build_time_string(self, time):
        ny_time = self.local_time(time, "US/Eastern")
        lon_time = self.local_time(time, "Europe/London")
        syd_time = self.local_time(time, "Australia/Sydney")
        time_string = 'New York: ' + self.format_time(ny_time) + '\n' + 'London: ' + self.format_time(
            lon_time) + '\n' + 'Sydney: ' + self.format_time(syd_time)
        return time_string

    @staticmethod
    def format_time(time):
        if os.name == "nt":  # Windows uses '#' instead of '-'.
            time_string = time.strftime("%A %#I:%M %p")
        else:
            time_string = time.strftime("%A %-I:%M %p")
        return time_string

    def local_time(self, time, timezone):
        local_settings = {'TIMEZONE': timezone, 'RETURN_AS_TIMEZONE_AWARE': True}
        local_time = dateparser.parse(str(time), settings=local_settings)
        local_time = self.convert2local(local_time)
        return local_time

    def save(self):
        with open('raids.pkl', 'wb') as f:
            pickle.dump(self.raids, f)
        print("Saved raids to file at: " + str(datetime.datetime.now()))

    async def background_task(self):
        bot = self.bot
        raids = self.raids
        await bot.wait_until_ready()
        sleep_time = 300  # Run background task every five minutes.
        save_time = 36  # Save to file every three hours.
        expiry_time = datetime.timedelta(seconds=7200)  # Delete raids after 2 hours.
        notify_time = datetime.timedelta(seconds=sleep_time)
        counter = 0
        while not bot.is_closed():
            await asyncio.sleep(sleep_time)
            counter = counter + 1
            current_time = datetime.datetime.utcnow()  # Raid time is stored in UTC.
            # Copy the list to iterate over.
            for raid in raids[:]:
                if current_time > raid.time + expiry_time:
                    # Find the raid post and delete it.
                    channel = bot.get_channel(raid.channel_id)
                    try:
                        post = await channel.fetch_message(raid.post_id)
                    except discord.NotFound:
                        print("Raid post already deleted.")
                    except discord.Forbidden:
                        print("We are missing required permissions to delete raid post.")
                    except AttributeError:
                        print("Raid channel has been deleted.")
                    else:
                        await post.delete()
                        print("Deleted old raid post.")
                    finally:
                        raids.remove(raid)
                        print("Deleted old raid.")
                elif current_time < raid.time - notify_time and current_time >= raid.time - notify_time * 2:
                    channel = bot.get_channel(raid.channel_id)
                    try:
                        await channel.fetch_message(raid.post_id)
                    except discord.NotFound:
                        print("Raid post already deleted.")
                        raids.remove(raid)
                        print("Deleted old raid.")
                    except discord.Forbidden:
                        print("We are missing required permissions to see raid post.")
                    except AttributeError:
                        print("Raid channel has been deleted.")
                        raids.remove(raid)
                        print("Deleted old raid.")
                    else:
                        if raid.roster:
                            raid_start_msg = "Gondor calls for aid! "
                            for player in raid.assigned_players:
                                if player:
                                    raid_start_msg = raid_start_msg + "<@{0}> ".format(player.id)
                            raid_start_msg = raid_start_msg + "will you answer the call? We are forming for the raid now."
                            await channel.send(raid_start_msg, delete_after=sleep_time * 2)
            if counter >= save_time:
                self.save()  # Save raids to file.
                counter = 0  # Reset counter to 0.


def setup(bot):
    raids = []
    # Load the saved raid posts from file.
    try:
        with open('raids.pkl', 'rb') as f:
            raids = pickle.load(f)
    except (OSError, IOError) as e:
        pass
    print("We have the following raid data in memory.")
    for raid in raids:
        print(raid)
    bot.add_cog(RaidCog(bot, raids))
    print("Loaded Raid Cog.")
