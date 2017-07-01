#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-05
import datetime
import json
import logging
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, pyqtSlot, QModelIndex
from PyQt5.QtWidgets import QDialog, QTableWidgetItem, QDialogButtonBox
import wnd_utils as wnd_utils
from app_config import DATE_FORMAT, DATETIME_FORMAT
from dashd_intf import DashdIndexException
from ui import ui_proposals


class Proposal(object):
    def __init__(self):
        pass


class ProposalColumn(object):
    def __init__(self, symbol, caption, visible):
        self.column_symbol = symbol
        self.caption = caption
        self.visible = visible


class ProposalsDlg(QDialog, ui_proposals.Ui_ProposalsDlg, wnd_utils.WndUtils):
    def __init__(self, parent, dashd_intf):
        QDialog.__init__(self, parent=parent)
        wnd_utils.WndUtils.__init__(self, app_path=parent.app_path)
        self.main_wnd = parent
        self.dashd_intf = dashd_intf
        self.proposals = []
        self.mn_count = None
        self.columns = [
            ProposalColumn('NAME', 'Name', True),
            ProposalColumn('HASH', 'Hash', False),
            ProposalColumn('COLLATERAL_HASH', 'Collateral hash', False),
            ProposalColumn('PAYMENT_START', 'Payment start', True),
            ProposalColumn('PAYMENT_END', 'Payment end', True),
            ProposalColumn('PAYMENT_AMOUNT', 'Amount', True),
            ProposalColumn('YES_COUNT', 'Yes count', True),
            ProposalColumn('NO_COUNT', 'No count', True),
            ProposalColumn('ABSTAIN_COUNT', 'Abstain count', True),
            ProposalColumn('CREATION_TIME', 'Creation time', True),
            ProposalColumn('URL', 'URL', True),
            ProposalColumn('PAYMENT_ADDRESS', 'Payment address', False)
        ]
        self.setupUi()

    def setupUi(self):
        try:
            ui_proposals.Ui_ProposalsDlg.setupUi(self, self)
            self.setWindowTitle('Proposals')

            # setup proposals grid
            self.tableWidget.clear()
            self.tableWidget.setColumnCount(len(self.columns))
            for idx, col in enumerate(self.columns):
                item = QtWidgets.QTableWidgetItem()
                item.setText(col.caption)
                self.tableWidget.setHorizontalHeaderItem(idx, item)
                if not col.visible:
                    self.tableWidget.hideColumn(idx)

            self.lblMessage.setVisible(True)
            self.lblMessage.setText('<b style="color:orange">Reading transactions, please wait...<b>')
            self.runInThread(self.load_proposals_thread, (), self.display_data)
            self.updateUi()
        except:
            logging.exception('Exception occurred')
            raise

    def updateUi(self):
        items = self.tableWidget.selectedItems()
        selected = len(items) > 0
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(selected)

    def load_proposals_thread(self, ctrl):
        try:
            if not self.dashd_intf.open():
                self.errorMsg('Dash daemon not connected')
            else:
                try:
                    self.proposals = self.dashd_intf.gobject("list", "valid", "proposals")
                    mns = self.dashd_intf.get_masternodelist('full')
                    self.mn_count = 0
                    statuses = {}
                    # count all active masternodes
                    for mn in mns:
                        if mn.status in ('ENABLED','PRE_ENABLED','NEW_START_REQUIRED','WATCHDOG_EXPIRED'):
                            self.mn_count += 1
                        if statuses.get(mn.status):
                            statuses[mn.status] += 1
                        else:
                            statuses[mn.status] = 1
                except DashdIndexException as e:
                    self.errorMsg(str(e))

                except Exception as e:
                    self.errorMsg('Error occurred while calling getaddressutxos method: ' + str(e))
        except Exception as e:
            pass

    def display_data(self):
        def item(value, horz_align = None):
            if isinstance(value, (int, float)):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, value)
            else:
                item = QTableWidgetItem(str(value))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if horz_align:
                item.setTextAlignment(horz_align)

            return item

        """
        Columns:
            0: name
            1: payment start
            2: payment end 
            3: payment amount
            4: yes count
            5: no count
            6: abstain count
            7: url
        """

        """
        'AbsoluteYesCount' = {int} 1233
        'AbstainCount' = {int} 5
        'CollateralHash' = {str} '8a7c9db293aeccf205b026753e12f57043f62b989ae0b0bfbbf467a3078e83ac'
        'CreationTime' = {int} 1487539972
        'DataHex' = {str} '
        'DataString' = {str} 
        '   [
               [
                  "proposal",
                  {
                     "end_epoch":"1495164424",
                     "name":"dash-detailed-2-shows",
                     "payment_address":"XbXb6rUeDrPcCe9xyoGTBL7TDkBU46KTvv",
                     "payment_amount":"215",
                     "start_epoch":"1487437984",
                     "type":1,
                     "url":"https://www.dash.org/forum/threads/dash-detailed-investor-report-5-pre-proposal.13136/"
                  }
               ]
            }
        '
        'Hash' = {str} '039db789f67dc8cddaddc5a382d805615da9298cd6a14620aa4ef81fd5d96430'
        'IsValidReason' = {str} ''
        'NoCount' = {int} 66
        'ObjectType' = {int} 1
        'YesCount' = {int} 1299
        'fBlockchainValidity' (5845426440) = {bool} True
        'fCachedDelete' (5845347568) = {bool} False
        'fCachedEndorsed' (5845347632) = {bool} False
        'fCachedFunding' (5845347504) = {bool} True
        'fCachedValid' (5845347440) = {bool} True"""

        """
        active:
        __len__ = {int} 16
        'AbsoluteYesCount' (5856492976) = {int} 404
        'AbstainCount' (5856443248) = {int} 3
        'CollateralHash' (5856442480) = {str} '4aee1851eeec5af3005b61fcc76d076269dffed004ea93d183957dd8000e6b9c'
        'CreationTime' (5856443184) = {int} 1494078194
        'DataHex' (5856434976) = {str} '5b5b2270726f706f73616c222c7b22656e645f65706f6368223a2231343937383435363234222c226e616d65223a224372656174652d7468652d66697273742d444153482d676174657761792d6f6e2d526970706c65222c227061796d656e745f61646472657373223a22587269416333564333793479617974686f46795a3
        'DataString' (4692987184) = {str} '[["proposal",{"end_epoch":"1497845624","name":"Create-the-first-DASH-gateway-on-Ripple","payment_address":"XriAc3VC3y4yaythoFyZ3YLRo1waumTdoB","payment_amount":"150","start_epoch":"1495270144","type":1,"url":"https://www.dashcentral.org/p/Create-the-first
        'Hash' (5856434696) = {str} '8a1d4e8f881d54d9314dc0d081f045cf74b187f8527ad763a11e101381226939'
        'IsValidReason' (5856443312) = {str} ''
        'NoCount' (5856435480) = {int} 50
        'ObjectType' (5856441776) = {int} 1
        'YesCount' (5856443120) = {int} 454
        'fBlockchainValidity' (5856493048) = {bool} True
        'fCachedDelete' (5856443440) = {bool} False
        'fCachedEndorsed' (5856443632) = {bool} False
        'fCachedFunding' (5856443504) = {bool} False
        'fCachedValid' (5856443568) = {bool} True        
        """

        def find_prop_data(prop_data):
            """
            Find proposal dict inside list returned in DataString field from RPC node 
            :param prop_data: 
            :return: 
            """
            if isinstance(prop_data, list):
                if len(prop_data) >= 2 and prop_data[0] == 'proposal' and isinstance(prop_data[1], dict):
                    return prop_data[1]
                elif len(prop_data) >= 1 and isinstance(prop_data[0], list):
                    return find_prop_data(prop_data[0])
            return None

        try:
            row = 0

            # todo: logging
            csv = [
                "proposal_name",
                "Hash",
                "fCachedDelete",
                "fCachedFunding",
                "ObjectType",
                "fBlockchainValidity",
                "fCachedEndorsed",
                "IsValidReason",
                "AbstainCount",
                "CollateralHash",
                "YesCount",
                "NoCount",
                "AbsoluteYesCount",
                "fCachedValid",
                "CreationTime",
                "proposal_url",
                "proposal_type",
                "proposal_end_epoch",
                "proposal_start_epoch",
                "proposal_payment_address",
                "proposal_payment_amount"]
            print('\t'.join(csv))

            for pro_key in self.proposals:
                prop = self.proposals[pro_key]
                # if prop.get('fCachedFunding', False) or prop.get('fCachedEndorsed', False):
                #     continue
                self.tableWidget.insertRow(self.tableWidget.rowCount())

                #todo: while debugging
                logging.debug('')
                logging.debug('=========================================================================================')
                logging.debug(json.dumps(prop))

                dstr = prop.get("DataString")
                prop_data_json = json.loads(dstr)
                prop_data = find_prop_data(prop_data_json)

                # todo: while debugging
                logging.debug('-----------------------------------')
                logging.debug(json.dumps(prop_data_json))

                if prop_data:
                    # todo: tempoary logging
                    csv = [
                        prop_data.get("name"),
                        prop.get("Hash"),
                        prop.get("fCachedDelete"),
                        prop.get("fCachedFunding"),
                        prop.get("ObjectType"),
                        prop.get("fBlockchainValidity"),
                        prop.get("fCachedEndorsed"),
                        prop.get("IsValidReason"),
                        prop.get("AbstainCount"),
                        prop.get("CollateralHash"),
                        prop.get("YesCount"),
                        prop.get("NoCount"),
                        prop.get("AbsoluteYesCount"),
                        prop.get("fCachedValid"),
                        datetime.datetime.fromtimestamp(int(prop.get("CreationTime"))).strftime(DATETIME_FORMAT),
                        prop_data.get("url"),
                        prop_data.get("type"),
                        datetime.datetime.fromtimestamp(int(prop_data['end_epoch'])).strftime(DATE_FORMAT),
                        datetime.datetime.fromtimestamp(int(prop_data['start_epoch'])).strftime(DATE_FORMAT),
                        prop_data.get("payment_address"),
                        prop_data.get("payment_amount")
                    ]
                    print('\t'.join([str(r) for r in csv]))

                    # "name" column display as a hyperlink if possible
                    url = prop_data.get('url', '')
                    if url:
                        url_lbl = QtWidgets.QLabel(self.tableWidget)
                        url_lbl.setText('<a href="%s">%s</a>' % (url, prop_data.get('name', '')))
                        url_lbl.setOpenExternalLinks(True)
                        self.tableWidget.setCellWidget(row, 0, url_lbl)
                    else:
                        self.tableWidget.setItem(row, 0, prop_data.get('name', ''))

                    dstart = datetime.datetime.fromtimestamp(int(prop_data['start_epoch'])).strftime(DATE_FORMAT)
                    dend = datetime.datetime.fromtimestamp(int(prop_data['end_epoch'])).strftime(DATE_FORMAT)
                    self.tableWidget.setItem(row, 1, item(dstart))  # 'Payment start' column
                    self.tableWidget.setItem(row, 2, item(dend))  # 'Payment end' column
                    self.tableWidget.setItem(row, 3, item(float(prop_data.get('payment_amount')), Qt.AlignRight))  # 'Payment amount' column
                    self.tableWidget.setItem(row, 4, item(int(prop.get('YesCount', '')), Qt.AlignRight))  # 'Yes count' column
                    self.tableWidget.setItem(row, 5, item(int(prop.get('NoCount', '')), Qt.AlignRight))  # 'No count' column
                    self.tableWidget.setItem(row, 6, item(int(prop.get('AbstainCount', '')), Qt.AlignRight))  # 'Abstain count' column
                else:
                    logging.warning("Not found proposal data for %s" % prop.get("Hash"))
                row += 1

            self.tableWidget.resizeColumnsToContents()
            self.lblMessage.setVisible(False)
            self.centerByWindow(self.main_wnd)

        except Exception as e:
            logging.exception("Exception occurred while displaing proposals.")
            self.lblMessage.setVisible(False)
            raise Exception('Error occurred while displaying proposals: ' + str(e))


            # self.tableWidget.setItem(row, 1, item(str(utxo.get('outputIndex', None))))
            # self.tableWidget.setItem(row, 2, item(utxo.get('time_str', None)))
            # self.tableWidget.setItem(row, 3, item(str(self.block_count - utxo.get('height', 0))))
        #
        # if len(self.utxos):
        #     self.tableWidget.resizeColumnsToContents()
        #     sh = self.sizeHint()
        #     sh.setWidth(sh.width() + 30)
        #     if sh.height() < 300:
        #         sh.setHeight(300)
        #     if sh.width() < 700:
        #         sh.setWidth(700)
        #     self.setBaseSize(sh)
        #     self.lblMessage.setVisible(False)
        #     self.centerByWindow(self.main_wnd)
        # else:
        #     self.lblMessage.setText('<b style="color:red">Found no unspent transactions with 1000 Dash '
        #                             'amount sent to address %s.<b>' %
        #                             self.dash_address)
        #     self.lblMessage.setVisible(True)

        self.updateUi()

    @pyqtSlot()
    def on_buttonBox_accepted(self):
        self.accept()

    @pyqtSlot()
    def on_buttonBox_rejected(self):
        self.reject()

    @pyqtSlot()
    def on_tableWidget_itemSelectionChanged(self):
        self.updateUi()

