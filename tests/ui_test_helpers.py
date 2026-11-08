"""Wait for actual rendered hit targets before a Pilot action."""

import asyncio

from textual.errors import NoWidget


async def settle_button(pilot, button):
    button.focus(scroll_visible=False)
    previous = None
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        button.scroll_visible(animate=False, immediate=True)
        await pilot.pause(.05)
        region = button.region
        try:
            target, _ = button.screen.get_widget_at(region.x + 2, region.y + 1)
        except NoWidget:
            previous = None
            continue
        if target is button and previous == region:
            return
        previous = region if target is button else None
    raise AssertionError(f'Button never became a stable visible hit target: {button.classes}')
