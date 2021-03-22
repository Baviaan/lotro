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
                await message.remove_reaction(payload.emoji, payload.member)

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
            res = upsert(self.conn, 'Settings', ['raid_leader'], [leader_role.id], ['guild_id'], [ctx.guild.id])
            await ctx.send(_("Raid Leader role set to `{0}`.").format(leader_role))
        else:
            if raid_leader:
                await ctx.send(_("No role `{0}` found.").format(raid_leader))
            else:
                res = upsert(self.conn, 'Settings', ['raid_leader'], [None], ['guild_id'], [ctx.guild.id])
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

    @commands.command(aliases=nicknames, help=fast_example, brief=fast_brief, description=fast_description)
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
        custom = False
        try:
            name = self.raid_lookup[name.lower()]
            return name, custom
        except KeyError:
            custom = True
            names = list(self.raid_lookup.values())
            match = get_match(name, names)
            if match[0]:
                return match[0], custom
        return name, custom

    async def raid_command(self, ctx, name, tier, boss, time, roster=False):
        full_name, custom = self.get_raid_name(name)
        command = ctx.invoked_with
        if command in ['raid', 'r,', 'instance'] and not custom:
            tip = _("Consider using `{prefix}{name} ...` instead of `{prefix}{command} {name} ...`.").format(
                prefix=ctx.prefix, name=name, command=command)
            await ctx.send(tip, delete_after=30)
        post = await ctx.send('\u200B')
        raid_id = post.id
        timestamp = int(time.replace(tzinfo=datetime.timezone.utc).timestamp())  # Do not use local tz.
        raid_columns = ['channel_id', 'guild_id', 'organizer_id', 'name', 'tier', 'boss', 'time', 'roster']
        raid_values = [ctx.channel.id, ctx.guild.id, ctx.author.id, full_name, tier, boss, timestamp, roster]
        upsert(self.conn, 'Raids', raid_columns, raid_values, ['raid_id'], [raid_id])
        self.roster_init(raid_id)
        self.conn.commit()
        logger.info("Created new raid: {0} at {1}".format(full_name, time))
        embed = self.build_raid_message(ctx.guild.id, raid_id, "\u200B", None)
        await post.edit(embed=embed)
        await self.emoji_init(ctx.channel, post)
        self.raids.append(raid_id)
        await self.bot.get_cog('CalendarCog').update_calendar(ctx.guild.id)

    def roster_init(self, raid_id):
        available = _("<Open>")
        assignment_columns = ['player_id', 'byname', 'class_name']
        for i in range(len(self.slots_class_names)):
            assignment_values = [None, available, ','.join(self.slots_class_names[i])]
            upsert(self.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'], [raid_id, i])

    async def emoji_init(self, channel, post):
        emojis = ["\U0001F6E0", "\u26CF", "\u274C", "\u2705"]  # Config, pick, cancel, check
        emojis.extend(self.class_emojis)
        try:
            for emoji in emojis:
                await post.add_reaction(emoji)
        except discord.Forbidden:
            await channel.send(_("Error: Missing 'Add Reactions' permission to add reactions to the raid post."))

    async def raid_update(self, payload):
        bot = self.bot
        guild = bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        user = payload.member
        raid_id = payload.message_id
        emoji = payload.emoji
        raid_deleted = False

        if str(emoji) in ["\U0001F6E0", "\u26CF"]:
            organizer_id = select_one(self.conn, 'Raids', ['organizer_id'], ['raid_id'], [raid_id])
            raid_leader_id = select_one(self.conn, 'Settings', ['raid_leader'], ['guild_id'], [guild.id])
            if raid_leader_id:
                raid_leader = guild.get_role(raid_leader_id)
            else:
                raid_leader = None

            operation_allowed = False
            if organizer_id == user.id:
                operation_allowed = True
            elif raid_leader in user.roles:
                operation_allowed = True
            elif user.guild_permissions.administrator:
                operation_allowed = True
            if not operation_allowed:
                error_msg = _("You do not have permission to change the raid settings. "
                              "You need to have the '{0}' role.").format(raid_leader_name)
                await channel.send(error_msg, delete_after=15)
                return
        if str(emoji) == "\u26CF":  # Pick emoji
            roster = select_one(self.conn, 'Raids', ['roster'], ['raid_id'], [raid_id])
            if not roster:
                upsert(self.conn, 'Raids', ['roster'], [True], ['raid_id'], [raid_id])
                await channel.send(_("Enabling roster for this raid."), delete_after=10)
            await self.get_players(user, channel, raid_id)
        elif str(emoji) == "\U0001F6E0":  # Config emoji
            raid_deleted = await self.configure(user, channel, raid_id)
        elif str(emoji) == "\u274C":  # Cancel emoji
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
                upsert(self.conn, 'Players', ['byname', 'unavailable'], [user.display_name, True],
                       ['player_id', 'raid_id'], [user.id, raid_id])
        elif str(emoji) == "\u2705":  # Check mark emoji
            role_names = [role.name for role in user.roles if role.name in self.role_names]
            if role_names:
                columns = ['byname', 'unavailable']
                columns.extend(role_names)
                values = [user.display_name, False]
                values.extend([True] * len(role_names))
                upsert(self.conn, 'Players', columns, values, ['player_id', 'raid_id'], [user.id, raid_id])
            else:
                error_msg = _("{0} you have not assigned yourself any class roles.").format(user.mention)
                await channel.send(error_msg, delete_after=15)
        elif emoji.name in self.role_names:
            upsert(self.conn, 'Players', ['byname', 'unavailable', emoji.name], [user.display_name, False, True],
                   ['player_id', 'raid_id'], [user.id, raid_id])
            try:
                role = await get_role(guild, emoji.name)
                if role not in user.roles:
                    await user.add_roles(role)
            except discord.Forbidden:
                await channel.send(_("Error: Missing 'Manage roles' permission to assign the class role."))
        self.conn.commit()
        if raid_deleted:
            post = channel.get_partial_message(raid_id)
            await post.delete()
            return True
        else:
            await self.update_raid_post(raid_id, channel)
            return

    async def update_raid_post(self, raid_id, channel):
        available = self.build_raid_players(raid_id)
        unavailable = self.build_raid_players(raid_id, available=False)
        embed = self.build_raid_message(channel.guild.id, raid_id, available, unavailable)
        post = channel.get_partial_message(raid_id)
        try:
            await post.edit(embed=embed)
        except discord.HTTPException as e:
            logger.warning(e)
            msg = "\n".join(["The above error occurred sending the following messages as embed:", embed.title, embed.description, str(embed.fields)])
            logger.warning(msg)
            await channel.send(_("That's an error. Check the logs."))

    async def configure(self, user, channel, raid_id):
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
                return True  # The raid has deleted from database.
        self.conn.commit()
        await bot.get_cog('CalendarCog').update_calendar(channel.guild.id, new_run=False)
        return

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
            time = await Time().converter(bot, channel, author.id, response.content)
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

    async def get_players(self, author, channel, raid_id):
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
            extra_msg = await channel.send("\u200b")
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
            slot_id = select_one(self.conn, 'Assignment', ['slot_id'], ['raid_id'], [raid_id], ['player_id'], ['class_name'], [search])
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

        await info_msg.delete()
        await player_msg.delete()
        await class_msg.delete()
        if len(available) > 20:
            await extra_msg.delete()
        return

    def build_raid_message(self, guild_id, raid_id, embed_texts_av, embed_texts_unav):
        timestamp = int(select_one(self.conn, 'Raids', ['time'], ['raid_id'], [raid_id]))
        time = datetime.datetime.utcfromtimestamp(timestamp)
        name, tier, boss, roster = select_one(self.conn, 'Raids', ['name', 'tier', 'boss', 'roster'], ['raid_id'],
                                              [raid_id])
        number_of_players = count(self.conn, 'Players', 'player_id', ['raid_id', 'unavailable'], [raid_id, False])

        time_cog = self.time_cog
        server_tz = time_cog.get_server_time(guild_id)
        server_time = time_cog.local_time(time, server_tz)
        fmt_24hr = time_cog.get_24hr_fmt(guild_id)
        header_time = time_cog.format_time(server_time, fmt_24hr) + _(" server time")

        embed_title = _("{0} on {1}").format(name, header_time)
        if tier:
            embed_title = _("{0} {1} on {2}").format(name, tier, header_time)
        embed_description = ""
        if boss:
            embed_description = _("Aim: {0}").format(boss)

        embed = discord.Embed(title=embed_title, colour=discord.Colour(0x3498db), description=embed_description)
        time_string = self.build_time_string(time, guild_id, fmt_24hr)
        embed.add_field(name=_("Time zones:"), value=time_string)
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
        embed.set_footer(text=_("Raid in your local time (broken on Android)"))
        embed.timestamp = time
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

    def build_time_string(self, time, guild_id, fmt_24hr):
        time_strings = []
        time_cog = self.time_cog
        display_times = time_cog.get_display_times(guild_id)
        for timezone in display_times:
            local_time = time_cog.local_time(time, timezone)
            _, _, city = timezone.partition('/')
            time_strings.append(city.replace('_', ' ') + ": " + time_cog.format_time(local_time, fmt_24hr))
        return "\n".join(time_strings)

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


def setup(bot):
    bot.add_cog(RaidCog(bot))
    logger.info("Loaded Raid Cog.")
