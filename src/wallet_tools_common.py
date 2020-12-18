import logging
from typing import Callable, Optional, Any, Tuple, List

import hw_intf
from app_defs import HWType
from hw_common import HardwareWalletInstance

log = logging.getLogger('dmt.wallet_tools_dlg')


class ActionPageBase:
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
            fn_set_btn_continue_text: Callable[[str, str], None],
            fn_set_hw_panel_visible: Callable[[bool], None]
    ):

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
        self.fn_set_hw_panel_visible = fn_set_hw_panel_visible

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

    def set_hw_panel_visible(self, visible: bool):
        if self.fn_set_hw_panel_visible:
            self.fn_set_hw_panel_visible(visible)

    def on_btn_cancel_clicked(self):
        pass

    def on_btn_back_clicked(self):
        pass

    def on_btn_continue_clicked(self):
        pass


class HardwareWalletList(object):
    def __init__(self, main_ui, hw_type: Optional[HWType]):
        self.main_ui = main_ui
        self.hw_type: Optional[HWType] = hw_type
        self.hw_model: Optional[str] = None
        self.hw_device_instances: List[HardwareWalletInstance] = []
        self.hw_device_id_selected: Optional[str]  # device id of the hw client selected
        self.hw_device_index_selected: Optional[int] = None  # index in self.hw_device_instances
        self.devices_fetched = False

    def load_hw_devices(self, return_hw_clients=False):
        """
        Load all instances of the selected hardware wallet type. If there is more than one, user has to select which
        one he is going to use.
        """

        hw_intf.control_trezor_keepkey_libs(self.hw_type)
        self.main_ui.disconnect_hardware_wallet()  # disconnect hw if it's open in the main window
        self.clear()

        if self.hw_type in (HWType.trezor, HWType.keepkey):
            self.hw_device_instances, _ = hw_intf.get_device_list(self.hw_type, return_clients=return_hw_clients)

        elif self.hw_type == HWType.ledger_nano_s:
            from btchip.btchipComm import getDongle
            from btchip.btchipException import BTChipException
            try:
                dongle = getDongle()
                if dongle:
                    lbl = HWType.get_desc(self.hw_type)
                    self.hw_device_instances.append(HardwareWalletInstance('ledger', lbl, lbl, '', None, False))
                    dongle.close()
                    del dongle
            except BTChipException as e:
                if e.message != 'No dongle found':
                    raise

        self.devices_fetched = True

        if self.hw_device_id_selected:
            # check whether the device id selected before still exists in the list
            self.hw_device_index_selected = next((i for i, device in enumerate(self.hw_device_instances)
                                                  if device.device_id == self.hw_device_id_selected), None)
            if self.hw_device_index_selected is None:
                self.hw_device_id_selected = None

        if self.hw_device_instances:
            if not self.hw_device_id_selected:
                self.hw_device_id_selected = self.hw_device_instances[0].device_id
                self.hw_device_index_selected = 0

    def close_hw_clients(self):
        try:
            for idx, hw_inst in enumerate(self.hw_device_instances):
                if hw_inst.client:
                    hw_inst.client.close()
                    hw_inst.client = None
        except Exception as e:
            log.exception(str(e))

    def clear(self):
        self.close_hw_clients()
        self.hw_device_instances.clear()
        self.hw_device_id_selected = None
        self.hw_device_index_selected = None

    def get_hw_instances(self, force_fetch: bool = False) -> List[HardwareWalletInstance]:
        if force_fetch or not self.devices_fetched:
            self.load_hw_devices(True)
        return self.hw_device_instances

    def get_hw_instance_selected(self) -> Optional[HardwareWalletInstance]:
        if not self.devices_fetched:
            self.load_hw_devices(True)
        if self.hw_device_id_selected:
            return self.hw_device_instances[self.hw_device_index_selected]
        else:
            return None

    def set_hw_type(self, hw_type: HWType):
        if hw_type != self.hw_type:
            self.clear()
        self.hw_type = hw_type