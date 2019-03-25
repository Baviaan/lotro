import asyncio
import datetime
import dateparser
import discord
from discord.ext import commands
import re

from initialise import add_emojis, get_role_emojis
from raid import Raid

class Tier(commands.Converter):
    async def convert(self, ctx, argument):
        tier = re.search(r'\d+',argument) # Filter out non-numbers
        if tier is None:
            raise commands.BadArgument("Failed to parse tier argument: " + argument)
        tier = "T{0}".format(tier.group())
        return tier

class Time(commands.Converter):
    async def convert(self, ctx, argument):
       if "server" in argument:
           # Strip off server (time) and return as US Eastern
           argument = argument.partition("server")[0]
           my_settings={'PREFER_DATES_FROM': 'future','TIMEZONE': 'US/Eastern', 'RETURN_AS_TIMEZONE_AWARE': True}
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
       return(time)

async def raid_command(ctx,name,tier,boss,time,role_names):
    name = name.capitalize()
    boss = boss.capitalize()
    raid = Raid(name,tier,boss,time)
    embed = build_raid_message(raid,"\u200B")
    post = await ctx.send(embed=embed)
    raid.set_post_id(post.id)
    emojis = await get_role_emojis(ctx.guild,role_names) 
    # Add cancel emoji.
    emojis.append("\u274C")
    await add_emojis(emojis,post)
    await asyncio.sleep(0.25)
    await post.pin()
    return raid

async def raid_update(payload,guild,raid,role_names):
    channel = guild.get_channel(payload.channel_id)
    user = guild.get_member(payload.user_id)
    emoji = payload.emoji
    emojis = await get_role_emojis(guild,role_names)
    update = False
    if str(emoji) == "\u274C":
        update = raid.remove_player(user)
    elif emoji in emojis:
        update = raid.add_player(user,emoji)
    msg = build_raid_players(raid.players)
    embed = build_raid_message(raid,msg)
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

def build_raid_message(raid,embed_texts):
    server_time = local_time(raid.time,"US/Eastern")
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
