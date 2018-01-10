## Hardware wallets initialization and recovery

Hardware wallets must be properly prepared for operation before their first use. This can be achieved with one of the following two scenarios:

- Initialization - a process that consists of generating a new set of private keys and related addresses on the device.

- Recovery - a process that consists of restoring a set of keys (and addresses) used previously, e.g. in another hardware or software wallet. This method is usually used when the previous device has failed, or we are simply "migrating our funds" to another device.


Although both scenarios are supported by official applications provided by manufacturers of the devices, there is a reason why those functionalities have been implemented within the DashMasternodeTool. Namely, Trezor - undoubtedly the most popular hardware wallet - despite its numerous advantages has one drawback: the official client application is a web-based solution, so in order to work it requires an Internet connection. It is therefore impossible to use it on an offline computer – and that is highly recommended considering the omnipresent malware and significant value of funds controlled by this type of device. It should also be taken into account that if the website [http://wallet.trezor.com](http://wallet.trezor.com/) is ever unavailable for whatever reason, it will be impossible to perform initialization or recovery.

[It will be continued]