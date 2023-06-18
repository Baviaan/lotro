from datetime import datetime
import discord
from discord.ext import commands
from itertools import compress
import gettext
import json
import locale
import logging
import os
import re

from database import create_connection, create_table, increment, read_config_key, select, upsert


class Bot(commands.Bot):

    def __init__(self):
        self.launch_time = datetime.utcnow()

        version = ""
        with open('__init__.py') as f:
            regex = r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]'
            version = re.search(regex, f.read(), re.MULTILINE).group(1)
        self.version = version

        logfile = 'raid_bot.log'
        logging.basicConfig(filename=logfile, level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        self.logger = logger

        self.logger.info("Running version " + self.version)

        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
        except FileNotFoundError:
            logger.warning(f"No config file found. Please create the file 'config.json', see GitHub for an example.")

        self.token = read_config_key(config, 'BOT_TOKEN', True)
        self.server_tz = read_config_key(config, 'SERVER_TZ', True)
        role_names = read_config_key(config, 'CLASSES', True)
        self.role_names = tuple(role_names)
        self.creep_names = read_config_key(config, 'CREEPS', False)
        # Line up
        lineup = read_config_key(config, 'LINEUP', True)
        default_lineup = []
        for string in lineup:
            bitmask = [int(char) for char in string]
            default_lineup.append(bitmask)
        slots_class_names = []
        for bitmask in default_lineup:
            class_names = list(compress(role_names, bitmask))
            slots_class_names.append(class_names)
        self.slots_class_names = slots_class_names

        # Get id for discord server hosting custom emoji.
        host_id = read_config_key(config, 'HOST', False)
        if host_id:
            self.host_id = int(host_id)
        else:
            self.host_id = None

        # Check for twitter auth
        self.twitter_token = read_config_key(config, 'TWITTER_TOKEN', False)
        self.twitter_id = read_config_key(config, 'TWITTER_ID', False)

        language = read_config_key(config, 'LANGUAGE', False)
        if language == 'fr':
            locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
        localization = gettext.translation('messages', localedir='locale', languages=[language], fallback=True)
        if language == 'en' or hasattr(localization, '_catalog'):  # Technically 'en' has no file.
            logger.info("Using language file for '{0}'.".format(language))
        else:
            logger.warning("Language file '{0}' not found. Defaulting to English.".format(language))
        localization.install()

        conn = create_connection('raid_db')
        if conn:
            self.logger.info("Bot connected to raid database.")
            create_table(conn, 'settings')
        else:
            self.logger.error("main could not create database connection!")
        self.conn = conn

        intents = discord.Intents.none()
        intents.guilds = True
        intents.dm_messages = True

        super().__init__(command_prefix=self.prefix_manager, case_insensitive=True, intents=intents,
                         activity=discord.Game(name=self.version))

        async def globally_block_dms(ctx):
            if ctx.guild is None and not await ctx.bot.is_owner(ctx.author):
                raise commands.NoPrivateMessage("No dm allowed!")
            else:
                return True

        super().add_check(globally_block_dms)

    def prefix_manager(self, bot, message):
        return commands.when_mentioned_or("!")(bot, message)

    async def on_ready(self):
        self.logger.info("We have logged in as {0}.".format(self.user))
        if not self.guilds:
            self.logger.error("The bot is not in any guilds. Shutting down.")
            await self.close()
            return
        for guild in self.guilds:
            self.logger.info('Welcome to {0}, {1}.'.format(guild.name, guild.id))
        try:
            await self.load_extension('config_cog')
            await self.load_extension('dev_cog')
            await self.load_extension('time_cog')
            # Load after time cog
            await self.load_extension('calendar_cog')
            # Load after calendar_cog
            await self.load_extension('raid_cog')
            # Load twitter cog
            #if self.twitter_token:
            #    await self.load_extension('twitter_cog')
            #else:
            #    self.logger.info("No twitter credentials found. Twitter cog will not be loaded.")
            # Load treasure cog
            if os.path.exists('../data/items/containers.xml'):
                await self.load_extension('treasure_cog')
            # Load custom cog
            await self.load_extension('custom_cog')
        except commands.ExtensionAlreadyLoaded:
            pass

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(_("You are not the bot owner."))
        else:
            if not isinstance(error, commands.CommandNotFound):
                self.logger.warning("Error for command: " + ctx.message.content)
                self.logger.warning(error)
            try:
                await ctx.send(error, delete_after=10)
            except discord.Forbidden:
                self.logger.warning("Missing Send messages permission for channel {0}".format(ctx.channel.id))
