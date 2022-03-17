import asyncio
import csv
import datetime
import discord
from discord.ext import commands
from discord.ext import tasks
import logging
import re
import requests
import time

from database import create_table, count, delete, select, select_le, select_one, upsert
from time_cog import Time
from utils import get_match

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RaidCog(commands.Cog):

    # Load raid (nick)names
    with open('list-of-raids.csv', 'r') as f:
        reader = csv.reader(f)
        raid_lookup = dict(reader)
    nicknames = list(raid_lookup.keys())

    def __init__(self, bot):
        self.bot = bot
        self.conn = bot.conn
        self.role_names = bot.role_names
        self.slots_class_names = bot.slots_class_names
        self.time_cog = bot.get_cog('TimeCog')
        self.calendar_cog = bot.get_cog('CalendarCog')

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

#    @commands.Cog.listener()
#    async def on_raw_message_delete(self, payload):
#        raid_id = payload.message_id
#        if raid_id in self.raids:
#            # Delete the guild event
#            try:
#                self.calendar_cog.delete_guild_event(raid_id)
#            except requests.HTTPError as e:
#                logger.warning(e.response.text)
#            # Handle clean up on bot side
#            await self.cleanup_old_raid(raid_id, "Raid manually deleted.")
#            self.conn.commit()

    def get_raid_name(self, name):
        try:
            name = self.raid_lookup[name.lower()]
        except KeyError:
            names = list(self.raid_lookup.values())
            match = get_match(name, names)
            if match[0]:
                name = match[0]
        return name

    async def post_raid(self, name, tier, boss, timestamp, roster, guild_id, channel, author_id):
        full_name = self.get_raid_name(name)
        raid_time = datetime.datetime.utcfromtimestamp(timestamp)
        # Check if time is in near future. Otherwise parsed date was likely unintended.
        current_time = int(time.time())
        if current_time + 604800 < timestamp:
            error_message = _("Please check the date <@{0}>. You are posting a raid for: {1} UTC.").format(
                author_id, raid_time)
            await channel.send(error_message, delete_after=30)
        post = await channel.send('\u200B')
        raid_id = post.id
        raid_columns = ['channel_id', 'guild_id', 'organizer_id', 'name', 'tier', 'boss', 'time', 'roster']
        raid_values = [channel.id, guild_id, author_id, full_name, tier, boss, timestamp, roster]
        upsert(self.conn, 'Raids', raid_columns, raid_values, ['raid_id'], [raid_id])
        self.roster_init(raid_id)
        embed = self.build_raid_message(raid_id, "\u200B", None)
        await post.edit(embed=embed, view=RaidView(self))
        self.raids.append(raid_id)
        await self.create_guild_event(channel, raid_id)
        self.conn.commit()
        logger.info("Created new raid: {0} at {1} for guild {2}.".format(full_name, raid_time, guild_id))
        await self.calendar_cog.update_calendar(guild_id)

    async def create_guild_event(self, channel, raid_id):
        try:
            event_id = self.calendar_cog.create_guild_event(raid_id)
        except requests.HTTPError as e:
            logger.warning(e.response.text)
            err_msg = _("Failed to create the discord event. Please check the bot has the manage event permission.")
            await channel.send(err_msg, delete_after=20)
        except requests.exceptions.JSONDecodeError as e:
            err_msg = _("Invalid response from Discord.")
            await channel.send(err_msg, delete_after=20)
        else:
            upsert(self.conn, 'Raids', ['event_id'], [event_id], ['raid_id'], [raid_id])

    def roster_init(self, raid_id):
        available = _("<Open>")
        assignment_columns = ['player_id', 'byname', 'class_name']
        for i in range(len(self.slots_class_names)):
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

    def build_raid_message(self, raid_id, embed_texts_av, embed_texts_unav):
        try:
            name, tier, time, boss, roster = select_one(self.conn, 'Raids', ['name', 'tier', 'time', 'boss', 'roster'],
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
        await self.calendar_cog.update_calendar(guild_id, new_run=False)
        try:
            self.raids.remove(raid_id)
        except ValueError:
            logger.info("Raid already deleted from memory.")

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
    async def settings(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self.raid_cog.has_raid_permission(interaction.user, interaction.guild, interaction.message.id):
            perm_msg = _("You do not have permission to change the raid settings.")
            await interaction.response.send_message(perm_msg, ephemeral=True)
            return
        msg = _("Please select the setting to update or delete the raid.\n") \
            + _("(This selection message is ephemeral and will cease to work after 60s without interaction.)")
        modal = ConfigureModal(self.raid_cog, interaction.message.id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(emoji="\u26CF\uFE0F", style=discord.ButtonStyle.blurple, custom_id='raid_view:select')
    async def select(self, button: discord.ui.Button, interaction: discord.Interaction):
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

    @discord.ui.button(emoji="\u274C", style=discord.ButtonStyle.red, custom_id='raid_view:cancel')
    async def red_cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.sign_up_cancel(interaction)

    @discord.ui.button(emoji="\u2705", style=discord.ButtonStyle.green, custom_id='raid_view:check')
    async def green_check(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.sign_up_all(interaction)

    async def sign_up_class(self, i, class_name):
        try:
            role = discord.utils.get(i.guild.roles, name=class_name)
            if role is None:
                role = await i.guild.create_role(mentionable=True, name=class_name)
            if role not in i.user.roles:
                await i.user.add_roles(role)
        except discord.Forbidden:
            err_msg = _("Error: Missing 'Manage roles' permission to assign the class role.")
            await i.response.send_message(err_msg)
        else:
            await i.response.defer()
        raid_id = i.message.id
        timestamp = int(time.time())
        byname = self.process_name(i.guild.id, i.user)
        upsert(self.conn, 'Players', ['byname', 'timestamp', 'unavailable', class_name],
               [byname, timestamp, False, True], ['player_id', 'raid_id'], [i.user.id, raid_id])
        self.conn.commit()
        await self.raid_cog.update_raid_post(raid_id, i.channel)

    async def sign_up_all(self, i):
        raid_id = i.message.id
        role_names = [role.name for role in i.user.roles if role.name in self.raid_cog.role_names]
        if role_names:
            await i.response.defer()
            timestamp = int(time.time())
            columns = ['byname', 'timestamp', 'unavailable']
            columns.extend(role_names)
            byname = self.process_name(i.guild.id, i.user)
            values = [byname, timestamp, False]
            values.extend([True] * len(role_names))
            upsert(self.conn, 'Players', columns, values, ['player_id', 'raid_id'], [i.user.id, raid_id])
            self.conn.commit()
            await self.raid_cog.update_raid_post(raid_id, i.channel)
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
            class_names = ','.join(self.raid_cog.slots_class_names[assigned_slot])
            assign_columns = ['player_id', 'byname', 'class_name']
            assign_values = [None, _("<Open>"), class_names]
            upsert(self.conn, 'Assignment', assign_columns, assign_values, ['raid_id', 'slot_id'],
                   [raid_id, assigned_slot])
        r = select_one(self.conn, 'Players', ['byname'], ['player_id', 'raid_id'], [i.user.id, raid_id])
        if r:
            delete(self.conn, 'Players', ['player_id', 'raid_id'], [i.user.id, raid_id])
        else:
            byname = self.process_name(i.guild.id, i.user)
            upsert(self.conn, 'Players', ['byname', 'timestamp', 'unavailable'], [byname, timestamp, True],
                   ['player_id', 'raid_id'], [i.user.id, raid_id])
        self.conn.commit()
        await self.raid_cog.update_raid_post(raid_id, i.channel)

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


class EmojiButton(discord.ui.Button):
    def __init__(self, emoji):
        super().__init__(emoji=emoji, custom_id=emoji.name)

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

        if self.values[0] == 'remove':
            self.clear_assignment()
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
        else:
            slot_id = self.view.slot
        if slot_id is None:
            msg = _("There are no slots available for the selected class. "
                    "Please select the slot manually or pick a different class.")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        self.clear_assignment()
        assignment_columns = ['player_id', 'byname', 'class_name']
        assignment_values = [self.view.player, signup[1], self.values[0]]
        upsert(self.view.conn, 'Assignment', assignment_columns, assignment_values, ['raid_id', 'slot_id'],
               [raid_id, slot_id])
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


#class TierSelect(discord.ui.Select):
#    def __init__(self):
#        options = [
#                discord.SelectOption(label="1", value="T1"),
#                discord.SelectOption(label="2", value="T2"),
#                discord.SelectOption(label="2c", value="T2c"),
#                discord.SelectOption(label="3", value="T3"),
#                discord.SelectOption(label="4", value="T4"),
#                discord.SelectOption(label="5", value="T5")
#        ]
#        super().__init__(placeholder=_("Tier"), options=options)
#
#    async def callback(self, interaction: discord.Interaction):
#        tier = self.values[0]
#        upsert(self.view.conn, 'Raids', ['tier'], [tier], ['raid_id'], [self.view.raid_id])
#        await self.view.raid_cog.update_raid_post(self.view.raid_id, interaction.channel)
#        await self.view.calendar_cog.update_calendar(interaction.guild.id, new_run=False)
#        try:
#            self.view.calendar_cog.modify_guild_event(self.view.raid_id)
#        except requests.HTTPError as e:
#            logger.warning(e.response.text)


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
        resp_msg = _("The raid settings have been successfully updated!")
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
        await interaction.response.send_message(resp_msg, ephemeral=True)
        # Update corresponding discord posts and events
        await self.raid_cog.update_raid_post(self.raid_id, interaction.channel)
        await self.calendar_cog.update_calendar(interaction.guild.id, new_run=False)
        try:
            self.calendar_cog.modify_guild_event(self.raid_id)
        except requests.HTTPError as e:
            logger.warning(e.response.text)
        self.stop()

    async def delete_raid(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # Delete the guild event
        try:
            self.calendar_cog.delete_guild_event(self.raid_id)
        except requests.HTTPError as e:
            logger.warning(e.response.text)
        # remove from memory first
        await self.raid_cog.cleanup_old_raid(self.raid_id, "Raid deleted via button.")
        # so deletion doesn't trigger another clean up
        post = interaction.channel.get_partial_message(self.raid_id)
        try:
            await post.delete()
        except discord.NotFound:
            pass


def setup(bot):
    bot.add_cog(RaidCog(bot))
    logger.info("Loaded Raid Cog.")
