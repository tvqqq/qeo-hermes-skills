"""Qeo Telegram shortcut registrations."""

from .handlers.story import register_story


def register(ctx):
    register_story(ctx)
