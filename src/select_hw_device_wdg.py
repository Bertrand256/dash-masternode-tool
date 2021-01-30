import logging

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QWidget

from hw_intf import HWDevices


class SelectHwDeviceWdg(QWidget):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        self.hw_devices: HWDevices = hw_devices
        self.setupUi(self)

    def setupUi(self, dlg):
        dlg.setObjectName("SelectHwDeviceWdg")
        # SelectHwDeviceWdg.resize(444, 16)
        self.layout_main = QtWidgets.QVBoxLayout(dlg)
        self.layout_main.setContentsMargins(0, 0, 0, 0)
        self.layout_main.setSpacing(12)
        self.layout_main.setObjectName("verticalLayout")

        # self.lbl_hw_instance = QtWidgets.QLabel(dlg)
        # self.lbl_hw_instance.setObjectName("lblHwInstance")
        # self.layout_main.addWidget(self.lbl_hw_instance)

        spacer = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.layout_main.addItem(spacer)

        self.retranslateUi(dlg)
        QtCore.QMetaObject.connectSlotsByName(dlg)
        self.devices_to_ui()

    def retranslateUi(self, SelectHwDeviceWdg):
        _translate = QtCore.QCoreApplication.translate
        SelectHwDeviceWdg.setWindowTitle(_translate("SelectHwDeviceWdg", "Form"))

    def devices_to_ui(self):
        for ctrl in self.layout_main.children():
            if ctrl is QtWidgets.QRadioButton:
                del ctrl

        for dev in self.hw_devices.get_devices():
            ctrl = QtWidgets.QRadioButton(self)
            ctrl.setText(dev.get_description())
            self.layout_main.insertWidget(0, ctrl)

    def update(self):
        try:
            devices = self.hw_devices.get_devices()
            dev_sel = self.hw_devices.get_selected_device()

            # if dev_sel and devices:
            #     if len(devices) == 1:
            #         # there is only one device connected to the computer
            #         lbl = 'Device connected: <b>' + dev_sel.device_label + '</b>'
            #     else:
            #         # there is more than one device connected
            #         lbl = 'Device connected: <b>' + dev_sel.device_label + '</b> (<a href="select-hw-device">change</a>)'
            # else:
            #     lbl = 'Plug in your hardware wallet device'
            #
            # self.lbl_hw_instance.setText(lbl)
            #
            # lbl = 'Device type: <b>' + app_defs.HWType.get_desc(self.hw_devices.hw_type) + \
            #       '</b> (<a href="change-hw-type">change</a>) </span>'
            # self.lbl_hw_type.setText(lbl)

        except Exception as e:
            logging.exception(str(e))
