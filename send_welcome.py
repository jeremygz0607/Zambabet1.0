#!/usr/bin/env python3
"""
One-off script to send and pin the Welcome message in the Telegram channel.
CHANGE 12: Pinned welcome message for onboarding.

Usage: python send_welcome.py

Requires: .env with TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, AFFILIATE_LINK.
Bot must be admin in the channel to pin messages.
"""
import logging

import config
import telegram_service

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    if not config.TELEGRAM_ENABLED:
        logger.error("Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID in .env")
        return 1
    if not config.AFFILIATE_LINK:
        logger.warning("AFFILIATE_LINK not set. Using default app.sinalgpt.ai link.")
    telegram_service.init()
    if telegram_service.send_and_pin_welcome_message():
        logger.info("Welcome message sent and pinned successfully.")
        return 0
    logger.error("Failed to send or pin welcome message.")
    return 1


if __name__ == "__main__":
    exit(main())
