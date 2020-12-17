from typing import Callable

from PyQt5.QtWidgets import QWidget

from ui.ui_hw_settings_wdg import Ui_WdgHwSettings
from wallet_tools_common import ActionPageBase


class WdgHwSettings(QWidget, Ui_WdgHwSettings, ActionPageBase):
    def __init__(self, parent):
        QWidget.__init__(self, parent=parent)
        Ui_WdgHwSettings.__init__(self)
        ActionPageBase.__init__(self)
        self.setupUi()

    def setupUi(self):
        Ui_WdgHwSettings.setupUi(self, self)

    def initialize(self):
        self.set_action_title('<b>Hardware wallet settings</b>')
        self.set_btn_cancel_visible(True)
        self.set_btn_back_visible(True)
        self.set_btn_back_text('Back')
        self.set_btn_continue_visible(False)
        self.set_btn_cancel_text('Close')

    def on_btn_back_clicked(self):
        self.exit_page()

