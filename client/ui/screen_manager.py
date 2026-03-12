# -*- coding: UTF-8 -*-
"""设备端界面元素创建与显隐管理。"""

LIFE_MODE_KEYS = (
    'background_life',
    'time_text',
    'temp_text',
    'humi_text',
    'sitting_text',
    'env_status',
)

SPORT_MODE_KEYS = (
    'background_sport',
    'time_text',
    'step_text',
    'pace_text',
    'carbon_reduce_text',
    'gps_status_text',
)

MEETING_MODE_KEYS = (
    'meeting_black',
)

ALL_UI_KEYS = (
    'background_life',
    'temp_text',
    'humi_text',
    'sitting_text',
    'env_status',
    'background_sport',
    'step_text',
    'pace_text',
    'carbon_reduce_text',
    'gps_status_text',
    'meeting_black',
    'time_text',
)


def create_ui_elements(gui):
    """创建所有模式下需要的 UI 元素。"""
    if not gui:
        return {}

    ui_elements = {}

    ui_elements['background_life'] = gui.draw_image(image="ui/life_mode.png", x=0, y=0)
    ui_elements['temp_text'] = gui.draw_text(
        text="--°C",
        x=178, y=223,
        font_size=11, color="#F17D30", angle=90, origin='center'
    )
    ui_elements['humi_text'] = gui.draw_text(
        text="-- %",
        x=201, y=221,
        font_size=11, color="#5A84F2", angle=90, origin='center'
    )
    ui_elements['sitting_text'] = gui.draw_text(
        text="0分钟",
        x=213, y=217,
        font_size=11, color="#000000", angle=90
    )
    ui_elements['env_status'] = gui.draw_text(
        text="适宜",
        x=175, y=115,
        font_size=18, color="#808080", angle=90, origin='center'
    )

    ui_elements['background_sport'] = gui.draw_image(image="ui/sport_mode.png", x=0, y=0)
    ui_elements['step_text'] = gui.draw_text(
        text="0 步",
        x=197, y=280,
        font_size=11, color="#000000", angle=90, origin='center'
    )
    ui_elements['pace_text'] = gui.draw_text(
        text="--'--\"",
        x=220, y=245,
        font_size=11, color="#000000", angle=90
    )
    ui_elements['carbon_reduce_text'] = gui.draw_text(
        text="0.00g",
        x=181, y=95,
        font_size=18, color="#8AD70D", angle=90, origin='center'
    )
    ui_elements['gps_status_text'] = gui.draw_text(
        text="GPS:--",
        x=234, y=36,
        font_size=9, color="#808080", angle=90, origin='center'
    )

    ui_elements['meeting_black'] = gui.fill_rect(x=0, y=0, w=240, h=320, color="#000000")
    ui_elements['time_text'] = gui.draw_text(
        text="00:00:00",
        x=0, y=320,
        font_size=25, color="#000000", angle=90
    )
    return ui_elements


def _set_elements_state(ui_elements, keys, state):
    for key in keys:
        element = ui_elements.get(key)
        if element is not None:
            element.config(state=state)


def hide_all_ui(ui_elements):
    """隐藏所有 UI 元素。"""
    _set_elements_state(ui_elements, ALL_UI_KEYS, 'hidden')


def update_ui_mode(ui_elements, current_mode, message_showing, mode_life, mode_sport, mode_meeting):
    """根据模式切换界面显示。"""
    if message_showing:
        return

    hide_all_ui(ui_elements)

    if current_mode == mode_life:
        _set_elements_state(ui_elements, LIFE_MODE_KEYS, 'normal')
    elif current_mode == mode_sport:
        _set_elements_state(ui_elements, SPORT_MODE_KEYS, 'normal')
    elif current_mode == mode_meeting:
        _set_elements_state(ui_elements, MEETING_MODE_KEYS, 'normal')
