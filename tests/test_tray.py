from fishcoin.ui.tray import build_menu


def test_every_menu_item_posts_its_event():
    """按 pystray 真实入口 MenuItem.__call__(icon) -> action(icon, item) 触发。"""
    events: list[str] = []
    menu = build_menu(events.append)
    for item in menu.items:
        if item.text:
            item(object())
    assert events == ["toggle", "details", "settings", "quit"]


def test_default_item_is_toggle():
    events: list[str] = []
    menu = build_menu(events.append)
    default = next(item for item in menu.items if item.default)
    default(object())
    assert events == ["toggle"]
