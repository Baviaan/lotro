import asyncio
import csv
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks
from enum import Enum
import json
import logging
import random
import re
import requests
import time
from typing import Optional

from database import create_table, count, delete, read_config_key, select, select_le, select_one, select_order, upsert
from time_cog import Time
from utils import get_match

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create Enumerator class
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    logger.warning(f"No config file found. Please create the file 'config.json', see GitHub for an example.")
role_names = read_config_key(config, 'CLASSES', True)
duo_spec = read_config_key(config, 'DUOSPEC', False)
Classes = Enum("Classes", role_names)

sign_up_delay = 3
assign_delay = 10

class RaidCog(commands.Cog):

    # Load raid (nick)names and size
    raid_lookup = dict()
    raid_size = dict()
    with open('list-of-raids.csv', 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            raid_lookup[row[0]] = row[1]
            raid_size[row[1]] = int(row[2])

    def __init__(self, bot):
        self.bot = bot
        self.conn = bot.conn
        self.role_names = bot.role_names
        self.creep_names = bot.creep_names
        self.slots_class_names = bot.slots_class_names
        self.time_cog = bot.get_cog('TimeCog')
        self.calendar_cog = bot.get_cog('CalendarCog')

        create_table(self.conn, 'raid')
        create_table(self.conn, 'player')
        create_table(self.conn, 'assign')
        create_table(self.conn, 'specs')

        raids = select(self.conn, 'Raids', ['raid_id'])
        self.raids = [raid[0] for raid in raids]
        logger.info("We have loaded {} raids in memory.".format(len(self.raids)))

        self.update_call = {}

        # Emojis
        host_guild = bot.get_guild(bot.host_id)
        if not host_guild:
            # Use first guild as host
            host_guild = bot.guilds[0]
        logger.info("Using emoji from {0}.".format(host_guild))
        self.class_emojis = [emoji for emoji in host_guild.emojis if emoji.name in self.role_names]
        self.creep_emojis = [emoji for emoji in host_guild.emojis if emoji.name in self.creep_names]
        self.emojis_dict = {emoji.name: str(emoji) for emoji in self.class_emojis + self.creep_emojis}

        # Add raid views
        self.bot.add_view(RaidView(self))
        self.bot.add_view(CreepView(self))

        # Add raid commands to tree
        @app_commands.guild_only()
        @app_commands.choices(tier=[
            app_commands.Choice(name='1', value='T1'),
            app_commands.Choice(name='2', value='T2'),
            app_commands.Choice(name='2c', value='T2c'),
            app_commands.Choice(name='3', value='T3'),
            app_commands.Choice(name='4', value='T4'),
            app_commands.Choice(name='5', value='T5'),
        ])
        @app_commands.describe(tier=_("The raid tier."), time=_("When the raid should be scheduled."), aim=_("A short description of your objective."))
        async def raid_respond(interaction: discord.Interaction, tier: app_commands.Choice[str], time: str, aim: Optional[str]):
            await self.handle_raid_command(interaction, interaction.command.name, tier.value, time, aim)

        for key, full_name in self.raid_lookup.items():
            description = _("Schedule {0}.").format(full_name)
            command = app_commands.Command(name=key, description=description, callback=raid_respond)
            self.bot.tree.add_command(command)

    async def cog_load(self):
        self.background_task.start()

    async def cog_unload(self):
        self.background_task.cancel()

    async def handle_raid_command(self, interaction, name, tier, time, aim, creep=False):
            new_raid = False
            channel = interaction.channel
            guild = interaction.guild
            perms = channel.permissions_for(guild.me)
            if not (perms.send_messages and perms.embed_links):
                content = _("Missing permissions to access this channel.")
            else:
                try:
                    timestamp = Time().converter(self.bot, guild.id, interaction.user.id, time)
                except commands.BadArgument as e:
                    content = str(e)
                else:
                    content = _("Posting a new raid!")
                    new_raid = True
            await interaction.response.send_message(content, ephemeral=True)
            if new_raid:
                if tier and int(tier[1]) > 2:
                    roster = True
                else:
                    roster = False
                await self.post_raid(name, tier, aim, timestamp, roster, guild.id, channel, interaction.user.id, creep)

    @app_commands.command(name=_("custom"), description=_("Schedule a custom raid or meetup."))
    @app_commands.describe(name=_("The name of the raid or meetup."), tier=_("The raid tier."), time=_("When the raid should be scheduled."), aim=_("A short description of your objective."))
    @app_commands.choices(tier=[
        app_commands.Choice(name='1', value='T1'),
        app_commands.Choice(name='2', value='T2'),
        app_commands.Choice(name='2c', value='T2c'),
        app_commands.Choice(name='3', value='T3'),
        app_commands.Choice(name='4', value='T4'),
        app_commands.Choice(name='5', value='T5'),
    ])
    @app_commands.guild_only()
    async def custom_respond(self, interaction: discord.Interaction, name: str, time: str, tier: Optional[app_commands.Choice[str]], aim: Optional[str]):
        if tier:
            tier = tier.value
        await self.handle_raid_command(interaction, name, tier, time, aim)

    @app_commands.command(name=_("creep"), description=_("Schedule a creep raid or meetup."))
    @app_commands.describe(time=_("When the raid should be scheduled."), aim=_("A short description of your objective."))
    @app_commands.guild_only()
    async def creep_respond(self, interaction: discord.Interaction, time: str, aim: Optional[str]):
        await self.handle_raid_command(interaction, "Ettenmoors", "", time, aim, True)

    @app_commands.command(name=_("leader"), description=_("Specify the role which is permitted to edit raids."))
    @app_commands.describe(role=_("Discord role."))
    @app_commands.guild_only()
    async def leader_respond(self, interaction: discord.Interaction, role: Optional[discord.Role]):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_("You must be an admin to change the raid leader role."), ephemeral=True)
        else:
            if role:
                role_id = role.id
            else:
                role_id = None
            res = upsert(self.conn, 'Settings', ['raid_leader'], [role_id], ['guild_id'], [interaction.guild_id])
            self.conn.commit()
            if role:
                await interaction.response.send_message(_("Set the raid leader role to {0}.").format(role.mention), allowed_mentions=discord.AllowedMentions.none())
            else:
                await interaction.response.send_message(_("Deleted the raid leader role."))

    @app_commands.command(name=_("kin"), description=_("Set your kin role to distinguish kin sign ups from non-kin."))
    @app_commands.describe(role=_("Discord role."))
    @app_commands.guild_only()
    async def priority_respond(self, interaction: discord.Interaction, role: Optional[discord.Role]):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_("You must be an admin to change the kin role."), ephemeral=True)
        else:
            if role:
                role_id = role.id
            else:
                role_id = None
            res = upsert(self.conn, 'Settings', ['priority'], [role_id], ['guild_id'], [interaction.guild_id])
            self.conn.commit()
            if role:
                await interaction.response.send_message(_("Set the kin role to {0}.").format(role.mention), allowed_mentions=discord.AllowedMentions.none())
            else:
                await interaction.response.send_message(_("Deleted the kin role."))

    @app_commands.command(name=_("remove_roles"), description=_("Deletes your class roles (used when signing up)."))
    @app_commands.guild_only()
    async def roles_respond(self, interaction: discord.Interaction):
        await interaction.response.send_message(_("Removing your class roles..."))
        member = interaction.user
        try:
            await member.remove_roles(*[role for role in member.roles if role.name in self.role_names])
            content = _("Successfully removed your class roles.")
        except discord.Forbidden:
            content = _("I am missing permissions to manage the class roles!")
        await interaction.edit_original_response(content=content)

    @app_commands.command(name=_("specs"), description=_("Set a specialization for your class."))
    @app_commands.describe(classes=_("The class to set your specialization for."), spec=_("Your chosen specialization."))
    @app_commands.choices(spec=[
        app_commands.Choice(name='Red \U0001F534', value=0b001),
        app_commands.Choice(name='Blue \U0001F535', value=0b010),
        app_commands.Choice(name='Yellow \U0001F7E1', value=0b100),
        app_commands.Choice(name='Red \U0001F534 and Blue \U0001F535', value=0b011),
        app_commands.Choice(name='Blue \U0001F535 and Yellow \U0001F7E1', value=0b110),
        app_commands.Choice(name='Red \U0001F534 and Yellow \U0001F7E1', value=0b101),
        app_commands.Choice(name='Clear specialization', value=0b000),
    ])
    async def specs_respond(self, interaction: discord.Interaction, classes: Classes, spec: app_commands.Choice[int]):
        if duo_spec and classes.name in duo_spec and (spec.value & 0b100):
            await interaction.response.send_message(_("Invalid specialization."))
            return
        upsert(self.conn, 'Specs', [classes.name], [spec.value], ['player_id'], [interaction.user.id])
        await interaction.response.send_message(_("Updated your {0} specialization.").format(classes.name), ephemeral=True)

    @app_commands.command(name=_("list_players"), description=_("List the signed up players for a raid in order of sign up time."))
    @app_commands.describe(raid_number=_("Specify the raid to list, e.g. 2 for the second upcoming raid. This defaults to 1 if omitted."), cut_off=_("Specify cut-off time in hours before raid time. This defaults to 24 hours if omitted."))
    @app_commands.guild_only()
    async def list_respond(self, interaction: discord.Interaction, raid_number: Optional[int]=1, cut_off: Optional[int]=24):
        if not self.calendar_cog.is_raid_leader(interaction.user, interaction.guild):
            await interaction.response.send_message(_("You must be a raid leader to list players."))
            return
        conn = self.conn
        raids = select_order(conn, 'Raids', ['raid_id', 'name', 'time'], 'time', ['guild_id'], [interaction.guild_id])
        if raid_number > len(raids):
            await interaction.response.send_message(_("Cannot list raid {0}: only {1} raids exist.").format(raid_number, len(raids)))
            return
        elif raid_number < 1:
            await interaction.response.send_message(_("Please provide a positive integer."))
            return
        raid_id, raid_name, raid_time = raids[raid_number-1]
        player_data = select_order(conn, 'Players', ['byname', 'timestamp'], 'timestamp', ['raid_id', 'unavailable'], [raid_id, False])

        # build the embed
        cutoff_time = raid_time - 3600 * cut_off
        embed_title = _("**Sign up list for {0} on <t:{1}>**").format(raid_name, raid_time)
        embed = discord.Embed(title=embed_title, colour=discord.Colour(0x3498db))
        players_on = ["\u200b"]
        players_off = ["\u200b"]
        times_on = ["\u200b"]
        times_off = ["\u200b"]
        for row in player_data:
            if row[1]:
                time = row[1]
                if time < cutoff_time:
                    players_on.append(row[0])
                    times_on.append(f"<t:{time}:R>")
                else:
                    players_off.append(row[0])
                    times_off.append(f"<t:{time}:R>")
            else:
                players_on.append(row[0])
                times_on.append("\u200b")
        players_on = "\n".join(players_on)
        players_off = "\n".join(players_off)
        times_on = "\n".join(times_on)
        times_off = "\n".join(times_off)
        embed.add_field(name=_("Players:"), value=players_on)
        embed.add_field(name=_("Sign up time:"), value=times_on)
        embed.add_field(name="\u200b", value="\u200b")
        embed.add_field(name=_("Late players:"), value=players_off)
        embed.add_field(name=_("Sign up time:"), value=times_off)
        embed.add_field(name="\u200b", value="\u200b")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name=_("list_raids"), description=_("Lists the events you have signed up for."))
    async def list_raids_respond(self, interaction: discord.Interaction):
        raids = select(self.conn, 'Players', ['raid_id'], ['player_id', 'unavailable'], [interaction.user.id, False])
        for i, raid in enumerate(raids):
            raid_data = select_one(self.conn, 'Raids', ['channel_id', 'guild_id', 'name', 'time'], ['raid_id'], [raid[0]])
            raids[i] = raid + raid_data
        # sort by raid time instead of creation time
        raids.sort(key=lambda x: int(x[4]))
        # build the embed
        embed_title = _("**You are signed up for the following events:**")
        embed = discord.Embed(title=embed_title, colour=discord.Colour(0x3498db))
        for raid in raids[:25]:
            raid_id, channel_id, guild_id, name, time = raid
            field_name = f"{name} at <t:{time}>"
            field_text = f"https://discord.com/channels/{guild_id}/{channel_id}/{raid_id}"
            embed.add_field(name=field_name, value=field_text, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def get_raid_name(self, name):
        try:
            name = self.raid_lookup[name.lower()]
        except KeyError:
            names = list(self.raid_lookup.values())
            match = get_match(name, names)
            if match[0]:
                name = match[0]
        return name

    def get_raid_size(self, full_name):
        try:
            size = self.raid_size[full_name]
        except KeyError:
            size = 12
        return size

    async def post_raid(self, name, tier, boss, timestamp, roster, guild_id, channel, author_id, creep=False):
        full_name = self.get_raid_name(name)
        raid_size = self.get_raid_size(full_name)
        raid_time = datetime.datetime.utcfromtimestamp(timestamp)
        tag = f'{name}{raid_time.day}{raid_time.hour}'
        # Check if time is in near future. Otherwise parsed date was likely unintended.
        current_time = int(time.time())
        if current_time + 31536000 < timestamp:
            error_message = _("Events must start within 1 year <@{0}>. Your event on {1} UTC will not be saved.").format(
                author_id, raid_time)
            await channel.send(error_message)
            return
        if current_time + 604800 < timestamp or current_time > timestamp:
            error_message = _("Please check the date <@{0}>. You are posting a raid for: {1} UTC.").format(
                author_id, raid_time)
            await channel.send(error_message, delete_after=30)
        post = await channel.send('\u200B')
        raid_id = post.id
        raid_columns = ['channel_id', 'guild_id', 'organizer_id', 'name', 'tier', 'boss', 'time', 'roster', 'tag', 'size']
        raid_values = [channel.id, guild_id, author_id, full_name, tier, boss, timestamp, roster, tag, raid_size]
        upsert(self.conn, 'Raids', raid_columns, raid_values, ['raid_id'], [raid_id])
        await channel.guild.create_role(mentionable=True, name=tag)
        if not creep:
            self.roster_init(raid_id, raid_size)
            embed = self.build_raid_message(raid_id, "\u200B", None)
            await post.edit(embed=embed, view=RaidView(self))
        else:
            embed = self.build_raid_message(raid_id, "\u200B", None)
            await post.edit(embed=embed, view=CreepView(self))
        self.raids.append(raid_id)
        await self.create_guild_event(channel, raid_id)
        self.conn.commit()
        logger.info("Created new raid: {0} at {1} for guild {2}.".format(full_name, raid_time, guild_id))
        await self.calendar_cog.update_calendar(guild_id)

    async def create_guild_event(self, channel, raid_id):
        event_id = await self.calendar_cog.create_guild_event(channel.guild, raid_id)
        if event_id == 0:
            return
        if not event_id:
            err_msg = _("Failed to create the discord event. Please check the bot has the manage event permission.")
            await channel.send(err_msg, delete_after=20)
        else:
            upsert(self.conn, 'Raids', ['event_id'], [event_id], ['raid_id'], [raid_id])

    def roster_init(self, raid_id, raid_size):
        available = _("<Open>")
        assignment_columns = ['player_id', 'byname', 'class_name']
        number_of_slots = min(len(self.slots_class_names), raid_size)
        for i in range(number_of_slots):
            assignment_values = [None, available, ','.join(self.slots_class_names[i])]
            upsert(self.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'], [raid_id, i])

    async def has_raid_permission(self, user, guild, raid_id, channel=None):
        if user.guild_permissions.administrator:
            return True

        organizer_id = select_one(self.conn, 'Raids', ['organizer_id'], ['raid_id'], [raid_id])
        if organizer_id == user.id:
            return True

        raid_leader_id = select_one(self.conn, 'Settings', ['raid_leader'], ['guild_id'], [guild.id])
        if raid_leader_id:
            raid_leader = guild.get_role(raid_leader_id)
            if raid_leader in user.roles:
                return True
        if channel:
            perm_msg = _("You do not have permission to change the raid settings.")
            await channel.send(perm_msg, delete_after=15)
        return False

    async def update_raid_post(self, raid_id, channel, delay=assign_delay):
        try:
            self.update_call[raid_id] += 1
        except KeyError:
            self.update_call[raid_id] = 0
        update_call = self.update_call[raid_id]
        await asyncio.sleep(delay)
        # If someone is spamming buttons only send the last update
        if update_call < self.update_call[raid_id]:
            return
        available = self.build_raid_players(raid_id)
        unavailable = self.build_raid_players(raid_id, available=False)
        embed = self.build_raid_message(raid_id, available, unavailable)
        if not embed:
            return
        post = channel.get_partial_message(raid_id)
        try:
            await post.edit(embed=embed)
        except discord.HTTPException as e:
            logger.warning(e)
            msg = "The above error occurred sending the following messages as embed:"
            error_msg = "\n".join([msg, embed.title, embed.description, str(embed.fields)])
            logger.warning(error_msg)
            await channel.send(_("That's an error. Check the logs."))

    def build_raid_message(self, raid_id, embed_texts_av, embed_texts_unav):
        try:
            name, tier, time, boss, roster, tag = select_one(self.conn, 'Raids', ['name', 'tier', 'time', 'boss', 'roster', 'tag'],
                                                    ['raid_id'], [raid_id])
        except TypeError:
            logger.info("The raid has been deleted during editing.")
            return
        timestamp = int(time)
        number_of_players = count(self.conn, 'Players', 'player_id', ['raid_id', 'unavailable'], [raid_id, False])

        if tier:
            embed_title = f"{name} {tier}\n<t:{timestamp}:F>"
        else:
            embed_title = f"{name}\n<t:{timestamp}:F>"
        if tag:
            embed_description = f"Tag: {tag}\n\n"
        else:
            embed_description = ""
        if boss:
            embed_description += _("Aim: {0}").format(boss)

        embed = discord.Embed(title=embed_title, colour=discord.Colour(0x3498db), description=embed_description)
        if roster:
            result = select(self.conn, 'Assignment', ['byname, class_name'], ['raid_id'], [raid_id])
            number_of_slots = len(result)
            # Add first half
            embed_name = _("Selected line up:")
            embed_text = ""
            if number_of_slots > 12:
                left_size = number_of_slots // 2
            else:
                left_size = min(number_of_slots, 6)
            for row in result[:left_size]:
                class_names = row[1].split(',')
                for class_name in class_names:
                    embed_text = embed_text + self.emojis_dict[class_name]
                embed_text = embed_text + ": " + row[0] + "\n"
            embed.add_field(name=embed_name, value=embed_text)
            # Add second half
            embed_name = "\u200B"
            embed_text = ""
            for row in result[left_size:]:
                class_names = row[1].split(',')
                for class_name in class_names:
                    embed_text = embed_text + self.emojis_dict[class_name]
                embed_text = embed_text + ": " + row[0] + "\n"
            embed.add_field(name=embed_name, value=embed_text)
            embed.add_field(name="\u200B", value="\u200B")
        # Add a field for each embed text
        for i in range(len(embed_texts_av)):
            if i == 0:
                embed_name = _("The following {0} players are available:").format(number_of_players)
            else:
                embed_name = "\u200B"
            embed.add_field(name=embed_name, value=embed_texts_av[i])
        if len(embed_texts_av) == 1:
            embed.add_field(name="\u200B", value="\u200B")
        if embed_texts_unav:
            number_of_unav_players = count(self.conn, 'Players', 'player_id', ['raid_id', 'unavailable'],
                                           [raid_id, True])
            for i in range(len(embed_texts_unav)):
                if i == 0:
                    embed_name = _("The following {0} players are unavailable:").format(number_of_unav_players)
                else:
                    embed_name = "\u200B"
                embed.add_field(name=embed_name, value=embed_texts_unav[i])
        return embed

    def build_raid_players(self, raid_id, available=True, block_size=6):
        columns = ['raid_id', 'player_id', 'byname']
        if available:
            columns.extend(self.role_names)
            columns.extend(self.creep_names)
        unavailable = not available
        result = select(self.conn, 'Players', columns, ['raid_id', 'unavailable'], [raid_id, unavailable])
        player_strings = []
        if result:
            number_of_players = len(result)
            number_of_fields = ((number_of_players - 1) // block_size) + 1
            # Create the player strings
            for row in result:
                i = 2
                if available:
                    specs = select_one(self.conn, 'Specs', self.role_names, ['player_id'], [row[1]])
                    player_string = row[i] + " "
                    for name in [*self.role_names, *self.creep_names]:
                        i = i + 1
                        if row[i]:
                            spec_str = ""
                            if specs and i < len(self.role_names) + 3:
                                spec = specs[i-3]
                                if spec:
                                    for emoji in ["\U0001F534", "\U0001F535", "\U0001F7E1"]:
                                        if (spec % 2):
                                            spec_str += emoji
                                        spec = spec >> 1
                            player_string += self.emojis_dict[name] + spec_str
                else:
                    player_string = "\u274C " + row[i]
                player_string = player_string + "\n"
                player_strings.append(player_string)
            # Sort the strings by length
            player_strings.sort(key=len, reverse=True)
        else:
            if not available:
                return None
            number_of_players = 0
            number_of_fields = 1
        # Compute number of fields
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
            msg = self.build_raid_players(raid_id, block_size=block_size // 2)
        return msg

    def process_name(self, guild_id, user):
        role_id = select_one(self.conn, 'Settings', ['priority'], ['guild_id'], [guild_id])
        if role_id in [role.id for role in user.roles]:
            byname = "\U0001F46A " + user.display_name
        else:
            if "\U0001F46A" in user.display_name:
                byname = "iMAhACkEr"
            else:
                byname = user.display_name
        return byname

    @tasks.loop(seconds=300)
    async def background_task(self):
        bot = self.bot
        expiry_time = 7200  # Delete raids after 2 hours.
        notify_time = 300  # Notify raiders 5 minutes before.
        current_time = datetime.datetime.now().timestamp()

        cutoff = current_time + notify_time + 1
        raids = select_le(self.conn, 'Raids', ['raid_id', 'channel_id', 'time', 'roster'], ['time'], [cutoff])
        raid_start_msgs = [
            _("Gondor calls for aid! {} will you answer?"),
            _("It's a dangerous business, {}, going out your door."),
            _("I made a promise Mr Frodo. A promise. \"Don't you leave him {}.\""),
            _("This task was appointed to you {}. And if you do not find a way, no one will."),
            _("Let this be the hour when we draw swords together {}."),
            _("A red sun rises. Blood will be spilt this night {}."),
            _("I can't carry it for you, but I can carry you {}."),
            _("Looks like raiding's back on the menu, {}."),
        ]
        for raid in raids:
            raid_id = int(raid[0])
            channel_id = int(raid[1])
            timestamp = int(raid[2])
            roster = int(raid[3])
            channel = bot.get_channel(channel_id)
            if not channel:
                await self.cleanup_old_raid(raid_id, "Raid channel has been deleted.")
                continue
            try:
                post = await channel.fetch_message(raid_id)
            except discord.NotFound:
                await self.cleanup_old_raid(raid_id, "Raid post already deleted.")
            except discord.Forbidden:
                await self.cleanup_old_raid(raid_id, "We are missing required permissions to see raid post.")
            except discord.DiscordServerError:
                logger.warning("Discord server error when fetching the raid message.")
            else:
                if current_time > timestamp + expiry_time:
                    await self.cleanup_old_raid(raid_id, "Deleted expired raid post.")
                    await post.delete()
                elif current_time < timestamp:
                    raid_start_msg = random.choice(raid_start_msgs)
                    players = select(self.conn, 'Assignment', ['player_id'], ['raid_id'], [raid_id])
                    player_ids = ["<@{}>".format(player[0]) for player in players if player[0]]
                    if not player_ids:
                        player_id = select_one(self.conn, 'Raids', ['organizer_id'], ['raid_id'], [raid_id])
                        player_ids = ["<@{}>".format(player_id)]
                    player_msg = " ".join(player_ids)
                    raid_start_msg = raid_start_msg.format(player_msg)
                    raid_start_msg = raid_start_msg + _(" We are forming for the raid now.")
                    try:
                        await channel.send(raid_start_msg, delete_after=notify_time * 2)
                    except discord.Forbidden:
                        logger.warning("Missing permissions to send raid notification to channel {0}".format(channel.id))

        self.conn.commit()
        logger.debug("Completed raid background task.")

    async def cleanup_old_raid(self, raid_id, message):
        logger.info(message)
        guild_id = select_one(self.conn, 'Raids', ['guild_id'], ['raid_id'], [raid_id])
        delete(self.conn, 'Raids', ['raid_id'], [raid_id])
        delete(self.conn, 'Players', ['raid_id'], [raid_id])
        delete(self.conn, 'Assignment', ['raid_id'], [raid_id])
        logger.info("Deleted old raid from database.")
        await self.calendar_cog.update_calendar(guild_id)
        try:
            self.raids.remove(raid_id)
        except ValueError:
            logger.info("Raid already deleted from memory.")
        try:
            del self.update_call[raid_id]
        except KeyError:
            logger.info("Raid cache already deleted from memory.")

    @background_task.before_loop
    async def before_background_task(self):
        await self.bot.wait_until_ready()

    @background_task.error
    async def handle_error(self, exception):
        logger.error("Raid background task failed.")
        logger.error(exception, exc_info=True)


class RaidView(discord.ui.View):
    def __init__(self, raid_cog):
        super().__init__(timeout=None)
        self.raid_cog = raid_cog
        self.conn = raid_cog.conn
        for emoji in raid_cog.class_emojis:
            self.add_item(EmojiButton(emoji))

    @discord.ui.button(emoji="\U0001F6E0\uFE0F", style=discord.ButtonStyle.blurple, custom_id='raid_view:settings')
    async def settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.raid_cog.has_raid_permission(interaction.user, interaction.guild, interaction.message.id):
            perm_msg = _("You do not have permission to change the raid settings.")
            await interaction.response.send_message(perm_msg, ephemeral=True)
            return
        modal = ConfigureModal(self.raid_cog, interaction.message.id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(emoji="\u26CF\uFE0F", style=discord.ButtonStyle.blurple, custom_id='raid_view:select')
    async def select(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.raid_cog.has_raid_permission(interaction.user, interaction.guild, interaction.message.id):
            perm_msg = _("You do not have permission to change the raid settings.")
            await interaction.response.send_message(perm_msg, ephemeral=True)
            return
        raid_id = interaction.message.id
        available = select(self.conn, 'Players', ['player_id, byname'], ['raid_id', 'unavailable'],
                           [raid_id, False])
        if not available:
            msg = _("There are no players to assign for this raid!")
            await interaction.response.send_message(msg, ephemeral=True)
            return
        msg = _("Please first select the player. The roster is updated when a class is selected. "
                "You can select a slot manually or leave it on automatic.\n") \
            + _("(This selection message is ephemeral and will cease to work after 60s without interaction.)")
        view = SelectView(self.raid_cog, raid_id)
        await interaction.response.send_message(msg, view=view, ephemeral=True)
        roster = select_one(self.conn, 'Raids', ['roster'], ['raid_id'], [raid_id])
        if not roster:
            upsert(self.conn, 'Raids', ['roster'], [True], ['raid_id'], [raid_id])
            self.conn.commit()

    @discord.ui.button(emoji="\u274C", style=discord.ButtonStyle.red, custom_id='raid_view:cancel')
    async def red_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.sign_up_cancel(interaction)

    @discord.ui.button(emoji="\u2705", style=discord.ButtonStyle.green, custom_id='raid_view:check')
    async def green_check(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.sign_up_all(interaction)

    async def sign_up_class(self, i, class_name):
        try:
            role = discord.utils.get(i.guild.roles, name=class_name)
            if role is None:
                role = await i.guild.create_role(mentionable=True, name=class_name)
            if role not in i.user.roles:
                await i.user.add_roles(role)
        except discord.Forbidden:
            msg = _("Error: Missing 'Manage roles' permission to assign the class role.")
        else:
            msg = _("Your sign up has been received and the raid post will be updated momentarily.")
        raid_id = i.message.id
        timestamp = int(time.time())
        byname = self.raid_cog.process_name(i.guild.id, i.user)
        sign_up = not select_one(self.conn, 'Players', [class_name], eq_columns=['player_id', 'raid_id'], eq_values=[i.user.id, raid_id])
        if not sign_up:
            sign_ups = select_one(self.conn, 'Players', self.raid_cog.role_names, eq_columns=['player_id', 'raid_id'], eq_values=[i.user.id, raid_id])
            signed_up_classes = sum(filter(None, sign_ups))
            if signed_up_classes == 1:
                await self.sign_up_cancel(i)
                return
        upsert(self.conn, 'Players', ['byname', 'timestamp', 'unavailable', class_name],
               [byname, timestamp, False, sign_up], ['player_id', 'raid_id'], [i.user.id, raid_id])
        self.conn.commit()
        await i.response.send_message(msg, ephemeral=True, delete_after=sign_up_delay)
        await self.raid_cog.update_raid_post(raid_id, i.channel, delay=sign_up_delay)

    async def sign_up_all(self, i):
        raid_id = i.message.id
        role_names = [role.name for role in i.user.roles if role.name in self.raid_cog.role_names]
        if role_names:
            await i.response.defer()
            timestamp = int(time.time())
            columns = ['byname', 'timestamp', 'unavailable']
            columns.extend(role_names)
            byname = self.raid_cog.process_name(i.guild.id, i.user)
            values = [byname, timestamp, False]
            values.extend([True] * len(role_names))
            upsert(self.conn, 'Players', columns, values, ['player_id', 'raid_id'], [i.user.id, raid_id])
            self.conn.commit()
            await self.raid_cog.update_raid_post(raid_id, i.channel, delay=0)
        else:
            err_msg = _("You have not assigned yourself any class roles yet, please sign up with a class first.")
            await i.response.send_message(err_msg, ephemeral=True)

    async def sign_up_cancel(self, i):
        await i.response.defer()
        raid_id = i.message.id
        timestamp = int(time.time())
        assigned_slot = select_one(self.conn, 'Assignment', ['slot_id'], ['player_id', 'raid_id'],
                                   [i.user.id, raid_id])
        if assigned_slot is not None:
            class_name = select_one(self.conn, 'Assignment', ['class_name'], ['player_id', 'raid_id'],
                                    [i.user.id, raid_id])
            error_msg = _("Dearest raid leader, {0} has cancelled their availability. "
                          "Please note they were assigned to {1} in the raid.").format(i.user.mention, class_name)
            await i.channel.send(error_msg)

            tag = select_one(self.conn, 'Raids', ['tag'], ['raid_id'], [raid_id])
            role = discord.utils.get(i.guild.roles, name=tag)
            if role:
                await i.user.remove_roles(role)

            class_names = ','.join(self.raid_cog.slots_class_names[assigned_slot])
            assign_columns = ['player_id', 'byname', 'class_name']
            assign_values = [None, _("<Open>"), class_names]
            upsert(self.conn, 'Assignment', assign_columns, assign_values, ['raid_id', 'slot_id'],
                   [raid_id, assigned_slot])
        r = select_one(self.conn, 'Players', ['byname'], ['player_id', 'raid_id'], [i.user.id, raid_id])
        if r:
            delete(self.conn, 'Players', ['player_id', 'raid_id'], [i.user.id, raid_id])
        else:
            byname = self.raid_cog.process_name(i.guild.id, i.user)
            upsert(self.conn, 'Players', ['byname', 'timestamp', 'unavailable'], [byname, timestamp, True],
                   ['player_id', 'raid_id'], [i.user.id, raid_id])
        self.conn.commit()
        await self.raid_cog.update_raid_post(raid_id, i.channel, delay=0)


class CreepView(discord.ui.View):
    def __init__(self, raid_cog):
        super().__init__(timeout=None)
        self.raid_cog = raid_cog
        self.conn = raid_cog.conn
        # For better visual appearance divide creep classes equally over two rows
        split = len(raid_cog.creep_emojis)//2 - 1
        for emoji in raid_cog.creep_emojis[:split]:
            self.add_item(EmojiButton(emoji, 0))
        for emoji in raid_cog.creep_emojis[split:]:
            self.add_item(EmojiButton(emoji, 1))

    async def sign_up_class(self, i, creep_name):
        raid_id = i.message.id
        timestamp = int(time.time())
        byname = self.raid_cog.process_name(i.guild.id, i.user)
        upsert(self.conn, 'Players', ['byname', 'timestamp', 'unavailable', creep_name],
               [byname, timestamp, False, True], ['player_id', 'raid_id'], [i.user.id, raid_id])
        self.conn.commit()
        msg = _("Your sign up has been received and the raid post will be updated momentarily.")
        await i.response.send_message(msg, ephemeral=True, delete_after=sign_up_delay)
        await self.raid_cog.update_raid_post(raid_id, i.channel, delay=sign_up_delay)

    async def sign_up_cancel(self, i):
        await i.response.defer()
        raid_id = i.message.id
        timestamp = int(time.time())
        r = select_one(self.conn, 'Players', ['byname'], ['player_id', 'raid_id'], [i.user.id, raid_id])
        if r:
            delete(self.conn, 'Players', ['player_id', 'raid_id'], [i.user.id, raid_id])
        else:
            byname = self.raid_cog.process_name(i.guild.id, i.user)
            upsert(self.conn, 'Players', ['byname', 'timestamp', 'unavailable'], [byname, timestamp, True],
                   ['player_id', 'raid_id'], [i.user.id, raid_id])
        self.conn.commit()
        await self.raid_cog.update_raid_post(raid_id, i.channel, delay=0)

    @discord.ui.button(emoji="\U0001F6E0\uFE0F", style=discord.ButtonStyle.blurple, custom_id='creep_view:settings')
    async def settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.raid_cog.has_raid_permission(interaction.user, interaction.guild, interaction.message.id):
            perm_msg = _("You do not have permission to change the raid settings.")
            await interaction.response.send_message(perm_msg, ephemeral=True)
            return
        modal = ConfigureModal(self.raid_cog, interaction.message.id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(emoji="\u274C", style=discord.ButtonStyle.red, custom_id='creep_view:cancel')
    async def red_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.sign_up_cancel(interaction)


class EmojiButton(discord.ui.Button):
    def __init__(self, emoji, row=None):
        super().__init__(emoji=emoji, custom_id=emoji.name, row=row)

    async def callback(self, interaction: discord.Interaction):
        class_name = self.custom_id
        await self.view.sign_up_class(interaction, class_name)


class SelectView(discord.ui.View):
    def __init__(self, raid_cog, raid_id):
        super().__init__(timeout=60)
        self.raid_cog = raid_cog
        self.raid_id = raid_id
        self.conn = raid_cog.conn

        self.slot = -1
        self.player = None
        raid_size = select_one(self.conn, 'Raids', ['size'], ['raid_id'], [self.raid_id])

        self.add_item(SlotSelect(raid_size))
        self.add_item(PlayerSelect(raid_cog.conn, raid_id))
        self.add_item(ClassSelect(raid_cog.class_emojis))

    async def on_timeout(self):
        self.conn.commit()


class SlotSelect(discord.ui.Select):
    def __init__(self, number_of_slots):
        options = [
                discord.SelectOption(label=_("Automatic"), value=-1)
        ]
        for i in range(number_of_slots):
            options.append(discord.SelectOption(label=i+1, value=i))
        super().__init__(placeholder=_("Slot (automatic)"), options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.slot = int(self.values[0])
        await interaction.response.defer()


class PlayerSelect(discord.ui.Select):
    def __init__(self, conn, raid_id):
        available = select(conn, 'Players', ['player_id, byname'], ['raid_id', 'unavailable'], [raid_id, False])
        if len(available) > 25:
            available = available[:25]  # discord API limit is 25 options
        options = []
        for player in available:
            options.append(discord.SelectOption(value=player[0], label=player[1]))
        super().__init__(placeholder=_("Player"), options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.player = self.values[0]
        await interaction.response.defer()


class ClassSelect(discord.ui.Select):
    def __init__(self, class_emojis):
        options = []
        for emoji in class_emojis:
            options.append(discord.SelectOption(label=emoji.name, emoji=emoji))
        options.append(discord.SelectOption(label=_("Remove"), value='remove', emoji="\u274C"))
        super().__init__(placeholder=_("Class"), options=options)

    async def callback(self, interaction: discord.Interaction):
        raid_id = self.view.raid_id
        if self.view.player is None:
            msg = _("Please select a player first.")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        #no members intent so fetch
        member = await interaction.guild.fetch_member(self.view.player)
        tag = select_one(self.view.conn, 'Raids', ['tag'], ['raid_id'], [self.view.raid_id])
        role = discord.utils.get(interaction.guild.roles, name=tag)

        if self.values[0] == 'remove':
            byname = select_one(self.view.conn, 'Players', ['byname'], ['player_id', 'raid_id'],
                            [self.view.player, raid_id])
            self.clear_assignment()
            if role:
                await member.remove_roles(role)
            msg = _("Removed {0} from the selected line up.").format(byname)
            await interaction.response.send_message(msg, ephemeral=True, delete_after=assign_delay)
            await self.view.raid_cog.update_raid_post(raid_id, interaction.channel)
            return

        signup = select_one(self.view.conn, 'Players', [self.values[0], 'byname'], ['player_id', 'raid_id'],
                            [self.view.player, raid_id])
        if not signup[0]:
            msg = _("{0} did not sign up with {1}.").format(signup[1], self.values[0])
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if self.view.slot == -1:
            search = '%' + self.values[0] + '%'
            slot_id = select_one(self.view.conn, 'Assignment', ['slot_id'], ['raid_id'], [raid_id], ['player_id'],
                                 ['class_name'], [search])
            if slot_id is None:
                slot_id = select_one(self.view.conn, 'Assignment', ['slot_id'], ['raid_id'], [raid_id], ['player_id'])
        else:
            slot_id = self.view.slot
        if slot_id is None:
            msg = _("There are no slots available. "
                    "Please select a slot manually to overwrite.")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        player_id = select_one(self.view.conn, 'Assignment', ['player_id'], ['slot_id', 'raid_id'], [slot_id, raid_id])
        if player_id:
            old_member = await interaction.guild.fetch_member(player_id)
            if role:
                await old_member.remove_roles(role)

        self.clear_assignment()
        assignment_columns = ['player_id', 'byname', 'class_name']
        assignment_values = [self.view.player, signup[1], self.values[0]]
        upsert(self.view.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'],
               [raid_id, slot_id])

        msg = _("Assigned {0} to {1}.").format(signup[1], self.values[0])
        await interaction.response.send_message(msg, ephemeral=True, delete_after=assign_delay)

        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                logger.warning("Error: Missing 'Manage roles' permissions for {interaction.guild}.")
        else:
            logger.warning('No role exists for raid {raid_id}.')

        await self.view.raid_cog.update_raid_post(raid_id, interaction.channel)

    def clear_assignment(self):
        slot = select_one(self.view.conn, 'Assignment', ['slot_id', 'byname'], ['player_id', 'raid_id'],
                          [self.view.player, self.view.raid_id])
        if slot is not None:
            assignment_columns = ['player_id', 'byname', 'class_name']
            class_names = ','.join(self.view.raid_cog.slots_class_names[slot[0]])
            assignment_values = [None, _("<Open>"), class_names]
            upsert(self.view.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'],
                   [self.view.raid_id, slot[0]])


class ConfigureModal(discord.ui.Modal):

    def __init__(self, raid_cog, raid_id):
        super().__init__(title='Raid Settings')
        self.raid_cog = raid_cog
        self.calendar_cog = raid_cog.bot.get_cog('CalendarCog')
        self.raid_id = raid_id
        self.conn = raid_cog.conn
        try:
            name, tier, aim, = select_one(self.conn, 'Raids', ['name', 'tier', 'boss'],
                                            ['raid_id'], [raid_id])
        except TypeError:
            logger.info("The raid has been deleted during editing.")
            return
        name_field = discord.ui.TextInput(custom_id='name', label='Name', default=name, max_length=256)
        tier_field = discord.ui.TextInput(custom_id='tier', label='Tier', required=False, default=tier, max_length=8)
        aim_field = discord.ui.TextInput(custom_id='boss', label='Aim', required=False, default=aim, max_length=1024)
        time_field = discord.ui.TextInput(custom_id='time', label='Time', required=False, placeholder=_("Leave blank to keep the existing time."), max_length=64)
        delete_field = discord.ui.TextInput(custom_id='delete', label='Delete', required=False, placeholder=_("Type 'delete' here to delete the raid."), max_length=8)
        self.add_item(name_field)
        self.add_item(tier_field)
        self.add_item(aim_field)
        self.add_item(time_field)
        self.add_item(delete_field)

    async def on_submit(self, interaction: discord.Interaction):
        text_fields = interaction.data['components']
        raid_columns = [field['components'][0]['custom_id'] for field in text_fields]
        raid_values = [field['components'][0]['value'] for field in text_fields]
        # delete parsing
        delete_index = raid_columns.index('delete')
        delete_input = raid_values[delete_index]
        if delete_input.lower() == 'delete':
            await self.delete_raid(interaction)
            self.stop()
            return
        raid_columns.pop(delete_index)
        raid_values.pop(delete_index)
        # default response
        resp_msg = _("The raid settings have been successfully updated! Changes will be reflected momentarily.")
        # time parsing
        time_index = raid_columns.index('time')
        time_input = raid_values[time_index]
        if time_input:
            try:
                timestamp = Time().converter(self.raid_cog.bot, interaction.guild_id, interaction.user.id, time_input)
            except commands.BadArgument:
                resp_msg = _("Failed to parse time argument: ") + time_input
                raid_columns.pop(time_index)
                raid_values.pop(time_index)
            else:
                raid_values[time_index] = timestamp
        else:
            raid_columns.pop(time_index)
            raid_values.pop(time_index)
        # write to database
        upsert(self.conn, 'Raids', raid_columns, raid_values, ['raid_id'], [self.raid_id])
        self.conn.commit()
        # respond
        await interaction.response.send_message(resp_msg, ephemeral=True, delete_after=assign_delay)
        # Update corresponding discord posts and events
        await self.raid_cog.update_raid_post(self.raid_id, interaction.channel)
        await self.calendar_cog.update_calendar(interaction.guild.id)
        await self.calendar_cog.modify_guild_event(interaction.guild, self.raid_id)
        self.stop()

    async def delete_raid(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # Delete the guild event
        await self.calendar_cog.delete_guild_event(interaction.guild, self.raid_id)
        # Delete tag role
        tag = select_one(self.conn, 'Raids', ['tag'], ['raid_id'], [self.raid_id])
        role = discord.utils.get(interaction.guild.roles, name=tag)
        await role.delete()
        # remove from memory first
        await self.raid_cog.cleanup_old_raid(self.raid_id, "Raid deleted via button.")
        # so deletion doesn't trigger another clean up
        post = interaction.channel.get_partial_message(self.raid_id)
        try:
            await post.delete()
        except discord.NotFound:
            pass


async def setup(bot):
    await bot.add_cog(RaidCog(bot))
    logger.info("Loaded Raid Cog.")
