## Hardware wallet initialization and recovery

 * [Introduction](#Introduction)  
 * [Understanding the *recovery seed*](#understanding-the-recovery-seed)  
 * [Security principles](#security-principles)  
 * [Hardware wallet initialization and recovery in DMT](#hardware-wallet-initialization-and-recovery-in-dmt)  
    * [Hardware wallet recovery - safe mode](hw-initr-safe-mode.md)  
    * [Hardware wallet recovery - convenient mode](hw-initr-conv-mode.md)  
    * [Hardware wallet recovery from hexadecimal entropy](hw-initr-entropy-mode.md)  
    * [Hardware wallet initialization with a newly generated seed words](hw-initr-new-seed.md)  
    * [Wiping hardware wallet](hw-initr-wipe.md)
 * [Running DMT on an offline Linux system](hw-initr-live-cd-linux.md)

### Introduction

Hardware wallets must be properly prepared for operation before their first use. This can be achieved with one of the following two scenarios:

- Initialization - a process that consists of generating a new set of private keys and related addresses on the device.

- Recovery - a process that consists of restoring a set of keys (and addresses) used previously, e.g. in another hardware or software wallet. This method is usually used when the previous device has failed, or we are simply "migrating our funds" to another device.


Although both scenarios are supported by official applications provided by manufacturers of the devices, there is a reason why those functionalities have been implemented within the DashMasternodeTool. Namely, Trezor - undoubtedly the most popular hardware wallet - despite its numerous advantages has one drawback: the official client application is a web-based solution, so in order to work it requires an Internet connection. It is therefore impossible to use it on an offline computer – and that is highly recommended considering the omnipresent malware and significant value of funds controlled by this type of devices. It should also be taken into account that if the website [http://wallet.trezor.com](http://wallet.trezor.com/) is ever unavailable for whatever reason, it will be impossible to perform initialization or recovery, at least at that moment.

### Understanding the *recovery seed*

All three hardware wallets compatible with DMT (Trezor, Keepkey and Ledger Nano S) support the BIP-32/BIP-44/BIP-39 standards. Without getting too much into their details, it’s enough to know that as a result:

- the device stores an entire tree of private keys and corresponding payment addresses,
- all those keys are generated based on so-called *entropy* – which is essentially a unique number with the length of 16 up to 32 bytes,
- for a person to be able to memorize the *entropy*, it is converted into a set of 12 up to 24 words, later referred to as *recovery seed*. 

Initialization of the device is actually the activity of generating new *entropy* and presenting it to a user as a set of words, while recovery is a reversed activity – passing a set of words forming the *recovery seed* to the device, and then converting them to *entropy* inside the device. This *entropy* is the basis for generating an entire set of keys, which was splendidly described by Andreas Antonopolous in his magnificent book “Mastering Bitcoin” (see: [https://github.com/bitcoinbook/bitcoinbook/blob/second_edition/ch05.asciidoc#wallet-technology-details](https://github.com/bitcoinbook/bitcoinbook/blob/second_edition/ch05.asciidoc))

### Security principles

It’s good to be aware that knowing the set of words composing a *recovery seed* means having access to funds controlled by those keys. So, if they get in the wrong hands, we risk losing our funds. Analogically, if we lose the *recovery seed*, we will also lose access to our funds and there are no technical ways of retrieving them.

Standard methods of initialization and recovery of devices are designed in such a way that they should be safe even on an infected computer. But with significant funds controlled by such *recovery seed*, you don’t have to be paranoid to think that it’s better to perform such activities offline. This especially concerns users working on Windows computers or on computers, to which numerous files are downloaded from the Internet, exposing them to potential infections.

To such people (but not only them), I strongly recommend performing recovery or initialization in Linux OS launched from a [live CD](hw-initr-live-cd-linux.md) – after its work is done, there will be no data saved that could be sent to hostile server on the first occasion.

### Hardware wallet initialization and recovery in DMT

All functionalities described in this chapter are available in the *Hardware wallet initialization/recovery* dialog window, launched from the Tools menu of DMT application. They work like a standard wizard-type dialog, where interaction with the user is divided into separate steps.  

List of available functions:

- [Hardware wallet recovery - safe mode](hw-initr-safe-mode.md)
- [Hardware wallet recovery - convenient mode](hw-initr-conv-mode.md)
- [Hardware wallet recovery from hexadecimal entropy](hw-initr-entropy-mode.md)
- [Hardware wallet initialization with a newly generated seed words](hw-initr-new-seed.md)
- [Wiping hardware wallet](hw-initr-wipe.md)

> For Ledger Nano S wallets, only two of the above options are available (second and third) – other options are not supported by the official Ledger API, so it was not possible to create a GUI for them within DMT. This, however, is not a big problem, as these functions are available through the interface of the device itself. 

