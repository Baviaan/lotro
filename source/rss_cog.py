import discord
import feedparser
import json
import logging
import requests

from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks

from database import create_table, select, select_one, upsert

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@app_commands.guild_only()
class RSSCog(commands.GroupCog, name=_("rss"), description=_("Manage RSS settings.")):

    def __init__(self, bot):
        self.bot = bot
        self.conn = bot.conn
        create_table(self.conn, 'rss')
        super().__init__()

    async def cog_load(self):
        self.rss_task.start()

    async def cog_unload(self):
        self.rss_task.cancel()

    async def get_rss_feed(self, url):
        response = requests.get(url, verify="../lotro-com-chain.pem")
        if response.status_code != 200:
            logger.error("LotRO forums endpoint status: {0}.".format(response.status_code))
            logger.error(response.text)
            return None
        feed = feedparser.parse(response.text)
        return feed

    async def get_new_posts(self, urls):
        for thread_id, url in urls.items():
            last_post_id = select_one(self.conn, 'RSS', ['post_id'], ['thread_id'], [thread_id])
            feed = await self.get_rss_feed(url)
            if not feed:
                continue
            if not last_post_id:
                last_post_id = 0
            entries = sorted(feed.entries, key=lambda d: d['id'])
            for i in range(len(entries)):
                entry = entries[i]
                post_id = int(entry.id)
                if post_id > last_post_id:
                    last_post_id = post_id
                    upsert(self.conn, 'RSS', ['post_id'], [post_id], ['thread_id'], [thread_id])
                    await self.post_to_servers(entry)
            self.conn.commit()

    async def post_to_servers(self, entry):
        content = BeautifulSoup(entry.content[0].value, 'lxml')
        text = content.get_text() + "\n" + entry.link
        embed = discord.Embed(title=entry.title, colour=discord.Colour(0x3498db), description=text)
        res = select(self.conn, 'Settings', ['guild_id', 'rss'])
        for row in res:
            if row[1]:
                await self.post_embed(*row, embed)

    async def post_embed(self, guild_id, chn_id, embed):
        chn = self.bot.get_channel(chn_id)
        if chn:
            try:
                await chn.send(embed=embed)
            except discord.Forbidden:
                logger.warning("Missing write access to RSS channel for guild {0}.".format(guild_id))
                upsert(self.conn, 'Settings', ['rss'], [None], ['guild_id'], [guild_id])

        else:
            logger.warning("RSS channel not found for guild {0}.".format(guild_id))
            upsert(self.conn, 'Settings', ['rss'], [None], ['guild_id'], [guild_id])

    @app_commands.command(name=_("on"), description=_("Turn on RSS in this channel."))
    async def rss_on(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_("You must be an admin to set up RSS."), ephemeral=True)
            return
        channel = interaction.channel
        guild = interaction.guild
        perms = channel.permissions_for(guild.me)
        if not (perms.send_messages and perms.embed_links):
            await interaction.response.send_message(_("Missing permissions to access this channel."))
            return
        upsert(self.conn, 'Settings', ['rss'], [channel.id], ['guild_id'], [guild.id])
        await interaction.response.send_message(_("Forum announcements will be posted to this channel."))
        self.conn.commit()

    @app_commands.command(name=_("off"), description=_("Turn off RSS in this channel."))
    async def rss_off(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_("You must be an admin to turn off RSS."), ephemeral=True)
            return
        upsert(self.conn, 'Settings', ['rss'], [None], ['guild_id'], [interaction.guild_id])
        await interaction.response.send_message(_("Forum announcements will no longer be posted to this channel."))
        self.conn.commit()

    @tasks.loop(seconds=300)
    async def rss_task(self):
        urls = {
            5: "https://forums.lotro.com/index.php?forums/announcements.5/index.rss",
            6: "https://forums.lotro.com/index.php?forums/service-news.6/index.rss",
            7: "https://forums.lotro.com/index.php?forums/release-notes-and-known-issues.7/index.rss",
            8: "https://forums.lotro.com/index.php?forums/sales-and-promotions.8/index.rss",
            9: "https://forums.lotro.com/index.php?forums/official-discussions-and-developer-diaries.9/index.rss",
        }
        await self.get_new_posts(urls)
        logger.debug("Completed rss background task.")

    @rss_task.before_loop
    async def before_rss_task(self):
        await self.bot.wait_until_ready()

    @rss_task.error
    async def handle_error(self, exception):
        logger.error("RSS task failed.")
        logger.error(exception, exc_info=True)


async def setup(bot):
    await bot.add_cog(RSSCog(bot))
    logger.info("Loaded RSS Cog.")
