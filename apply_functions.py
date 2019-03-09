import discord

async def kin_app(client,message,apply_channel):
    channel_msg = '{0} I have sent you the info a pm.'.format(message.author.mention)
    await client.send_message(message.channel,channel_msg)
    class_question = "Please respond with your characters' names and classes."
    dm = "Hello there! " + class_question
    await client.send_message(message.author,dm)
    class_reply = await client.wait_for_message(author=message.author,timeout=300)
    if class_reply is None:
        dm = "You took too long to respond. Please apply again."
        await client.send_message(message.author,dm)
        return
    raid_question = "Please respond what times you are generally available for raiding (server time)."
    await client.send_message(message.author,raid_question)
    raid_reply = await client.wait_for_message(author=message.author,timeout=300)
    if raid_reply is None:
        dm = "You took too long to respond. Please apply again."
        await client.send_message(message.author,dm)
        return

    embed = discord.Embed(title="A new application has arrived!")
    embed.add_field(name="Discord username:",value=message.author.name)
    embed.add_field(name="Discord nickname:",value=message.author.display_name)
    embed.add_field(name="User's response to '{0}':".format(class_question),value=class_reply.content)
    embed.add_field(name="User's response to '{0}':".format(raid_question),value=raid_reply.content)
    try:
        await client.send_message(apply_channel,embed=embed)
        await client.send_message(message.author,"Your application has been submitted, an officer will be in touch soon!")
    except (discord.errors.HTTPException) as e:
        await client.send_message(message.author,"An error occured.")
