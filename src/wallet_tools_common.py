import functools
import logging
from typing import Callable, Optional, Any, Tuple, List

import hw_intf
from app_config import AppConfig
from common import CancelException, HwNotInitialized
from hw_common import HWDevice, HWType
from wnd_utils import WndUtils

log = logging.getLogger('dmt.wallet_tools_dlg')


class ActionPageBase:
    def __init__(self, parent_dialog, app_config: AppConfig, hw_devices: hw_intf.HWDevices, action_title: str):
        self.parent_dialog = parent_dialog
        self.app_config: AppConfig = app_config
        self.finishing = False
        self.hw_devices = hw_devices
        self.hw_devices.sig_connected_hw_device_changed.connect(self._on_connected_hw_device_changed)
        self.action_title = action_title
        self.fn_exit_page: Optional[Callable[[], None]] = None
        self.fn_set_action_title: Optional[Callable[[str], None]] = None
        self.fn_set_btn_close_visible: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_close_enabled: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_cancel_visible: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_cancel_enabled: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_cancel_text: Optional[Callable[[str, str], None]] = None
        self.fn_set_btn_back_visible: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_back_enabled: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_back_text: Optional[Callable[[str, str], None]] = None
        self.fn_set_btn_continue_visible: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_continue_enabled: Optional[Callable[[bool], None]] = None
        self.fn_set_btn_continue_text: Optional[Callable[[str, str], None]] = None
        self.fn_set_hw_change_enabled: Optional[Callable[[bool], None]] = None
        self.fn_show_message_page: Optional[Callable[[Optional[str]], None]] = None
        self.fn_show_action_page: Optional[Callable[[None], None]] = None

    def set_control_functions(
            self,
            fn_exit_page: Callable[[], None],
            fn_set_action_title: Callable[[str], None],
            fn_set_btn_close_visible: Callable[[bool], None],
            fn_set_btn_close_enabled: Callable[[bool], None],
            fn_set_btn_cancel_visible: Callable[[bool], None],
            fn_set_btn_cancel_enabled: Callable[[bool], None],
            fn_set_btn_cancel_text: Callable[[str, str], None],
            fn_set_btn_back_visible: Callable[[bool], None],
            fn_set_btn_back_enabled: Callable[[bool], None],
            fn_set_btn_back_text: Callable[[str, str], None],
            fn_set_btn_continue_visible: Callable[[bool], None],
            fn_set_btn_continue_enabled: Callable[[bool], None],
            fn_set_btn_continue_text: Callable[[str, str], None],
            fn_set_hw_panel_visible: Callable[[bool], None],
            fn_set_hw_change_enabled: Callable[[bool], None],
            fn_show_message_page: Optional[Callable[[Optional[str]], None]],
            fn_show_action_page: Optional[Callable[[], None]]):

        self.fn_exit_page = fn_exit_page
        self.fn_set_action_title = fn_set_action_title
        self.fn_set_btn_close_visible = fn_set_btn_close_visible
        self.fn_set_btn_close_enabled = fn_set_btn_close_enabled
        self.fn_set_btn_cancel_visible = fn_set_btn_cancel_visible
        self.fn_set_btn_cancel_enabled = fn_set_btn_cancel_enabled
        self.fn_set_btn_cancel_text = fn_set_btn_cancel_text
        self.fn_set_btn_back_visible = fn_set_btn_back_visible
        self.fn_set_btn_back_enabled = fn_set_btn_back_enabled
        self.fn_set_btn_back_text = fn_set_btn_back_text
        self.fn_set_btn_continue_visible = fn_set_btn_continue_visible
        self.fn_set_btn_continue_enabled = fn_set_btn_continue_enabled
        self.fn_set_btn_continue_text = fn_set_btn_continue_text
        self.fn_set_hw_panel_visible = fn_set_hw_panel_visible
        self.fn_set_hw_change_enabled = fn_set_hw_change_enabled
        self.fn_show_message_page = fn_show_message_page
        self.fn_show_action_page = fn_show_action_page

    def initialize(self):
        self.update_action_subtitle('')
        self.set_btn_close_visible(False)

    def on_close(self):
        pass

    def _on_connected_hw_device_changed(self, hw_device: HWDevice):
        if not self.finishing:
            self.on_connected_hw_device_changed(hw_device)

    def on_validate_hw_device(self, hw_device: HWDevice) -> bool:
        """
        Its purpose is to validate in derived classes whether the hardware wallet device passed in the 'hw_device'
        argument is approved or not. This way, a derived class may not allow a certain type or model of hardware
        wallet for the tasks associated with that class.
        :return: True, if hw device is accepted, False otherwise
        """
        return False

    def on_connected_hw_device_changed(self, cur_hw_device: HWDevice):
        pass

    def exit_page(self):
        if self.fn_exit_page:
            self.fn_exit_page()

    def set_action_title(self, title: str):
        if self.fn_set_action_title:
            self.fn_set_action_title(title)

    def set_btn_close_visible(self, visible: bool):
        if self.fn_set_btn_close_visible:
            self.fn_set_btn_close_visible(visible)

    def set_btn_close_enabled(self, enabled: bool):
        if self.fn_set_btn_close_enabled:
            self.fn_set_btn_close_enabled(enabled)

    def set_btn_cancel_visible(self, visible: bool):
        if self.fn_set_btn_cancel_visible:
            self.fn_set_btn_cancel_visible(visible)

    def set_btn_cancel_enabled(self, enabled: bool):
        if self.fn_set_btn_cancel_enabled:
            self.fn_set_btn_cancel_enabled(enabled)

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

    def set_hw_panel_visible(self, visible: bool):
        if self.fn_set_hw_panel_visible:
            self.fn_set_hw_panel_visible(visible)

    def set_hw_change_enabled(self, enabled: bool):
        if self.fn_set_hw_change_enabled:
            self.fn_set_hw_change_enabled(enabled)

    def show_message_page(self, message: Optional[str] = None):
        if self.fn_show_message_page:
            self.fn_show_message_page(message)

    def show_action_page(self):
        if self.fn_show_action_page:
            self.fn_show_action_page()

    def go_to_next_step(self):
        pass

    def go_to_prev_step(self):
        self.exit_page()

    def on_btn_continue_clicked(self):
        self.go_to_next_step()

    def on_btn_back_clicked(self):
        self.go_to_prev_step()

    def on_before_cancel(self) -> bool:
        """
        Called by the wallet tools dialog before closing dialog (after the <Cancel> button has been clicked.
        :return: True if the action widget allows for closure or False otherwise.
        """
        return True

    def on_before_close(self) -> bool:
        """
        Called by the wallet tools dialog before closing dialog (after the <Close> button has been clicked.
        :return: True if the action widget allows for closure or False otherwise.
        """
        return True

    def update_action_subtitle(self, subtitle: Optional[str] = None):
        title = self.action_title
        if subtitle:
            title += ' - ' + subtitle
        self.set_action_title(f'<b>{title}</b>')


def handle_hw_exceptions(func):
    """
    The purpose of this wrapper is to intercept known exceptions related to hardware wallets, like cancelling
    operations by the user, errors about not initialized device, etc, and to display an appropriate message.
    """

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        ret = None
        try:
            ret = func(self, *args, **kwargs)
        except CancelException:
            pass
        except HwNotInitialized:
            WndUtils.error_msg('Your hardware wallet device is not initialized. To initialize your device, you can '
                               'use the (a) "initialization" or (b) "recovery from seed" features available in this '
                               'application.')
        except Exception as e:
            WndUtils.error_msg(str(e), True)
        return ret
    return wrapper