import logging
import re
import ssl
import urllib, urllib.request, urllib.parse
from enum import Enum
from typing import Callable, Optional, List, Dict

import simplejson
from PyQt5 import QtGui, QtCore
from PyQt5.QtCore import pyqtSlot, QItemSelection, QItemSelectionModel, Qt
from PyQt5.QtWidgets import QWidget, QMessageBox, QTableWidgetItem

import app_defs
import hw_intf
from app_defs import get_note_url
from common import CancelException
from hw_common import HWDevice, HWType
from thread_fun_dlg import CtrlObject
from ui.ui_hw_update_firmware_wdg import Ui_WdgHwUpdateFirmware
from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices
from wnd_utils import WndUtils, ReadOnlyTableCellDelegate


class Step(Enum):
    STEP_FIRMWARE_SOURCE = 1
    STEP_UPLOAD_FIRMWARE = 2


class FirmwareSource(Enum):
    INTERNET = 1
    LOCAL_FILE = 2


class Pages(Enum):
    PAGE_FIRMWARE_SOURCE = 0
    PAGE_UPLOAD_FIRMWARE = 1
    PAGE_MESSAGE = 2


class WdgHwUpdateFirmware(QWidget, Ui_WdgHwUpdateFirmware, ActionPageBase):
    def __init__(self, parent, hw_devices: HWDevices):
        QWidget.__init__(self, parent=parent)
        Ui_WdgHwUpdateFirmware.__init__(self)
        ActionPageBase.__init__(self, hw_devices)

        self.cur_hw_device: Optional[HWDevice] = self.hw_devices.get_selected_device()
        self.current_step: Step = Step.STEP_FIRMWARE_SOURCE
        self.hw_firmware_source_type: FirmwareSource = FirmwareSource.INTERNET
        self.hw_firmware_source_file: str = ''
        self.hw_firmware_web_sources: List[Dict] = []
        # subset of self.hw_firmware_web_sources dedicated to current hardware wallet type:
        self.hw_firmware_web_sources_cur_hw: List = []
        self.hw_firmware_url_selected: Optional[Dict] = None
        self.hw_firmware_last_hw_type = None
        self.hw_firmware_last_hw_model = None

        self.setupUi(self)

    def setupUi(self, dlg):
        Ui_WdgHwUpdateFirmware.setupUi(self, self)
        WndUtils.change_widget_font_attrs(self.lblMessage, point_size_diff=3, bold=True)
        self.tabFirmwareWebSources.verticalHeader().setDefaultSectionSize(
            self.tabFirmwareWebSources.verticalHeader().fontMetrics().height() + 3)
        self.tabFirmwareWebSources.setItemDelegate(ReadOnlyTableCellDelegate(self.tabFirmwareWebSources))
        self.pages.setCurrentIndex(Pages.PAGE_FIRMWARE_SOURCE.value)

    def initialize(self):
        self.set_action_title('<b>Update hardware wallet firmware</b>')
        self.set_btn_cancel_visible(True)
        self.set_btn_back_visible(True)
        self.set_btn_back_text('Back')
        self.set_btn_continue_visible(True)
        self.set_btn_cancel_text('Close')
        self.set_hw_panel_visible(True)
        if not self.hw_firmware_web_sources:
            self.load_remote_firmware_list()
        self.update_ui()
        hw_changed = False
        if not self.cur_hw_device:
            self.hw_devices.select_device(self.parent())
            hw_changed = True
        if self.cur_hw_device and not self.cur_hw_device.hw_client:
            self.hw_devices.open_hw_session(self.cur_hw_device)
            hw_changed = True
        if hw_changed:
            self.update_ui()
            self.display_firmware_list()

    def on_current_hw_device_changed(self, cur_hw_device: HWDevice):
        if cur_hw_device:
            if cur_hw_device.hw_type == HWType.ledger_nano:
                # If the wallet type is not Trezor or Keepkey we can't use this page
                self.cur_hw_device = None
                self.update_ui()
                WndUtils.warn_msg('This feature is not available for Ledger devices.')
            else:
                self.cur_hw_device = self.hw_devices.get_selected_device()
                if not self.cur_hw_device.hw_client:
                    self.hw_devices.open_hw_session(self.cur_hw_device)
                self.update_ui()
                self.display_firmware_list()

    def on_btn_back_clicked(self):
        self.exit_page()

    @pyqtSlot(bool)
    def on_rbFirmwareSourceInternet_toggled(self, checked):
        if checked:
            self.hw_firmware_source_type = FirmwareSource.INTERNET
            self.update_ui()

    @pyqtSlot(bool)
    def on_rbFirmwareSourceLocalFile_toggled(self, checked):
        if checked:
            self.hw_firmware_source_type = FirmwareSource.LOCAL_FILE
            self.update_ui()

    def update_ui(self):
        try:
            if self.cur_hw_device and self.cur_hw_device.hw_client:
                if self.current_step == Step.STEP_FIRMWARE_SOURCE:
                    self.set_btn_continue_visible(True)
                    self.pages.setCurrentIndex(Pages.PAGE_FIRMWARE_SOURCE.value)
                    if self.hw_firmware_source_type == FirmwareSource.INTERNET:
                        self.lblFileLabel.setVisible(False)
                        self.edtFirmwareFilePath.setVisible(False)
                        self.btnChooseFirmwareFile.setVisible(False)
                        self.tabFirmwareWebSources.setVisible(True)
                        self.edtFirmwareNotes.setVisible(True)
                    elif self.hw_firmware_source_type == FirmwareSource.LOCAL_FILE:
                        self.lblFileLabel.setVisible(True)
                        self.edtFirmwareFilePath.setVisible(True)
                        self.btnChooseFirmwareFile.setVisible(True)
                        self.tabFirmwareWebSources.setVisible(False)
                        self.edtFirmwareNotes.setVisible(False)

                elif self.current_step == Step.STEP_UPLOAD_FIRMWARE:
                    self.pages.setCurrentIndex(Pages.PAGE_UPLOAD_FIRMWARE.value)
                    self.set_btn_continue_visible(False)

            else:
                self.lblMessage.setText('<b>Connect your hardware wallet device to continue</b>')
                self.pages.setCurrentIndex(Pages.PAGE_MESSAGE.value)

        except Exception as e:
            WndUtils.error_msg(str(e), True)

    def load_remote_firmware_list(self):
        WndUtils.run_thread(self, self.load_remote_firmware_list_thread, (),
                            on_thread_finish=self.display_firmware_list)

    def load_remote_firmware_list_thread(self, ctrl: CtrlObject):
        def load_firmware_list_from_url(base_url: str, list_url, device: str = None, official: bool = False,
                                        model: str = None, testnet_support: bool = False):
            r = urllib.request.urlopen(list_url)
            c = r.read()
            fw_list = simplejson.loads(c)
            for f in fw_list:
                url = f.get('url')
                if url.startswith('/') and base_url.endswith('/'):
                    f['url'] = base_url + url[1:]
                elif not base_url.endswith('/') and not url.startswith('/'):
                    f['url'] = base_url + '/' + url
                else:
                    f['url'] = base_url + url
                if not f.get('device') and device:
                    f['device'] = device
                if not f.get('official') and official:
                    f['official'] = official
                if not f.get('model') and model:
                    f['model'] = model
                f['testnet'] = testnet_support
                self.hw_firmware_web_sources.append(f)

        try:
            self.hw_firmware_url_selected = None
            self.hw_firmware_web_sources.clear()
            project_url = app_defs.PROJECT_URL.replace('//github.com', '//raw.githubusercontent.com')
            if not project_url.endswith('/'):
                project_url += '/'
            project_url += 'master/'

            url = urllib.parse.urljoin(project_url, 'hardware-wallets/firmware/firmware-sources.json')
            response = urllib.request.urlopen(url)
            contents = response.read()
            fw_sources = simplejson.loads(contents)
            for fw_src in fw_sources:
                try:
                    official = fw_src.get('official')
                    device = fw_src.get('device')
                    model = fw_src.get('model')
                    url = fw_src.get('url')
                    url_base = fw_src.get('url_base')
                    testnet_support = fw_src.get('testnetSupport', True)
                    if not url_base:
                        url_base = project_url

                    if not re.match('\s*http://', url, re.IGNORECASE):
                        url = urllib.parse.urljoin(url_base, url)

                    load_firmware_list_from_url(base_url=url_base, list_url=url, device=device, official=official,
                                                model=model, testnet_support=testnet_support)

                except Exception:
                    logging.exception('Exception while processing firmware source')
        except Exception as e:
            logging.error('Error while loading hardware-wallets/firmware/releases.json file from GitHub: ' + str(e))

    def display_firmware_list(self):
        """Display list of firmwares available for the currently selected hw type."""

        def item(value):
            i = QTableWidgetItem(value)
            i.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            return i

        self.hw_firmware_url_selected = None
        self.hw_firmware_web_sources_cur_hw.clear()

        if self.cur_hw_device:
            for f in self.hw_firmware_web_sources:
                if f.get('device').lower() == self.cur_hw_device.hw_type.value.lower() and \
                        (self.cur_hw_device.hw_type != HWType.trezor or
                         self.cur_hw_device.device_model == f.get('model')):
                    self.hw_firmware_web_sources_cur_hw.append(f)

        self.tabFirmwareWebSources.setRowCount(len(self.hw_firmware_web_sources_cur_hw))
        for row, f in enumerate(self.hw_firmware_web_sources_cur_hw):
            version = f.get('version', None)
            if isinstance(version, list):
                version = '.'.join(str(x) for x in version)
            else:
                version = str(version)
            if f.get('testnet', False):
                testnet = 'Yes'
            else:
                testnet = 'No'
            if f.get('official', False):
                official = 'Yes'
            else:
                official = 'Custom/Unofficial'

            if f.get('device').lower() == 'trezor':
                if f.get('model', '1') == '1':
                    model = 'Trezor One'
                else:
                    model = 'Trezor T'
            else:
                model = str(f.get('model', 1))

            self.tabFirmwareWebSources.setItem(row, 0, item(version))
            self.tabFirmwareWebSources.setItem(row, 1, item(model))
            self.tabFirmwareWebSources.setItem(row, 2, item(official))
            self.tabFirmwareWebSources.setItem(row, 3, item(testnet))
            # self.tabFirmwareWebSources.setItem(row, 4, item(str(f.get('url', ''))))
            # self.tabFirmwareWebSources.setItem(row, 5, item(str(f.get('fingerprint', ''))))

        self.tabFirmwareWebSources.resizeColumnsToContents()
        if len(self.hw_firmware_web_sources_cur_hw) > 0:
            self.tabFirmwareWebSources.selectRow(0)
            # self.on_tabFirmwareWebSources_itemSelectionChanged isn't always fired up if there was previously
            # selected row, so we need to force selecting new row:
            self.select_firmware(0)
        else:
            sm = self.tabFirmwareWebSources.selectionModel()
            s = QItemSelection()
            sm.select(s, QItemSelectionModel.Clear | QItemSelectionModel.Rows)
            # force deselect firmware:
            self.select_firmware(-1)

        # max_col_width = 230
        # for idx in range(self.tabFirmwareWebSources.columnCount()):
        #     w = self.tabFirmwareWebSources.columnWidth(idx)
        #     if w > max_col_width:
        #         self.tabFirmwareWebSources.setColumnWidth(idx, max_col_width)

    def on_tabFirmwareWebSources_itemSelectionChanged(self):
        try:
            idx = self.tabFirmwareWebSources.currentIndex()
            row_index = -1
            if idx:
                row_index = idx.row()
            self.select_firmware(row_index)
        except Exception as e:
            self.error_msg(str(e))

    def select_firmware(self, row_index):
        if row_index >= 0:
            item = self.tabFirmwareWebSources.item(row_index, 0)
            if item:
                idx = self.tabFirmwareWebSources.indexFromItem(item)
                if idx:
                    row = idx.row()
                    if 0 <= row <= len(self.hw_firmware_web_sources_cur_hw):
                        details = ''
                        cfg = self.hw_firmware_web_sources_cur_hw[row]
                        self.hw_firmware_url_selected = cfg
                        notes = cfg.get('notes', '')
                        fingerprint = cfg.get('fingerprint')
                        changelog = cfg.get('changelog', '')
                        if changelog:
                            details += 'Changelog:\n' + changelog + '\n'
                        if fingerprint:
                            details += '\nFingerprint: ' + fingerprint + '\n'
                        if notes:
                            details += '\nNotes: ' + notes

                        self.edtFirmwareNotes.setText(details)
                        return
        self.hw_firmware_url_selected = None
        self.edtFirmwareNotes.clear()
