"""Qeo Telegram shortcut registrations."""

from .handlers.story import register_story
from .handlers.voice import register_voice


def register(ctx):
    register_story(ctx)
    register_voice(ctx)
