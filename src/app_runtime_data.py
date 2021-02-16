from typing import Optional


class AppRuntimeData:
    __instance = None

    @staticmethod
    def get_instance() -> 'AppRuntimeData':
        return AppRuntimeData.__instance

    def __init__(self, app_config: 'AppConfig', dashd_intf: 'DashdInterface'):
        if AppRuntimeData.__instance is not None:
            raise Exception('Internal error: cannot create another instance of this class')
        AppRuntimeData.__instance = self

        self._app_config = app_config
        self._dashd_intf = dashd_intf

    @property
    def hw_coin_name(self):
        return self._app_config.hw_coin_name

    @property
    def is_testnet(self):
        return self._app_config.is_testnet

    @property
    def dash_network(self):
        return self._app_config.dash_network

    @property
    def tx_cache_dir(self):
        return self._app_config.tx_cache_dir

    @property
    def app_config(self):
        return self._app_config

    @app_config.setter
    def app_config(self, app_config):
        self._app_config = app_config

    @property
    def dashd_intf(self):
        return self._dashd_intf

