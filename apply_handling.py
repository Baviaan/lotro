import asyncio
import discord

from channel_handling import get_channel

async def new_app(bot,message,apply_channel_name):
    # This assumes the function is called on a message in a guild channel.
    author = message.author
    channel = message.channel
    apply_channel = await get_channel(message.guild,apply_channel_name)

    response = "{0} I will send you the info in a pm.".format(author.mention)
    await channel.send(response,delete_after=60)
    await message.delete()

    dm = "Hello there! Thanks for applying to {0}.".format(message.guild.name)
    try:
        await author.send(dm)
    except discord.Forbidden:
        response = "{0} you have not allowed me to send you a pm.".format(author.mention)
        await channel.send(response,delete_after=60)
        return
 
    def check(msg):
        return msg.author == author

    class_dm = "Please respond with your characters' names and classes."
    await author.send(class_dm)
    try:
        class_reply = await bot.wait_for('message',check=check,timeout=300)
    except asyncio.TimeoutError:
        await author.send("Sorry, you took too long to respond.")
        return

    raid_dm = "Please respond what times you are generally available for raiding (server time)."
    await author.send(raid_dm)
    try:
        raid_reply = await bot.wait_for('message',check=check,timeout=300)
    except asyncio.TimeoutError:
        await author.send("Sorry, you took too long to respond.")
        return

    embed = discord.Embed(title="A new application has arrived!")
    embed.add_field(name="Discord username:",value=author.name)
    embed.add_field(name="Discord nickname:",value=author.display_name)
    embed.add_field(name="User's response to '{0}':".format(class_dm),value=class_reply.content)
    embed.add_field(name="User's response to '{0}':".format(raid_dm),value=raid_reply.content)
    try:
        await apply_channel.send(embed=embed)
    except discord.errors.HTTPException:
        dm = "An error occured."
    else:
        dm = "Your application has been successfully submitted. An officer will be in touch soon!"
    await author.send(dm)
