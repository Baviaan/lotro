import asyncio
import csv
import datetime
import discord
from discord.ext import commands
from discord.ext import tasks
from itertools import compress
import json
import logging
import re
import time
import typing

from database import create_table, count, delete, select, select_le, select_one, upsert
from role_cog import get_role
from time_cog import Time
from utils import alphabet_emojis, get_match

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Tier(commands.Converter):
    async def convert(self, ctx, argument):
        tier = re.match(r'[tT][1-5]', argument)  # match tier argument
        if tier:
            tier = "T{0}".format(tier.group()[1])
        else:
            raise commands.BadArgument(_("Failed to parse tier argument: ") + argument)
        return tier

    @staticmethod
    def converter(argument):
        tier = re.search(r'\d+', argument)  # Filter out non-numbers
        if tier:
            tier = "T{0}".format(tier.group())
        else:
            raise commands.BadArgument(_("Failed to parse tier argument: ") + argument)
        return tier

    @staticmethod
    async def channel_converter(channel):
        tier = re.search(r'\d+', channel.name)  # Filter out non-numbers
        if tier:
            tier = "T{0}".format(tier.group())
        else:
            msg = _("Channel name does not specify tier.\nDefaulting to tier 1.")
            await channel.send(msg, delete_after=10)
            tier = "T1"
        return tier


class RaidCog(commands.Cog):
    with open('config.json', 'r') as f:
        config = json.load(f)

    prefix = config['PREFIX']
    # Line up
    default_lineup = []
    for string in config['LINEUP']:
        bitmask = [int(char) for char in string]
        default_lineup.append(bitmask)
    role_names = config['CLASSES']
    slots_class_names = []
    for bitmask in default_lineup:
        class_names = list(compress(role_names, bitmask))
        slots_class_names.append(class_names)
    # Load raid (nick)names
    with open('list-of-raids.csv', 'r') as f:
        reader = csv.reader(f)
        raid_lookup = dict(reader)
    nicknames = list(raid_lookup.keys())
    event_limit = 10

    def __init__(self, bot):
        self.bot = bot
        self.conn = self.bot.conn
        self.role_names = self.bot.role_names
        self.time_cog = bot.get_cog('TimeCog')

        create_table(self.conn, 'raid')
        create_table(self.conn, 'player')
        create_table(self.conn, 'assign')

        raids = select(self.conn, 'Raids', ['raid_id'])
        self.raids = [raid[0] for raid in raids]
        logger.info("We have loaded {} raids in memory.".format(len(self.raids)))
        # Emojis
        host_guild = bot.get_guild(bot.host_id)
        if not host_guild:
            # Use first guild as host
            host_guild = bot.guilds[0]
        logger.info("Using emoji from {0}.".format(host_guild))
        self.class_emojis = [emoji for emoji in host_guild.emojis if emoji.name in self.role_names]
        self.class_emojis_dict = {emoji.name: str(emoji) for emoji in self.class_emojis}

        # Run background task
        self.background_task.start()

        # Add raid view
        self.bot.add_view(RaidView(self))

    def cog_unload(self):
        self.background_task.cancel()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        channel = self.bot.get_channel(payload.channel_id)
        if payload.message_id in self.raids:
            raid_deleted = await self.raid_update(payload)
            if not raid_deleted:
                message = channel.get_partial_message(payload.message_id)
                try:
                    await message.remove_reaction(payload.emoji, payload.member)
                except discord.NotFound:
                    pass

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        raid_id = payload.message_id
        if raid_id in self.raids:
            await self.cleanup_old_raid(raid_id, "Raid manually deleted.")
            self.conn.commit()

    @commands.command()
    async def leader(self, ctx, *raid_leader):
        """Sets the role to be used as raid leader in this guild."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send(_("You must be an admin to change the raid leader role."))
            return
        raid_leader = " ".join(raid_leader)
        leader_role = discord.utils.get(ctx.guild.roles, name=raid_leader)
        if leader_role:
            upsert(self.conn, 'Settings', ['raid_leader'], [leader_role.id], ['guild_id'], [ctx.guild.id])
            await ctx.send(_("Raid Leader role set to `{0}`.").format(leader_role))
        else:
            if raid_leader:
                await ctx.send(_("No role `{0}` found.").format(raid_leader))
            else:
                upsert(self.conn, 'Settings', ['raid_leader'], [None], ['guild_id'], [ctx.guild.id])
                await ctx.send(_("Raid leader role deleted."))
        self.conn.commit()

    async def check_event_limit(self, channel):
        res = count(self.conn, 'Raids', 'raid_id', ['guild_id'], [channel.guild.id])
        if self.bot.host_id and res >= self.event_limit:  # host_id will not be set for private bots
            msg = _("Due to limited resources you may only post up to {0} concurrent raids.").format(self.event_limit)
            await channel.send(msg)
            return False
        return True

    meet_brief = _("Schedules a meetup.")
    meet_description = _("Schedules a meetup. Day/timezone will default to today/server if not specified. Usage:")
    meet_example = _("Examples:\n{0}meetup scourges Friday 4pm\n{0}meetup \"kin house\" 21:00 UTC").format(prefix)

    @commands.command(aliases=['meet', 'm'], help=meet_example, brief=meet_brief, description=meet_description)
    async def meetup(self, ctx, name, *, time: Time()):
        """Schedules a meetup"""
        if not await self.check_event_limit(ctx.channel):
            return
        await self.raid_command(ctx, name, "", "", time)

    raid_brief = _("Schedules a raid.")
    raid_description = _("Schedules a raid. Day/timezone will default to today/server if not specified. Usage:")
    raid_example = _("Examples:\n{0}raid Anvil Friday 4pm\n{0}raid throne t3 21:00 UTC").format(prefix)

    @commands.command(aliases=['instance', 'r'], help=raid_example, brief=raid_brief, description=raid_description)
    async def raid(self, ctx, name, tier: typing.Optional[Tier], *, time: Time()):
        """Schedules a raid"""
        if not await self.check_event_limit(ctx.channel):
            return
        if tier is None:
            tier = await Tier.channel_converter(ctx.channel)
        await self.raid_command(ctx, name, tier, "", time)

    fast_brief = _("Shortcut to schedule a raid (use the aliases).")
    fast_description = _("Schedules a raid with the name of the command. "
                         "Day/timezone will default to today/server if not specified. Usage:")
    fast_example = _("Examples:\n{0}anvil Friday 4pm\n{0}anvil 21:00 UTC").format(prefix)

    @commands.command(aliases=nicknames[:-1], help=fast_example, brief=fast_brief, description=fast_description)
    async def aliasraid(self, ctx, tier: typing.Optional[Tier], *, time: Time()):
        """Shortcut to schedule a raid"""
        if not await self.check_event_limit(ctx.channel):
            return
        name = ctx.invoked_with
        if name == "aliasraid":
            name = _("unknown raid")
        if tier is None:
            tier = await Tier.channel_converter(ctx.channel)
        if '1' in tier or '2' in tier:
            roster = False
        else:
            roster = True
        await self.raid_command(ctx, name, tier, "", time, roster=roster)

    def get_raid_name(self, name):
        try:
            name = self.raid_lookup[name.lower()]
        except KeyError:
            names = list(self.raid_lookup.values())
            match = get_match(name, names)
            if match[0]:
                name = match[0]
        return name

    async def raid_command(self, ctx, name, tier, boss, time, roster=False):
        await self.post_raid(name, tier, boss, time, roster, ctx.guild.id, ctx.channel, ctx.author.id)

    async def post_raid(self, name, tier, boss, time, roster, guild_id, channel, author_id):
        full_name = self.get_raid_name(name)
        # Check if time is in near future. Otherwise parsed date was likely unintended.
        current_time = datetime.datetime.utcnow()
        delta_time = datetime.timedelta(days=7)
        if current_time + delta_time < time:
            error_message = _("Please check the date <@{0}>. You are posting a raid for: {1} UTC.").format(
                author_id, time)
            await channel.send(error_message, delete_after=30)
        post = await channel.send('\u200B')
        raid_id = post.id
        timestamp = int(time.replace(tzinfo=datetime.timezone.utc).timestamp())  # Do not use local tz.
        raid_columns = ['channel_id', 'guild_id', 'organizer_id', 'name', 'tier', 'boss', 'time', 'roster']
        raid_values = [channel.id, guild_id, author_id, full_name, tier, boss, timestamp, roster]
        upsert(self.conn, 'Raids', raid_columns, raid_values, ['raid_id'], [raid_id])
        self.roster_init(raid_id)
        self.conn.commit()
        logger.info("Created new raid: {0} at {1}".format(full_name, time))
        embed = self.build_raid_message(raid_id, "\u200B", None)
        await post.edit(embed=embed, view=RaidView(self))
        #await post.edit(embed=embed)
        #await self.emoji_init(channel, post)
        self.raids.append(raid_id)
        await self.bot.get_cog('CalendarCog').update_calendar(guild_id)

    def roster_init(self, raid_id):
        available = _("<Open>")
        assignment_columns = ['player_id', 'byname', 'class_name']
        for i in range(len(self.slots_class_names)):
            assignment_values = [None, available, ','.join(self.slots_class_names[i])]
            upsert(self.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'], [raid_id, i])

    async def emoji_init(self, channel, post):
        emojis = ["\U0001F6E0\uFE0F", "\u26CF\uFE0F", "\u274C", "\u2705"]  # Config, pick, cancel, check
        emojis.extend(self.class_emojis)
        try:
            for emoji in emojis:
                await post.add_reaction(emoji)
        except discord.Forbidden:
            await channel.send(_("Error: Missing 'Add Reactions' permission to add reactions to the raid post."))

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


    async def raid_update(self, payload):
        bot = self.bot
        guild = bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        user = payload.member
        raid_id = payload.message_id
        emoji = payload.emoji

        if str(emoji) in ["\u26CF", "\u26CF\uFE0F"]:  # Pick emoji
            await self.get_players(guild, channel, raid_id, user)
        elif str(emoji) in ["\U0001F6E0", "\U0001F6E0\uFE0F"]:  # Config emoji
            return await self.configure(guild, channel, raid_id, user)
        elif str(emoji) == "\u274C":  # Cancel emoji
            await self.sign_up_cancel(guild, channel, raid_id, user)
        elif str(emoji) == "\u2705":  # Check mark emoji
            await self.sign_up_all(guild, channel, raid_id, user)
        elif emoji.name in self.role_names:
            await self.sign_up_class(guild, channel, raid_id, user, emoji.name)

    async def sign_up_class(self, guild, channel, raid_id, user, class_name):
        timestamp = int(time.time())
        byname = self.process_name(guild.id, user)
        upsert(self.conn, 'Players', ['byname', 'timestamp', 'unavailable', class_name],
               [byname, timestamp, False, True], ['player_id', 'raid_id'], [user.id, raid_id])
        try:
            role = await get_role(guild, class_name)
            if role not in user.roles:
                await user.add_roles(role)
        except discord.Forbidden:
            await channel.send(_("Error: Missing 'Manage roles' permission to assign the class role."))
        self.conn.commit()
        await self.update_raid_post(raid_id, channel)

    async def sign_up_all(self, guild, channel, raid_id, user):
        role_names = [role.name for role in user.roles if role.name in self.role_names]
        if role_names:
            timestamp = int(time.time())
            columns = ['byname', 'timestamp', 'unavailable']
            columns.extend(role_names)
            byname = self.process_name(guild.id, user)
            values = [byname, timestamp, False]
            values.extend([True] * len(role_names))
            upsert(self.conn, 'Players', columns, values, ['player_id', 'raid_id'], [user.id, raid_id])
            self.conn.commit()
            await self.update_raid_post(raid_id, channel)
        else:
            error_msg = _("{0} you have not assigned yourself any class roles.").format(user.mention)
            await channel.send(error_msg, delete_after=15)

    async def sign_up_cancel(self, guild, channel, raid_id, user):
        timestamp = int(time.time())
        assigned_slot = select_one(self.conn, 'Assignment', ['slot_id'], ['player_id', 'raid_id'],
                                   [user.id, raid_id])
        if assigned_slot is not None:
            class_name = select_one(self.conn, 'Assignment', ['class_name'], ['player_id', 'raid_id'],
                                    [user.id, raid_id])
            error_msg = _("Dearest raid leader, {0} has cancelled their availability. "
                          "Please note they were assigned to {1} in the raid.").format(user.mention, class_name)
            await channel.send(error_msg)
            class_names = ','.join(self.slots_class_names[assigned_slot])
            assign_columns = ['player_id', 'byname', 'class_name']
            assign_values = [None, _("<Open>"), class_names]
            upsert(self.conn, 'Assignment', assign_columns, assign_values, ['raid_id', 'slot_id'],
                   [raid_id, assigned_slot])
        r = select_one(self.conn, 'Players', ['byname'], ['player_id', 'raid_id'], [user.id, raid_id])
        if r:
            delete(self.conn, 'Players', ['player_id', 'raid_id'], [user.id, raid_id])
        else:
            byname = self.process_name(guild.id, user)
            upsert(self.conn, 'Players', ['byname', 'timestamp', 'unavailable'], [byname, timestamp, True],
                   ['player_id', 'raid_id'], [user.id, raid_id])
        self.conn.commit()
        await self.update_raid_post(raid_id, channel)

    async def update_raid_post(self, raid_id, channel):
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

    async def configure(self, guild, channel, raid_id, user):
        if not await self.has_raid_permission(user, guild, raid_id, channel):
            return

        bot = self.bot

        def check(msg):
            return user == msg.author

        text = _("Please respond with 'a(im)', 'd(ate)', 'r(oster)' or 't(ier)' to indicate which setting you wish to "
                 "update for this raid.\nType 'cancel' to cancel the raid.")
        msg = await channel.send(text)
        try:
            reply = await bot.wait_for('message', timeout=20, check=check)
        except asyncio.TimeoutError:
            await msg.delete()
            await channel.send(_("Configuration finished!"), delete_after=10)
            return
        else:
            await msg.delete()
            await reply.delete()
            raid_deleted = False
            if reply.content.lower().startswith(_("r")):
                await self.roster_configure(user, channel, raid_id)
            elif reply.content.lower().startswith(_("d")):
                await self.time_configure(user, channel, raid_id)
            elif reply.content.lower().startswith(_("a")):  # Boss renamed to aim in UI
                await self.boss_configure(user, channel, raid_id)
            elif reply.content.lower().startswith(_("t")):
                await self.tier_configure(user, channel, raid_id)
            elif reply.content.lower().startswith(_("cancel")):
                await self.cleanup_old_raid(raid_id, "Raid manually deleted.")
                raid_deleted = True
        self.conn.commit()
        await bot.get_cog('CalendarCog').update_calendar(channel.guild.id, new_run=False)
        if raid_deleted:
            post = channel.get_partial_message(raid_id)
            await post.delete()
            return True  # The raid has deleted from database.
        else:
            await self.update_raid_post(raid_id, channel)

    async def boss_configure(self, author, channel, raid_id):
        bot = self.bot

        def check(msg):
            return author == msg.author

        msg = await channel.send(_("Please specify the new aim."))
        try:
            response = await bot.wait_for('message', check=check, timeout=30)
        except asyncio.TimeoutError:
            return
        else:
            await response.delete()
        finally:
            await msg.delete()
        boss = response.content
        char_limit = 255
        if len(boss) > char_limit:
            await channel.send(_("Please use less than {0} characters.").format(char_limit), delete_after=20)
            return
        upsert(self.conn, 'Raids', ['boss'], [boss], ['raid_id'], [raid_id])
        return

    async def time_configure(self, author, channel, raid_id):
        bot = self.bot

        def check(msg):
            return author == msg.author

        msg = await channel.send(_("Please specify the new raid time."))
        try:
            response = await bot.wait_for('message', check=check, timeout=30)
        except asyncio.TimeoutError:
            return
        else:
            await response.delete()
        finally:
            await msg.delete()
        try:
            time = await Time().converter(bot, channel.guild.id, author.id, response.content)
        except commands.BadArgument:
            error_msg = _("Failed to parse time argument: ") + response.content
            await channel.send(error_msg, delete_after=20)
        else:
            timestamp = int(time.replace(tzinfo=datetime.timezone.utc).timestamp())  # Do not use local tz.
            upsert(self.conn, 'Raids', ['time'], [timestamp], ['raid_id'], [raid_id])
        return

    async def tier_configure(self, author, channel, raid_id):
        bot = self.bot

        def check(msg):
            return author == msg.author

        msg = await channel.send(_("Please specify the new raid tier."))
        try:
            response = await bot.wait_for('message', check=check, timeout=30)
        except asyncio.TimeoutError:
            return
        else:
            await response.delete()
        finally:
            await msg.delete()
        try:
            tier = Tier.converter(response.content)
        except commands.BadArgument:
            error_msg = _("Failed to parse tier argument: ") + response.content
            await channel.send(error_msg, delete_after=20)
        else:
            upsert(self.conn, 'Raids', ['tier'], [tier], ['raid_id'], [raid_id])
        return

    async def roster_configure(self, author, channel, raid_id):
        bot = self.bot
        roster = select_one(self.conn, 'Raids', ['roster'], ['raid_id'], [raid_id])

        def check(msg):
            return author == msg.author

        text = _("Please respond with 'yes/no' to indicate whether you want to use the roster for this raid.")
        msg = await channel.send(text)
        try:
            reply = await bot.wait_for('message', timeout=20, check=check)
        except asyncio.TimeoutError:
            await channel.send(_("Roster configuration finished!"), delete_after=10)
            return
        else:
            await reply.delete()
            if reply.content.lower().startswith(_("n")):
                if roster:
                    upsert(self.conn, 'Raids', ['roster'], [False], ['raid_id'], [raid_id])
                    await channel.send(_("Roster disabled for this raid.\nRoster configuration finished!"),
                                       delete_after=10)
                return
            elif not reply.content.lower().startswith(_("y")):
                await channel.send(_("Roster configuration finished!"), delete_after=10)
                return
        finally:
            await msg.delete()
        if not roster:
            upsert(self.conn, 'Raids', ['roster'], [True], ['raid_id'], [raid_id])
            await channel.send(_("Roster enabled for this raid."), delete_after=10)
        await self.roster_overwrite(author, channel, raid_id)

    async def roster_overwrite(self, author, channel, raid_id):
        bot = self.bot

        def check(msg):
            return author == msg.author

        text = _("Send a message with the slot number and the class to change a default slot to something else.\n"
                 "Example: `1 captain`\nConfiguration will finish after 20s of no interaction. ")
        msg = await channel.send(text)
        while True:
            try:
                reply = await bot.wait_for('message', timeout=20, check=check)
            except asyncio.TimeoutError:
                await channel.send(_("Roster configuration finished!"), delete_after=10)
                break
            else:
                await reply.delete()
                if reply.content[0].isdigit():
                    index = int(reply.content[0])
                    if index == 1:
                        if reply.content[1].isdigit():
                            index = int(reply.content[0:2])
                    if index <= 0 or index > len(self.slots_class_names):
                        await channel.send(_("No valid slot provided!"), delete_after=10)
                        continue
                else:
                    await channel.send(_("No slot provided!"), delete_after=10)
                    continue
                new_classes = []
                for name in self.role_names:
                    if name.lower() in reply.content.lower():
                        new_classes.append(name)
                if new_classes:
                    if len(new_classes) > 3:
                        await channel.send(_("You may only provide up to 3 classes per slot."), delete_after=10)
                        continue  # allow maximum of 3 classes
                    available = _("<Open>")
                    assignment_columns = ['player_id', 'byname', 'class_name']
                    assignment_values = [None, available, ','.join(new_classes)]
                    upsert(self.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'],
                           [raid_id, index - 1])
                    await channel.send(_("Classes for slot {0} updated!").format(index), delete_after=10)
        await msg.delete()

    async def get_players(self, guild, channel, raid_id, author):
        if not await self.has_raid_permission(author, guild, raid_id, channel):
            return
        roster = select_one(self.conn, 'Raids', ['roster'], ['raid_id'], [raid_id])
        if not roster:
            upsert(self.conn, 'Raids', ['roster'], [True], ['raid_id'], [raid_id])
            await channel.send(_("Enabling roster for this raid."), delete_after=10)

        bot = self.bot

        def check(reaction, user):
            return user == author

        timeout = 60
        reactions = alphabet_emojis()
        reaction_limit = len(reactions)

        players = select(self.conn, 'Assignment', ['player_id'], ['raid_id'], [raid_id])
        assigned_ids = [player[0] for player in players if player[0] is not None]
        available = select(self.conn, 'Players', ['player_id, byname'], ['raid_id', 'unavailable'], [raid_id, False])
        default_name = _("<Open>")

        if not available:
            await channel.send(_("There are no players to assign for this raid!"), delete_after=10)
            return
        if len(available) > reaction_limit:
            available = available[:reaction_limit]  # This only works for the first 36 players.
            await channel.send(_("**Warning**: Excluding some noobs from available players!"), delete_after=15)
        msg_content = _("Please select the player you want to assign a spot in the raid from the list below using the "
                        "corresponding reaction. Assignment will finish after {0}s of no interaction.").format(timeout)
        info_msg = await channel.send(msg_content)

        msg_content = _("Available players:\n*Please wait... Loading*")
        player_msg = await channel.send(msg_content)
        number_of_choices = min(len(available), 20)
        for reaction in reactions[:number_of_choices]:
            await player_msg.add_reaction(reaction)
        if len(available) > 20:
            extra_msg = await channel.send("\u200B")
            for reaction in reactions[number_of_choices:len(available)]:
                await extra_msg.add_reaction(reaction)
        class_msg_content = _("Select the class for this player.")
        class_msg = await channel.send(class_msg_content)
        for reaction in self.class_emojis:
            await class_msg.add_reaction(reaction)

        while True:
            # Update player msg
            msg_content = _("Available players:\n")
            counter = 0
            for player in available:
                if player[0] in assigned_ids:
                    msg_content = msg_content + str(reactions[counter]) + " ~~" + player[1] + "~~\n"
                else:
                    msg_content = msg_content + str(reactions[counter]) + " " + player[1] + "\n"
                counter = counter + 1
            await player_msg.edit(content=msg_content)
            # Get player
            try:
                (reaction, user) = await bot.wait_for('reaction_add', timeout=timeout, check=check)
            except asyncio.TimeoutError:
                await channel.send(_("Player assignment finished!"), delete_after=10)
                break
            else:
                try:
                    index = reactions.index(reaction.emoji)
                except ValueError:
                    await class_msg.remove_reaction(reaction, user)
                    await channel.send(_("Please select a player first!"), delete_after=10)
                    continue
                else:
                    if index < 20:
                        await player_msg.remove_reaction(reaction, user)
                    else:
                        await extra_msg.remove_reaction(reaction, user)
                    selected_player = available[index]
                    slot = select_one(self.conn, 'Assignment', ['slot_id'], ['player_id', 'raid_id'],
                                      [selected_player[0], raid_id])
                    if slot is not None:
                        # Player already assigned a slot, remove player and reset slot.
                        class_names = ','.join(self.slots_class_names[slot])
                        assignment_columns = ['player_id', 'byname', 'class_name']
                        assignment_values = [None, default_name, class_names]
                        upsert(self.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'],
                               [raid_id, slot])
                        assigned_ids.remove(selected_player[0])
                        text = _("Removed {0} from the line up!").format(selected_player[1])
                        await channel.send(text, delete_after=10)
                        await self.update_raid_post(raid_id, channel)
                        continue
            # Get class
            try:
                (reaction, user) = await bot.wait_for('reaction_add', timeout=timeout, check=check)
            except asyncio.TimeoutError:
                await channel.send(_("Player assignment finished!"), delete_after=10)
                break
            else:
                if reaction.emoji in self.class_emojis:
                    await class_msg.remove_reaction(reaction, user)
                    signup = select_one(self.conn, 'Players', [reaction.emoji.name], ['player_id', 'raid_id'],
                                        [selected_player[0], raid_id])
                    if not signup:
                        text = _("{0} did not sign up with {1}!").format(selected_player[1], str(reaction.emoji))
                        await channel.send(text, delete_after=10)
                        continue
                else:
                    await player_msg.remove_reaction(reaction, user)
                    await channel.send(_("That is not a class, please start over!"), delete_after=10)
                    continue
            # Check for free slot
            search = '%' + reaction.emoji.name + '%'
            slot_id = select_one(self.conn, 'Assignment', ['slot_id'], ['raid_id'], [raid_id], ['player_id'],
                                 ['class_name'], [search])
            if slot_id is None:
                await channel.send(_("There are no slots available for the selected class."), delete_after=10)
            else:
                assignment_columns = ['player_id', 'byname', 'class_name']
                assignment_values = list(selected_player)
                assignment_values.append(reaction.emoji.name)
                upsert(self.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'],
                       [raid_id, slot_id])
                assigned_ids.append(selected_player[0])
                msg_content = _("Assigned {0} to {1}.").format(selected_player[1], str(reaction.emoji))
                await channel.send(msg_content, delete_after=10)
                await self.update_raid_post(raid_id, channel)

        try:
            await info_msg.delete()
            await player_msg.delete()
            await class_msg.delete()
        except discord.NotFound:
            pass
        if len(available) > 20:
            await extra_msg.delete()
        self.conn.commit()
        return

    def build_raid_message(self, raid_id, embed_texts_av, embed_texts_unav):
        name, tier, time, boss, roster = select_one(self.conn, 'Raids', ['name', 'tier', 'time', 'boss', 'roster'],
                                                    ['raid_id'], [raid_id])
        try:
            timestamp = int(time)
        except TypeError:
            logger.info("The raid has been deleted during editing.")
            return
        number_of_players = count(self.conn, 'Players', 'player_id', ['raid_id', 'unavailable'], [raid_id, False])

        if tier:
            embed_title = f"{name} {tier}\n<t:{timestamp}:F>"
        else:
            embed_title = f"{name}\n<t:{timestamp}:F>"
        if boss:
            embed_description = _("Aim: {0}").format(boss)
        else:
            embed_description = ""

        embed = discord.Embed(title=embed_title, colour=discord.Colour(0x3498db), description=embed_description)
        if roster:
            result = select(self.conn, 'Assignment', ['byname, class_name'], ['raid_id'], [raid_id])
            number_of_slots = len(result)
            # Add first half
            embed_name = _("Selected line up:")
            embed_text = ""
            for row in result[:number_of_slots // 2]:
                class_names = row[1].split(',')
                for class_name in class_names:
                    embed_text = embed_text + self.class_emojis_dict[class_name]
                embed_text = embed_text + ": " + row[0] + "\n"
            embed.add_field(name=embed_name, value=embed_text)
            # Add second half
            embed_name = "\u200B"
            embed_text = ""
            for row in result[number_of_slots // 2:]:
                class_names = row[1].split(',')
                for class_name in class_names:
                    embed_text = embed_text + self.class_emojis_dict[class_name]
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
        unavailable = (int(available) + 1) % 2
        result = select(self.conn, 'Players', columns, ['raid_id', 'unavailable'], [raid_id, unavailable])
        player_strings = []
        if result:
            number_of_players = len(result)
            number_of_fields = ((number_of_players - 1) // block_size) + 1
            # Create the player strings
            for row in result:
                i = 2
                if available:
                    player_string = row[i] + " "
                    for name in self.role_names:
                        i = i + 1
                        if row[i]:
                            player_string = player_string + self.class_emojis_dict[name]
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

    @tasks.loop(seconds=300)
    async def background_task(self):
        bot = self.bot
        expiry_time = 7200  # Delete raids after 2 hours.
        notify_time = 300  # Notify raiders 5 minutes before.
        current_time = datetime.datetime.now().timestamp()

        cutoff = current_time + 2 * notify_time
        raids = select_le(self.conn, 'Raids', ['raid_id', 'channel_id', 'time', 'roster'], ['time'], [cutoff])
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
            else:
                if current_time > timestamp + expiry_time:
                    await self.cleanup_old_raid(raid_id, "Deleted expired raid post.")
                    await post.delete()
                elif current_time < timestamp - notify_time:
                    raid_start_msg = _("Gondor calls for aid! Will you answer the call")
                    if roster:
                        players = select(self.conn, 'Assignment', ['player_id'], ['raid_id'], [raid_id])
                        player_msg = " ".join(["<@{0}>".format(player[0]) for player in players if player[0]])
                        raid_start_msg = " ".join([raid_start_msg, player_msg])
                    raid_start_msg = raid_start_msg + _("? We are forming for the raid now.")
                    await channel.send(raid_start_msg, delete_after=notify_time * 2)
        self.conn.commit()
        logger.info("Completed background task.")

    async def cleanup_old_raid(self, raid_id, message):
        logger.info(message)
        guild_id = select_one(self.conn, 'Raids', ['guild_id'], ['raid_id'], [raid_id])
        delete(self.conn, 'Raids', ['raid_id'], [raid_id])
        delete(self.conn, 'Players', ['raid_id'], [raid_id])
        delete(self.conn, 'Assignment', ['raid_id'], [raid_id])
        logger.info("Deleted old raid from database.")
        await self.bot.get_cog('CalendarCog').update_calendar(guild_id, new_run=False)
        try:
            self.raids.remove(raid_id)
        except ValueError:
            logger.info("Raid already deleted from memory.")

    @background_task.before_loop
    async def before_background_task(self):
        await self.bot.wait_until_ready()

    @background_task.error
    async def handle_error(self, exception):
        logger.error(exception)


class RaidView(discord.ui.View):
    def __init__(self, raid_cog):
        super().__init__(timeout=None)
        self.raid_cog = raid_cog
        for emoji in raid_cog.class_emojis:
            self.add_item(EmojiButton(emoji, raid_cog.sign_up_class))

    @discord.ui.button(emoji="\U0001F6E0\uFE0F", style=discord.ButtonStyle.blurple, custom_id='raid_view:settings')
    async def settings(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self.raid_cog.has_raid_permission(interaction.user, interaction.guild, interaction.message.id):
            perm_msg = _("You do not have permission to change the raid settings.")
            await interaction.response.send_message(perm_msg, ephemeral=True)
            return
        await interaction.response.defer()
        await self.raid_cog.configure(interaction.guild, interaction.channel, interaction.message.id, interaction.user)

    @discord.ui.button(emoji="\u26CF\uFE0F", style=discord.ButtonStyle.blurple, custom_id='raid_view:select')
    async def select(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self.raid_cog.has_raid_permission(interaction.user, interaction.guild, interaction.message.id):
            perm_msg = _("You do not have permission to change the raid settings.")
            await interaction.response.send_message(perm_msg, ephemeral=True)
            return
        raid_id = interaction.message.id
        available = select(self.raid_cog.conn, 'Players', ['player_id, byname'], ['raid_id', 'unavailable'], [raid_id, False])
        if not available:
            msg = _("There are no players to assign for this raid!")
            await interaction.response.send_message(msg, ephemeral=True)
            return
        msg = _("Please first select the player. The roster is updated when a class is selected. You can select a slot manually or leave it on automatic. (This selection message is ephemeral and will cease to work after 60s without interaction.)")
        view = SelectView(self.raid_cog, raid_id)
        await interaction.response.send_message(msg, view=view, ephemeral=True)
        roster = select_one(self.raid_cog.conn, 'Raids', ['roster'], ['raid_id'], [raid_id])
        if not roster:
            upsert(self.raid_cog.conn, 'Raids', ['roster'], [True], ['raid_id'], [raid_id])

    @discord.ui.button(emoji="\u274C", style=discord.ButtonStyle.red, custom_id='raid_view:cancel')
    async def red_cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.raid_cog.sign_up_cancel(interaction.guild, interaction.channel, interaction.message.id, interaction.user)

    @discord.ui.button(emoji="\u2705", style=discord.ButtonStyle.green, custom_id='raid_view:check')
    async def green_check(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.raid_cog.sign_up_all(interaction.guild, interaction.channel, interaction.message.id, interaction.user)

    @discord.ui.button(label="\U0001D4D1", custom_id='raid_view:brawler')
    async def brawler(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_message("You will have to wait for this...", ephemeral=True)


class EmojiButton(discord.ui.Button):
    def __init__(self, emoji, sign_up_class):
        super().__init__(emoji=emoji, custom_id=emoji.name)
        self.sign_up_class = sign_up_class

    async def callback(self, interaction: discord.Interaction):
        class_name = self.custom_id
        await self.sign_up_class(interaction.guild, interaction.channel, interaction.message.id, interaction.user, class_name)


class SelectView(discord.ui.View):
    def __init__(self, raid_cog, raid_id):
        super().__init__(timeout=20)
        self.raid_cog = raid_cog
        self.raid_id = raid_id
        self.conn = raid_cog.conn

        self.slot = -1
        self.player = None

        self.add_item(SlotSelect(len(raid_cog.slots_class_names)))
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

        slot = select_one(self.view.conn, 'Assignment', ['slot_id', 'byname'], ['player_id', 'raid_id'], [self.view.player, raid_id])
        if slot is not None:
            assignment_columns = ['player_id', 'byname', 'class_name']
            class_names = ','.join(self.view.raid_cog.slots_class_names[slot[0]])
            assignment_values = [None, _("<Open>"), class_names]
            upsert(self.view.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'], [raid_id, slot[0]])
            await self.view.raid_cog.update_raid_post(raid_id, interaction.channel)

        if self.values[0] == 'remove':
            return

        signup = select_one(self.view.conn, 'Players', [self.values[0], 'byname'], ['player_id', 'raid_id'], [self.view.player, raid_id])
        if not signup[0]:
            msg = _("{0} did not sign up with {1}.").format(signup[1], self.values[0])
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if self.view.slot == -1:
            search = '%' + self.values[0] + '%'
            slot_id = select_one(self.view.conn, 'Assignment', ['slot_id'], ['raid_id'], [raid_id], ['player_id'], ['class_name'], [search])
        else:
            slot_id = self.view.slot
        if slot_id is None:
            msg =_("There are no slots available for the selected class. Please select the slot manually or pick a different class.")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        assignment_columns = ['player_id', 'byname', 'class_name']
        assignment_values = [self.view.player, signup[1], self.values[0]]
        upsert(self.view.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'], [raid_id, slot_id])
        await self.view.raid_cog.update_raid_post(raid_id, interaction.channel)


def setup(bot):
    bot.add_cog(RaidCog(bot))
    logger.info("Loaded Raid Cog.")
