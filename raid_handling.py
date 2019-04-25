import asyncio
import datetime
import dateparser
import discord
from discord.ext import commands
import re

from initialise import add_emojis, get_role_emojis
from raid import Raid
from role_handling import get_role

class Tier(commands.Converter):
    async def convert(self, ctx, argument):
        return await self.converter(argument)

    async def converter(self, argument):
        tier = re.search(r'\d+',argument) # Filter out non-numbers
        if tier is None:
            raise commands.BadArgument("Failed to parse tier argument: " + argument)
        tier = "T{0}".format(tier.group())
        return tier

class Time(commands.Converter):
    def __init__(self,tz):
        self.tz = tz

    async def convert(self, ctx, argument):
       return await self.converter(argument)

    async def converter(self, argument):
       if "server" in argument:
           # Strip off server (time) and return as server time
           argument = argument.partition("server")[0]
           my_settings={'PREFER_DATES_FROM': 'future','TIMEZONE': self.tz, 'RETURN_AS_TIMEZONE_AWARE': True}
       else:
           my_settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True}
       time = dateparser.parse(argument,settings=my_settings)
       if time is None:
           raise commands.BadArgument("Failed to parse time argument: " + argument)
       time = convert2UTC(time)
       # Check if time is in near futre.
       current_time = datetime.datetime.now()
       delta_time = datetime.timedelta(days=30)
       if current_time + delta_time < time:
           error_message = "You are not allowed to post raids more than a month in advance."
           raise commands.BadArgument(error_message)
       return time

async def raid_command(ctx,name,tier,boss,time,role_names,boss_name,server_tz):
    name = name.capitalize()
    boss = boss.capitalize()
    raid = Raid(name,tier,boss,time)
    embed = build_raid_message(raid,"\u200B",server_tz)
    post = await ctx.send(embed=embed)
    raid.set_post_id(post.id)
    raid.set_channel_id(ctx.channel.id)
    raid.set_guild_id(ctx.guild.id)
    emojis = await get_role_emojis(ctx.guild,role_names) 
    emojis.append("\u274C") # Cancel emoji
    emojis.append("\u2705") # Check mark emoji
    emojis.append("\u23F2") # Timer emoji
    boss_emoji = discord.utils.get(ctx.guild.emojis, name=boss_name)
    emojis.append(boss_emoji)
    await add_emojis(emojis,post)
    await asyncio.sleep(0.25)
    await post.pin()
    return raid

async def raid_update(bot,payload,raid,role_names,boss_name,raid_leader_name,server_tz):
    guild = bot.get_guild(payload.guild_id)
    channel = guild.get_channel(payload.channel_id)
    user = guild.get_member(payload.user_id)
    emoji = payload.emoji
    emojis = await get_role_emojis(guild,role_names)
    boss_emoji = discord.utils.get(guild.emojis, name=boss_name)
    update = False

    def check(msg):
        return msg.author == user

    if emoji == boss_emoji:
        raid_leader = await get_role(guild,raid_leader_name)
        if raid_leader not in user.roles:
            error_msg = "You do not have permission to change the raid boss. This incident will be reported to Santa Claus."
            print("Putting {0} on the naughty list.".format(user.name))
            await channel.send(error_msg,delete_after=15)
            return False
        await channel.send("Please specify the new raid boss.",delete_after=15)
        try:
            response = await bot.wait_for('message',check=check,timeout=300)
        except asyncio.TimeoutError:
            return False
        finally:
            await response.delete()
        boss = response.content.capitalize()
        raid.set_boss(boss)
        update = True
    elif str(emoji) == "\u23F2": # Timer emoji
        raid_leader = await get_role(guild,raid_leader_name)
        if raid_leader not in user.roles:
            error_msg = "You do not have permission to change the raid time. This incident will be reported to Santa Claus."
            print("Putting {0} on the naughty list.".format(user.name))
            await channel.send(error_msg,delete_after=15)
            return False
        await channel.send("Please specify the new raid time.",delete_after=15)
        try:
            response = await bot.wait_for('message',check=check,timeout=300)
        except asyncio.TimeoutError:
            return False
        try:
            time = await Time(server_tz).converter(response.content)
        except commands.BadArgument:
            error_msg = "Failed to parse time argument: " + response.content
            await channel.send(error_msg,delete_after=20)
            return False
        finally:
            await response.delete()
        raid.set_time(time)
        update = True
    elif str(emoji) == "\u274C": # Cancel emoji
        update = raid.remove_player(user)
    elif str(emoji) == "\u2705": # Check mark emoji
        has_class_role = False
        for emoji in emojis:
            if emoji.name in [role.name for role in user.roles]:
                update = raid.add_player(user,emoji)
                has_class_role = True
        if not has_class_role:
            error_msg = "{0} you have not assigned yourself any class roles.".format(user.mention)
            await channel.send(error_msg, delete_after=15)
    elif emoji in emojis:
        update = raid.add_player(user,emoji)
    msg = build_raid_players(raid.players)
    embed = build_raid_message(raid,msg,server_tz)
    post = await channel.fetch_message(raid.post_id)
    try:
        await post.edit(embed=embed)
    except discord.HTTPException:
        await channel.send("That's an error. Check the logs.")
        print("An error occured sending the following messages as embed.")
        for part in msg:
            print(part)
    return update

def convert2UTC(time):
    offset = time.utcoffset()
    time = time.replace(tzinfo=None)
    time = time - offset
    return time

def convert2Local(time):
    offset = time.utcoffset()
    time = time.replace(tzinfo=None)
    time = time + offset
    return time

def build_raid_message(raid,embed_texts,server_tz):
    server_time = local_time(raid.time,server_tz)
    header_time = server_time.strftime("%A %-I:%M %p server time")
    embed_title = "{0} {1} at {2}".format(raid.name,raid.tier,header_time)
    embed_description = "Bosses: {0}".format(raid.boss)
    embed = discord.Embed(title=embed_title,colour=discord.Colour(0x3498db), description=embed_description)
    time_string = build_time_string(raid.time)
    embed.add_field(name="Time zones:",value=time_string)
    embed.add_field(name="\u200B",value="\u200B")
    # Add a field for each embed text
    for i in range(len(embed_texts)):
        if i == 0:
            embed_name = "The following {0} players are available:".format(len(raid.players))
        else:
            embed_name = "\u200B"
        embed.add_field(name=embed_name,value=embed_texts[i])
    embed.set_footer(text="{0}".format(raid.time))
    return embed

def build_raid_players(players):
    if len(players) == 0:
        number_of_fields = 1
    else:
        number_of_fields = ((len(players)-1) // 6) +1
    msg = [""] * number_of_fields
    number_of_players = 0
    for player in players:
        index = number_of_players // 6
        number_of_players = number_of_players + 1
        msg[index] = msg[index] + player.display_name + " "
        for emoji in player.classes:
            msg[index] = msg[index] + str(emoji)
        msg[index] = msg[index] + "\n"
    if msg[0] == "":
        msg[0] = "\u200B"
    return msg 


def build_time_string(time):
    ny_time = local_time(time,"US/Eastern")
    lon_time = local_time(time,"Europe/London")
    syd_time = local_time(time,"Australia/Sydney")
    time_string = 'New York: ' + ny_time.strftime('%A %-I:%M %p') + '\n' + 'London: ' + lon_time.strftime('%A %-I:%M %p') + '\n' + 'Sydney: ' + syd_time.strftime('%A %-I:%M %p')
    return time_string

def local_time(time,timezone):
    local_settings = {'TIMEZONE': timezone, 'RETURN_AS_TIMEZONE_AWARE': True}
    local_time = dateparser.parse(str(time), settings=local_settings)
    local_time = convert2Local(local_time)
    return local_time
