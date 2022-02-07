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

from database import create_connection, create_table, increment, select, upsert


class Bot(commands.Bot):

    def __init__(self):
        self.launch_time = datetime.utcnow()
        self.api = "https://discord.com/api/v8/"

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

        def read_config_key(config, key, required):
            try:
                value = config[key]
            except KeyError:
                try:
                    value = os.environ[key]
                except KeyError:
                    if required:
                        logging.critical(f"Please supply a config value for {key}.")
                        raise SystemExit
                    else:
                        value = None
            return value

        with open('config.json', 'r') as f:
            config = json.load(f)
        self.token = read_config_key(config, 'BOT_TOKEN', True)
        self.server_tz = read_config_key(config, 'SERVER_TZ', True)
        role_names = read_config_key(config, 'CLASSES', True)
        self.role_names = tuple(role_names)
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
        self.host_id = int(read_config_key(config, 'HOST', False))

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
        intents.guild_messages = True

        super().__init__(command_prefix=self.prefix_manager, case_insensitive=True, intents=intents,
                         activity=discord.Game(name=self.version))

        def globally_block_dms(ctx):
            if ctx.guild is None:
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
            self.logger.info('Welcome to {0}.'.format(guild))
        try:
            self.load_extension('config_cog')
            self.load_extension('dev_cog')
            self.load_extension('role_cog')
            self.load_extension('time_cog')
            # Load after time cog
            self.load_extension('calendar_cog')
            self.load_extension('raid_cog')
            # Load slash cog
            self.load_extension('slash_cog')
            self.load_extension('register_cog')
            # Load twitter cog
            if self.twitter_token:
                self.load_extension('twitter_cog')
            else:
                self.logger.info("No twitter credentials found. Twitter cog will not be loaded.")
            # Load custom cog
            self.load_extension('custom_cog')
        except commands.ExtensionAlreadyLoaded:
            pass

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(_("Please use this command in a server."))
        else:
            if not isinstance(error, commands.CommandNotFound):
                self.logger.warning("Error for command: " + ctx.message.content)
                self.logger.warning(error)
            try:
                await ctx.send(error, delete_after=10)
            except discord.Forbidden:
                self.logger.warning("Missing Send messages permission for channel {0}".format(ctx.channel.id))

    async def on_command_completion(self, ctx):
        timestamp = int(datetime.now().timestamp())
        upsert(self.conn, 'Settings', ['last_command'], [timestamp], ['guild_id'], [ctx.guild.id])
        increment(self.conn, 'Settings', 'command_count', ['guild_id'], [ctx.guild.id])
        self.conn.commit()
        await ctx.send(_("**DEPRECATED**: Consider using the new / command."), delete_after=60)
