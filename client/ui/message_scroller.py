# -*- coding: UTF-8 -*-
"""旋转滚动消息显示"""

import threading
import time

from utils.logger import get_logger

logger = get_logger('ui.message_scroller')

PUNCTUATION = set(['，', '。', '、', '！', '？', '；', '：', '…', ',', '.', '!', '?', ';', ':', '\'', '"', '“', '”', '‘', '’'])


def split_message_tokens(message):
    """将标点附着到前一个字符，减少滚动时的视觉抖动"""
    tokens = []
    for char in message:
        if char in PUNCTUATION and tokens:
            tokens[-1] += char
        else:
            tokens.append(char)
    return tokens


def estimate_text_units(text):
    """估算文本宽度单位，用于滚动时长估计"""
    total = 0.0
    for char in text:
        if char.isspace():
            total += 0.06
        elif ord(char) < 128:
            if char.isalnum():
                total += 0.07
            else:
                total += 0.08
        else:
            if char in PUNCTUATION:
                total += 0.1
            else:
                total += 0.2
    return max(total, 1.0)


class RotatedMessageScroller:
    """将文本整体旋转 90 度后进行滚动显示"""

    def __init__(
        self,
        gui_getter,
        hide_ui_callback,
        restore_ui_callback,
        speak_callback,
        stop_voice_callback,
        is_running_callback,
        is_emergency_callback,
        state_change_callback=None,
        screen_width=240,
        screen_height=320,
        font_size=72,
        scroll_speed=74.0,
        frame_time=0.033,
        text_x=205,
        start_offset_ratio=0.9,
        initial_y_compensation=0,
        tail_gap_ratio=0.25,
        min_tail_gap=12,
    ):
        self.gui_getter = gui_getter
        self.hide_ui_callback = hide_ui_callback
        self.restore_ui_callback = restore_ui_callback
        self.speak_callback = speak_callback
        self.stop_voice_callback = stop_voice_callback
        self.is_running_callback = is_running_callback
        self.is_emergency_callback = is_emergency_callback
        self.state_change_callback = state_change_callback

        self.screen_width = screen_width
        self.screen_height = screen_height
        self.font_size = font_size
        self.scroll_speed = scroll_speed
        self.frame_time = frame_time
        self.text_x = text_x
        self.start_offset_ratio = start_offset_ratio
        self.initial_y_compensation = initial_y_compensation
        self.tail_gap_ratio = tail_gap_ratio
        self.min_tail_gap = min_tail_gap

        self.is_showing = False
        self.current_message = ""
        self._thread = None
        self._lock = threading.Lock()

    def _update_state(self, is_showing, message):
        self.is_showing = is_showing
        self.current_message = message
        if self.state_change_callback:
            try:
                self.state_change_callback(is_showing, message)
            except Exception as e:
                logger.debug(f"更新消息状态回调失败: {e}")

    def show(self, message):
        """显示滚动消息"""
        self.stop_voice_callback()

        with self._lock:
            if self._thread and self._thread.is_alive():
                self._update_state(False, "")
                time.sleep(0.08)

            self.hide_ui_callback()
            time.sleep(0.02)
            self._update_state(True, message)
            self.speak_callback(message)

            self._thread = threading.Thread(target=self._scroll_loop, args=(message,), daemon=True)
            self._thread.start()

    def hide(self):
        """退出滚动显示"""
        self._update_state(False, "")
        self.stop_voice_callback()
        time.sleep(0.08)
        self.restore_ui_callback()

    def _scroll_loop(self, message):
        gui = self.gui_getter()
        if not gui:
            self._update_state(False, "")
            return

        tokens = split_message_tokens(message)
        rendered_message = ''.join(tokens)
        text_color = "#FF0000" if self.is_emergency_callback() else "#000000"

        text_units = estimate_text_units(rendered_message)
        content_extent = int(self.font_size * 1.3 * text_units + self.font_size * 2.1)
        start_offset = int(self.font_size * self.start_offset_ratio)
        start_y = start_offset + int(self.initial_y_compensation)
        tail_gap = max(int(self.font_size * self.tail_gap_ratio), int(self.min_tail_gap))
        total_scroll_distance = self.screen_height + content_extent - start_y + tail_gap

        white_bg = gui.fill_rect(x=0, y=0, w=self.screen_width, h=self.screen_height, color="#FFFFFF")
        scroll_text = gui.draw_text(
            x=self.text_x,
            y=start_y,
            text=rendered_message,
            color=text_color,
            font_size=self.font_size,
            anchor="n",
            angle=90,
        )

        start_time = time.perf_counter()

        while self.is_showing and self.is_running_callback() and self.current_message == message:
            elapsed = time.perf_counter() - start_time
            offset = (elapsed * self.scroll_speed) % total_scroll_distance
            y_pos = start_y + int(offset)

            try:
                scroll_text.config(y=y_pos)
            except Exception:
                break

            time.sleep(self.frame_time)

        try:
            scroll_text.remove()
            white_bg.remove()
        except Exception:
            pass

        if self.current_message == message:
            self._update_state(False, "")
            self.restore_ui_callback()
