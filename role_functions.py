import discord
import asyncio

from channel_functions import clear_channel, add_emoji_pin

# Cleans up the channel, adds the initial post, adds reactions and pins the post.
async def prepare_channel(client,emojis,channel):
    await clear_channel(client,channel,100)

    message_content = 'Please mute this bot command channel or lose your sanity like me.\n\nReact to this post with each class you want to sign up for or click \u274C to remove all your class roles.\n\n*Further commands that can be used in this channel*:\n`!roles` Shows which class roles you currently have.\n`!dwarves` Shows a list of the 13 dwarves in the Anvil raid with their associated skills. (Work in progress.)\n`!apply` to apply to Reckoning.'
    role_post = await client.send_message(channel, message_content)
    await add_emoji_pin(client,emojis,role_post)
    await client.add_reaction(role_post,'\u274C')
    return role_post

async def add_role(client,emojis,class_roles,reaction,user):
    # Check if the reaction emoji matches any of our class emojis.
    for key,value in emojis.items():
        if reaction.emoji == value:
            # Add user to the class role.
            await client.add_roles(user, class_roles[key])
            # Send confirmation message.
            await client.send_message(reaction.message.channel, 'Added {0} to @{1}.'.format(user.mention,class_roles[key]))
    # Check if the reaction emoji is the cancel emoji
    if reaction.emoji == '\u274C':
        # Send a message because this will take 5s.
        await client.send_message(reaction.message.channel, 'Removing...')
        # Remove the user from all class roles.
        for key,value in class_roles.items():
            await client.remove_roles(user, value)
            # Discord rate limits requests; drops requests if too fast.
            await asyncio.sleep(0.5)
        # Send confirmation message.
        await client.send_message(reaction.message.channel, 'Removed {0} from all class roles.'.format(user.mention))

async def remove_role(client,emojis,class_roles,reaction,user):
    # Check if the reaction emoji matches any of our class emojis.
    for key,value in emojis.items():
        if reaction.emoji == value:
            # Remove user from the class role.
            await client.remove_roles(user, class_roles[key])
            # Send confirmation message.
            await client.send_message(reaction.message.channel, 'Removed {0} from @{1}.'.format(user.mention,class_roles[key]))

# Checks which class roles the user has and sends these to the class roles channel.
async def show_class_roles(client,class_roles,message):
    user = message.author
    send = '{0} has the following class roles: '.format(user.mention)
    has_class_role = False
    # Build string to send
    for key,value in class_roles.items():
        if value in user.roles:
            send = send + value.name + ', '
            has_class_role = True
    # leet formatting skills
    send = send[:-2]
    send = send + '.'
    if has_class_role:
        await client.send_message(message.channel,send)
    else:
        await client.send_message(message.channel,'{0} does not have any class roles assigned.'.format(user.mention))

