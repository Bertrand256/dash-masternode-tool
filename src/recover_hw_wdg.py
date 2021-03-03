from typing import Callable

from PyQt5.QtWidgets import QWidget

from hw_intf import HWDevices
from ui.ui_recover_hw_wdg import Ui_WdgRecoverHw
from wallet_tools_common import ActionPageBase


class WdgRecoverHw(QWidget, Ui_WdgRecoverHw, ActionPageBase):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        Ui_WdgRecoverHw.__init__(self)
        ActionPageBase.__init__(self, parent, parent.app_config, hw_devices)
        self.setupUi(self)

    def setupUi(self, widget: QWidget):
        Ui_WdgRecoverHw.setupUi(self, self)

    def initialize(self):
        self.set_action_title('<b>Recover hardware wallet</b>')
        self.set_btn_cancel_visible(True)
        self.set_btn_back_visible(True)
        self.set_btn_continue_visible(True)
        self.set_btn_back_text('Back')
        self.set_btn_cancel_text('Cancel')
        self.set_btn_continue_text('Continue')

    def on_btn_back_clicked(self):
        self.exit_page()

