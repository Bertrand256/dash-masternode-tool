import unicodedata

try:
    import traceback
    import sys
    from trezorlib.client import TrezorClient, TrezorClientDebug, TrezorDebugClient
    from trezorlib.transport_hid import HidTransport
except Exception as e:
    print(str(e))
    traceback.print_exc(file=sys.stdout)
    input('Press any key...')


def main():
    try:
        # List all connected TREZORs on USB
        devices = HidTransport.enumerate()

        # Check whether we found any
        if len(devices) == 0:
            input('No TREZOR found. Press any key...')
            return

        # Use first connected device
        transport = HidTransport(devices[0])

        # Creates object for manipulating TREZOR
        client = TrezorClient(transport)

        # Print out TREZOR's features and settings
        print(client.features)

        # # Get the first address of first BIP44 account
        # # (should be the same address as shown in wallet.trezor.io)
        bip32_path = client.expand_path("m/44'/5'/0'/0/0")
        address = client.get_address('Dash', bip32_path)
        print('Dash address:', address)

        client.close()
    except Exception as e:
        print(str(e))
        traceback.print_exc(file=sys.stdout)
        input('Press any key...')


if __name__ == '__main__':
    main()