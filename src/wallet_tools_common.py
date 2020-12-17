from typing import Callable, Optional


class ActionPageBase():
    def __init__(self):
        self.fn_exit_page: Optional[Callable[[], None]] = None
        self.fn_set_action_title: Optional[Callable[[str], None]] = None
        self.fn_set_btn_cancel_visible: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_cancel_enabled: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_cancel_text: Optional[Callable[[str, str], None]] = None
        self.fn_set_btn_back_visible: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_back_enabled: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_back_text: Optional[Callable[[str, str], None]] = None
        self.fn_set_btn_continue_visible: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_continue_enabled: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_continue_text: Optional[Callable[[str, str], None]] = None

    def set_control_functions(
            self,
            fn_exit_page: Callable[[], None],
            fn_set_action_title: Callable[[str], None],
            fn_set_btn_cancel_visible: Callable[[bool], None],
            fn_set_btn_cancel_enabled: Callable[[bool], None],
            fn_set_btn_cancel_text: Callable[[str, str], None],
            fn_set_btn_back_visible: Callable[[bool], None],
            fn_set_btn_back_enabled: Callable[[bool], None],
            fn_set_btn_back_text: Callable[[str, str], None],
            fn_set_btn_continue_visible: Callable[[bool], None],
            fn_set_btn_continue_enabled: Callable[[bool], None],
            fn_set_btn_continue_text: Callable[[str, str], None]):

        self.fn_exit_page = fn_exit_page
        self.fn_set_action_title = fn_set_action_title
        self.fn_set_btn_cancel_visible = fn_set_btn_cancel_visible
        self.fn_set_btn_cancel_enabled = fn_set_btn_cancel_enabled
        self.fn_set_btn_cancel_text = fn_set_btn_cancel_text
        self.fn_set_btn_back_visible = fn_set_btn_back_visible
        self.fn_set_btn_back_enabled = fn_set_btn_back_enabled
        self.fn_set_btn_back_text = fn_set_btn_back_text
        self.fn_set_btn_continue_visible = fn_set_btn_continue_visible
        self.fn_set_btn_continue_enabled = fn_set_btn_continue_enabled
        self.fn_set_btn_continue_text = fn_set_btn_continue_text

    def initialize(self):
        pass

    def exit_page(self):
        if self.fn_exit_page:
            self.fn_exit_page()

    def set_action_title(self, title: str):
        if self.fn_set_action_title:
            self.fn_set_action_title(title)

    def set_btn_cancel_visible(self, visible: bool):
        if self.fn_set_btn_cancel_visible:
            self.fn_set_btn_cancel_visible(visible)

    def set_btn_cancel_enabled(self, enabled: bool):
        if self.fn_set_btn_cancel_enabled:
            self.fn_set_btn_cancel_enabled = enabled

    def set_btn_cancel_text(self, label: str, tool_tip: Optional[str] = None):
        if self.fn_set_btn_cancel_text:
            self.fn_set_btn_cancel_text(label, tool_tip)

    def set_btn_back_visible(self, visible: bool):
        if self.fn_set_btn_back_visible:
            self.fn_set_btn_back_visible(visible)

    def set_btn_back_enabled(self, enabled: bool):
        if self.fn_set_btn_back_enabled:
            self.fn_set_btn_back_enabled(enabled)

    def set_btn_back_text(self, label: str, tool_tip: Optional[str] = None):
        if self.fn_set_btn_back_text:
            self.fn_set_btn_back_text(label, tool_tip)

    def set_btn_continue_visible(self, visible: bool):
        if self.fn_set_btn_continue_visible:
            self.fn_set_btn_continue_visible(visible)

    def set_btn_continue_enabled(self, enabled: bool):
        if self.fn_set_btn_continue_enabled:
            self.fn_set_btn_continue_enabled(enabled)

    def set_btn_continue_text(self, label: str, tool_tip: Optional[str] = None):
        if self.fn_set_btn_continue_text:
            self.fn_set_btn_continue_text(label, tool_tip)

    def on_btn_cancel_clicked(self):
        pass

    def on_btn_back_clicked(self):
        pass

    def on_btn_continue_clicked(self):
        pass