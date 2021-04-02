#!/usr/bin/env python3

from bot import Bot


def main():
    bot = Bot()
    bot.run(bot.token)
    bot.logger.info("Shutting down.")


if __name__ == '__main__':
    main()
